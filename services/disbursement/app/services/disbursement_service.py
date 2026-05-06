"""
Disbursement Service — Business Logic Layer

Orchestrates the full disbursement flow:

  initiate()
    1. Idempotency check — reject duplicate loan_id.
    2. Resolve or create TransferRecipient.
    3. Generate idempotent transfer reference.
    4. Call provider.initiate_transfer().
    5. Transition state: PENDING → RECIPIENT_READY → TRANSFER_INITIATED.
    6. Persist DisbursementRequest + DisbursementEvent rows.

  handle_webhook()
    1. Parse and verify provider signature.
    2. Look up DisbursementRequest by transfer_code.
    3. Transition state (TRANSFER_INITIATED → COMPLETED/FAILED/REVERSED).
    4. On COMPLETED: emit loan.disbursed event to Redis Stream.
    5. On FAILED + retry eligible: schedule retry.

  retry_failed()
    Called by the retry worker for FAILED requests past their next_retry_at.
    Resets state to PENDING and calls initiate() again.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    DisbursementEvent,
    DisbursementProvider,
    DisbursementRequest,
    DisbursementState,
    TransferRecipient,
)
from app.engine.idempotency import generate_transfer_reference
from app.engine.providers.base import PaymentProvider, TransferStatus
from app.engine.state_machine import (
    DisbursementState as SM,
    InvalidTransitionError,
    is_retry_eligible,
    next_retry_delay_seconds,
    transition,
)
from app.schemas.disbursement import (
    DisbursementEventOut,
    DisbursementStatusOut,
    DisbursementState as SchemaState,
    InitiateDisbursementRequest,
    WebhookAckOut,
)
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Initiate disbursement
# ---------------------------------------------------------------------------


async def initiate(
    payload: InitiateDisbursementRequest,
    db: AsyncSession,
    provider: PaymentProvider,
) -> DisbursementStatusOut:
    """
    Start the disbursement process for a loan.

    Idempotent — calling twice with the same loan_id returns the existing
    DisbursementRequest rather than creating a duplicate.
    """
    # Idempotency: return existing if already initiated
    existing = await db.scalar(
        select(DisbursementRequest).where(
            DisbursementRequest.loan_id == payload.loan_id
        )
    )
    if existing:
        if existing.state == DisbursementState.COMPLETED:
            return _to_status_out(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Disbursement for loan_id={payload.loan_id} already exists "
                f"with state={existing.state.value}."
            ),
        )

    # Resolve recipient
    recipient = await _resolve_recipient(payload, db)

    # Create disbursement request
    attempt_number = 1
    reference = generate_transfer_reference(
        payload.loan_id, attempt_number, salt=settings.secret_key
    )

    req = DisbursementRequest(
        loan_id=payload.loan_id,
        customer_id=payload.customer_id,
        tenant_id=payload.tenant_id,
        amount_kobo=payload.amount_kobo,
        currency=payload.currency,
        state=DisbursementState.PENDING,
        attempt_count=0,
        max_attempts=settings.max_disbursement_attempts,
        provider=DisbursementProvider(payload.provider.value),
        recipient_id=recipient.id if recipient else None,
        transfer_reference=reference,
    )
    db.add(req)
    await db.flush()

    # Transition: PENDING → RECIPIENT_READY
    _record_event(db, req, SM.PENDING, SM.RECIPIENT_READY, "recipient_resolved")
    req.state = DisbursementState.RECIPIENT_READY

    # Transition: RECIPIENT_READY → TRANSFER_INITIATED
    try:
        result = await provider.initiate_transfer(
            recipient_code=recipient.recipient_code,
            amount_kobo=payload.amount_kobo,
            reference=reference,
            reason=f"Loan disbursement — {payload.loan_id[:8]}",
            currency=payload.currency,
        )
    except Exception as exc:
        # Transfer call failed — record and move to FAILED
        req.state = DisbursementState.FAILED
        req.attempt_count = 1
        req.failure_reason = str(exc)
        _record_event(
            db, req, SM.RECIPIENT_READY, SM.FAILED,
            "transfer_initiation_error", detail=str(exc)
        )
        logger.error(
            "Disbursement transfer initiation failed",
            extra={"loan_id": payload.loan_id, "error": str(exc)},
        )
        await db.flush()
        return _to_status_out(req)

    req.state = DisbursementState.TRANSFER_INITIATED
    req.attempt_count = 1
    req.transfer_code = result.transfer_code
    _record_event(
        db, req, SM.RECIPIENT_READY, SM.TRANSFER_INITIATED,
        "transfer_initiated",
        provider_reference=result.transfer_code,
    )

    await db.flush()
    logger.info(
        "Disbursement transfer initiated",
        extra={
            "loan_id": payload.loan_id,
            "transfer_code": result.transfer_code,
            "amount_kobo": payload.amount_kobo,
        },
    )
    return _to_status_out(req)


# ---------------------------------------------------------------------------
# Handle provider webhook
# ---------------------------------------------------------------------------


async def handle_webhook(
    transfer_code: str,
    transfer_status: TransferStatus,
    db: AsyncSession,
) -> WebhookAckOut:
    """
    Process a transfer webhook from Paystack.

    Maps provider status → DisbursementState, updates the request,
    and emits domain events on COMPLETED.
    """
    req = await db.scalar(
        select(DisbursementRequest).where(
            DisbursementRequest.transfer_code == transfer_code
        )
    )
    if not req:
        logger.warning("Webhook for unknown transfer_code", extra={"transfer_code": transfer_code})
        return WebhookAckOut(
            status="ignored",
            event="unknown",
            transfer_code=transfer_code,
            message="No disbursement request found for this transfer_code.",
        )

    if req.is_terminal:
        return WebhookAckOut(
            status="already_terminal",
            event=transfer_status.value,
            transfer_code=transfer_code,
            message=f"Disbursement already in terminal state {req.state.value}.",
        )

    prev_sm = SM(req.state.value)

    if transfer_status == TransferStatus.SUCCESS:
        target_sm = SM.COMPLETED
        req.state = DisbursementState.COMPLETED
        req.completed_at = datetime.now(timezone.utc)
        _record_event(
            db, req, prev_sm, target_sm, "transfer_success",
            provider_reference=transfer_code,
        )
        # Emit loan.disbursed domain event
        await _emit_disbursed_event(req)
        logger.info("Loan disbursed", extra={"loan_id": req.loan_id, "amount_kobo": req.amount_kobo})

    elif transfer_status == TransferStatus.FAILED:
        target_sm = SM.FAILED
        req.state = DisbursementState.FAILED
        req.failure_reason = "Transfer rejected by bank."
        _record_event(
            db, req, prev_sm, target_sm, "transfer_failed",
            provider_reference=transfer_code,
        )
        # Schedule retry if eligible
        if is_retry_eligible(SM.FAILED, req.attempt_count):
            delay = next_retry_delay_seconds(req.attempt_count)
            req.next_retry_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + delay, tz=timezone.utc
            )
        logger.warning("Disbursement transfer failed", extra={"loan_id": req.loan_id})

    elif transfer_status == TransferStatus.REVERSED:
        target_sm = SM.REVERSED
        req.state = DisbursementState.REVERSED
        req.failure_reason = "Transfer reversed by provider."
        _record_event(
            db, req, prev_sm, target_sm, "transfer_reversed",
            provider_reference=transfer_code,
        )
        logger.error("Disbursement reversed", extra={"loan_id": req.loan_id})

    await db.flush()
    return WebhookAckOut(
        status="processed",
        event=transfer_status.value,
        transfer_code=transfer_code,
        message=f"Disbursement state updated to {req.state.value}.",
    )


# ---------------------------------------------------------------------------
# Retry a failed disbursement
# ---------------------------------------------------------------------------


async def retry_disbursement(
    loan_id: str,
    db: AsyncSession,
    provider: PaymentProvider,
) -> DisbursementStatusOut:
    """Reset a FAILED disbursement to PENDING and re-initiate the transfer."""
    req = await db.scalar(
        select(DisbursementRequest).where(DisbursementRequest.loan_id == loan_id)
    )
    if not req:
        raise HTTPException(status_code=404, detail=f"No disbursement for loan_id={loan_id}")

    if not req.can_retry:
        raise HTTPException(
            status_code=422,
            detail=f"Disbursement cannot be retried (state={req.state.value}, attempts={req.attempt_count})",
        )

    # Reset to PENDING for re-initiation
    _record_event(db, req, SM(req.state.value), SM.PENDING, "retry_scheduled")
    req.state = DisbursementState.PENDING
    req.failure_reason = None
    req.next_retry_at = None
    await db.flush()

    # Generate new reference for this attempt
    attempt_number = req.attempt_count + 1
    reference = generate_transfer_reference(
        req.loan_id, attempt_number, salt=settings.secret_key
    )
    req.transfer_reference = reference

    recipient = await db.get(TransferRecipient, req.recipient_id)
    if not recipient:
        raise HTTPException(status_code=422, detail="No recipient found for retry.")

    try:
        result = await provider.initiate_transfer(
            recipient_code=recipient.recipient_code,
            amount_kobo=req.amount_kobo,
            reference=reference,
            reason=f"Loan disbursement retry — {req.loan_id[:8]}",
            currency=req.currency,
        )
        req.state = DisbursementState.TRANSFER_INITIATED
        req.attempt_count = attempt_number
        req.transfer_code = result.transfer_code
        _record_event(
            db, req, SM.PENDING, SM.TRANSFER_INITIATED,
            "retry_transfer_initiated", provider_reference=result.transfer_code,
        )
    except Exception as exc:
        req.state = DisbursementState.FAILED
        req.attempt_count = attempt_number
        req.failure_reason = str(exc)
        _record_event(db, req, SM.PENDING, SM.FAILED, "retry_failed", detail=str(exc))

    await db.flush()
    return _to_status_out(req)


# ---------------------------------------------------------------------------
# Get disbursement status
# ---------------------------------------------------------------------------


async def get_status(loan_id: str, db: AsyncSession) -> DisbursementStatusOut:
    req = await db.scalar(
        select(DisbursementRequest).where(DisbursementRequest.loan_id == loan_id)
    )
    if not req:
        raise HTTPException(
            status_code=404, detail=f"No disbursement found for loan_id={loan_id}"
        )
    return _to_status_out(req)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _resolve_recipient(
    payload: InitiateDisbursementRequest,
    db: AsyncSession,
) -> TransferRecipient:
    """Fetch existing recipient by ID, or raise if not found."""
    if payload.recipient_id:
        recipient = await db.get(TransferRecipient, payload.recipient_id)
        if not recipient:
            raise HTTPException(
                status_code=404,
                detail=f"TransferRecipient {payload.recipient_id} not found.",
            )
        return recipient
    raise HTTPException(
        status_code=422,
        detail="recipient_id is required. Create a TransferRecipient first via POST /api/v1/recipients.",
    )


def _record_event(
    db: AsyncSession,
    req: DisbursementRequest,
    from_state: SM,
    to_state: SM,
    event_type: str,
    detail: str | None = None,
    provider_reference: str | None = None,
) -> None:
    db.add(
        DisbursementEvent(
            disbursement_request_id=req.id,
            from_state=from_state.value,
            to_state=to_state.value,
            event_type=event_type,
            detail=detail,
            provider_reference=provider_reference,
        )
    )


async def _emit_disbursed_event(req: DisbursementRequest) -> None:
    """Emit loan.disbursed to Redis Stream for the repayment service to consume."""
    try:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.redis_stream_url)
        event = {
            "event": "loan.disbursed",
            "loan_id": req.loan_id,
            "customer_id": req.customer_id,
            "tenant_id": req.tenant_id,
            "amount_kobo": str(req.amount_kobo),
            "transfer_code": req.transfer_code or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await redis.xadd(settings.disbursement_events_stream, event)
        await redis.aclose()
    except Exception as exc:
        logger.error("Failed to emit loan.disbursed event", extra={"error": str(exc)})


def _to_status_out(req: DisbursementRequest) -> DisbursementStatusOut:
    return DisbursementStatusOut(
        id=req.id,
        loan_id=req.loan_id,
        customer_id=req.customer_id,
        tenant_id=req.tenant_id,
        amount_kobo=req.amount_kobo,
        currency=req.currency,
        state=SchemaState(req.state.value),
        attempt_count=req.attempt_count,
        max_attempts=req.max_attempts,
        provider=req.provider.value,
        transfer_code=req.transfer_code,
        transfer_reference=req.transfer_reference,
        failure_reason=req.failure_reason,
        next_retry_at=req.next_retry_at,
        created_at=req.created_at,
        updated_at=req.updated_at,
        completed_at=req.completed_at,
        events=[
            DisbursementEventOut(
                id=e.id,
                from_state=e.from_state,
                to_state=e.to_state,
                event_type=e.event_type,
                detail=e.detail,
                provider_reference=e.provider_reference,
                created_at=e.created_at,
            )
            for e in (req.events or [])
        ],
    )
