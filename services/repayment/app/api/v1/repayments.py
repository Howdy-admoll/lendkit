"""
Repayment Service — API v1 Routes
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.repayment import (
    AmortizationScheduleOut,
    DefaultsListOut,
    LoanRepaymentStatusOut,
    RegisterLoanRequest,
    RepaymentWebhookPayload,
    WebhookAckOut,
)
from app.services import repayment_service as svc

router = APIRouter(prefix="/api/v1", tags=["Repayments"])

DB = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Register a disbursed loan
# ---------------------------------------------------------------------------


@router.post(
    "/loans",
    response_model=LoanRepaymentStatusOut,
    status_code=201,
    summary="Register a newly disbursed loan",
    description=(
        "Called by the loan-origination service after a loan is disbursed. "
        "Persists the loan account and generates the amortization schedule."
    ),
)
async def register_loan(payload: RegisterLoanRequest, db: DB) -> LoanRepaymentStatusOut:
    return await svc.register_loan(payload, db)


# ---------------------------------------------------------------------------
# Payment webhook
# ---------------------------------------------------------------------------


@router.post(
    "/repayments/webhook",
    response_model=WebhookAckOut,
    status_code=200,
    summary="Receive payment notification from payment provider",
    description=(
        "Idempotent endpoint — safe to retry. Duplicate provider_reference "
        "values return 409. HMAC signature verification is performed in middleware."
    ),
)
async def receive_webhook(payload: RepaymentWebhookPayload, db: DB) -> WebhookAckOut:
    return await svc.apply_payment(payload, db)


# ---------------------------------------------------------------------------
# Loan repayment status
# ---------------------------------------------------------------------------


@router.get(
    "/repayments/{loan_id}",
    response_model=LoanRepaymentStatusOut,
    summary="Get repayment status for a loan",
)
async def get_repayment_status(loan_id: str, db: DB) -> LoanRepaymentStatusOut:
    return await svc.get_loan_status(loan_id, db)


# ---------------------------------------------------------------------------
# Amortization schedule
# ---------------------------------------------------------------------------


@router.get(
    "/repayments/{loan_id}/schedule",
    response_model=AmortizationScheduleOut,
    summary="Get full amortization schedule for a loan",
    description=(
        "Returns all installment rows — paid and unpaid — with per-row "
        "principal/interest split. Useful for statements and customer-facing schedule views."
    ),
)
async def get_amortization_schedule(loan_id: str, db: DB) -> AmortizationScheduleOut:
    return await svc.get_schedule(loan_id, db)


# ---------------------------------------------------------------------------
# Defaults list
# ---------------------------------------------------------------------------


@router.get(
    "/defaults",
    response_model=DefaultsListOut,
    summary="List loans in default",
    description=(
        "Returns all loans with days_past_due ≥ threshold. "
        "Default threshold is 90 days (CBN definition). "
        "Also used by the delinquency worker to build the collections queue."
    ),
)
async def list_defaults(
    db: DB,
    days_past_due: int = Query(default=90, ge=1, description="Minimum days past due"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> DefaultsListOut:
    return await svc.get_defaults(days_past_due, db, limit=limit, offset=offset)
