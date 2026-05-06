"""Disbursement Service — API v1 Routes."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.engine.providers.paystack import PaystackProvider
from app.schemas.disbursement import (
    CreateRecipientRequest,
    DisbursementStatusOut,
    InitiateDisbursementRequest,
    PaystackWebhookPayload,
    TransferRecipientOut,
    WebhookAckOut,
)
from app.services import disbursement_service as svc
from app.services import recipient_service as rec_svc

router = APIRouter(prefix="/api/v1", tags=["Disbursement"])
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]


def _get_provider() -> PaystackProvider:
    return PaystackProvider(secret_key=settings.paystack_secret_key)


# ---------------------------------------------------------------------------
# Initiate disbursement
# ---------------------------------------------------------------------------


@router.post(
    "/disbursements",
    response_model=DisbursementStatusOut,
    status_code=202,
    summary="Initiate a loan disbursement",
    description=(
        "Called by the loan-origination service when a loan offer is accepted. "
        "Idempotent — safe to retry with the same loan_id."
    ),
)
async def initiate_disbursement(
    payload: InitiateDisbursementRequest,
    db: DB,
) -> DisbursementStatusOut:
    provider = _get_provider()
    return await svc.initiate(payload, db, provider)


# ---------------------------------------------------------------------------
# Get disbursement status
# ---------------------------------------------------------------------------


@router.get(
    "/disbursements/{loan_id}",
    response_model=DisbursementStatusOut,
    summary="Get disbursement status for a loan",
)
async def get_disbursement_status(loan_id: str, db: DB) -> DisbursementStatusOut:
    return await svc.get_status(loan_id, db)


# ---------------------------------------------------------------------------
# Retry a failed disbursement
# ---------------------------------------------------------------------------


@router.post(
    "/disbursements/{loan_id}/retry",
    response_model=DisbursementStatusOut,
    summary="Manually retry a failed disbursement",
    description="Resets a FAILED disbursement to PENDING and re-initiates the transfer.",
)
async def retry_disbursement(loan_id: str, db: DB) -> DisbursementStatusOut:
    provider = _get_provider()
    return await svc.retry_disbursement(loan_id, db, provider)


# ---------------------------------------------------------------------------
# Paystack transfer webhook
# ---------------------------------------------------------------------------


@router.post(
    "/disbursements/webhook/paystack",
    response_model=WebhookAckOut,
    status_code=200,
    summary="Receive Paystack transfer webhook",
    description=(
        "Paystack calls this endpoint with transfer.success / transfer.failed / "
        "transfer.reversed events. HMAC-SHA512 signature is verified before processing."
    ),
)
async def paystack_webhook(
    request: Request,
    db: DB,
    x_paystack_signature: str = Header(default=""),
) -> WebhookAckOut:
    raw_body = await request.body()

    # Verify HMAC signature
    provider = _get_provider()
    if settings.paystack_webhook_secret and not provider.verify_webhook(
        raw_body, x_paystack_signature
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Paystack webhook signature.",
        )

    body = await request.json()
    parsed = PaystackProvider.parse_webhook_event(body)

    if parsed is None:
        return WebhookAckOut(
            status="ignored",
            event=body.get("event", "unknown"),
            transfer_code=None,
            message="Event not handled by disbursement service.",
        )

    transfer_code, transfer_status = parsed
    return await svc.handle_webhook(transfer_code, transfer_status, db)


# ---------------------------------------------------------------------------
# Transfer recipients
# ---------------------------------------------------------------------------


@router.post(
    "/recipients",
    response_model=TransferRecipientOut,
    status_code=201,
    summary="Register a borrower's bank account as a transfer recipient",
)
async def create_recipient(
    payload: CreateRecipientRequest,
    db: DB,
) -> TransferRecipientOut:
    provider = _get_provider()
    return await rec_svc.create_recipient(payload, db, provider)


@router.get(
    "/recipients/{recipient_id}",
    response_model=TransferRecipientOut,
    summary="Get a transfer recipient by ID",
)
async def get_recipient(recipient_id: str, db: DB) -> TransferRecipientOut:
    return await rec_svc.get_recipient(recipient_id, db)


@router.get(
    "/recipients/customer/{customer_id}",
    response_model=list[TransferRecipientOut],
    summary="List all active recipients for a customer",
)
async def list_recipients(customer_id: str, db: DB) -> list[TransferRecipientOut]:
    return await rec_svc.list_customer_recipients(customer_id, db)
