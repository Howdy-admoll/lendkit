"""
LendKit — Repayment Tracking & Default Detection Service

Responsibilities:
  - Record incoming repayments (webhook from payment provider)
  - Calculate outstanding balance and accrued interest daily
  - Detect delinquency (missed payments past grace period)
  - Classify default risk: current | at_risk | delinquent | default
  - Trigger collections workflow for defaulted loans
  - Emit domain events: repayment.received, loan.default_detected

Default detection runs via Celery beat every hour.
Grace period and penalty rates are configurable per tenant.

Status: SCAFFOLD — schemas and route stubs defined.
        Good first issue: implement AmortizationSchedule.generate()
"""
from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal

from fastapi import FastAPI, status
from pydantic import BaseModel, Field

app = FastAPI(
    title="LendKit Repayment Service",
    description="Repayment tracking and default detection",
    version="0.1.0-alpha",
)


# ---------------------------------------------------------------------------
# Domain Enums
# ---------------------------------------------------------------------------

class RepaymentStatus(str, Enum):
    CURRENT     = "current"      # all payments up to date
    AT_RISK     = "at_risk"      # approaching due date, not yet missed
    DELINQUENT  = "delinquent"   # 1–90 days past due
    DEFAULT     = "default"      # 90+ days past due
    SETTLED     = "settled"      # fully repaid
    WRITTEN_OFF = "written_off"  # irrecoverable, written off


class RepaymentMethod(str, Enum):
    CARD           = "card"
    BANK_TRANSFER  = "bank_transfer"
    USSD           = "ussd"
    DIRECT_DEBIT   = "direct_debit"
    WALLET         = "wallet"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RepaymentWebhookPayload(BaseModel):
    """Inbound payment notification from Paystack / Flutterwave / etc."""
    provider: str
    provider_reference: str
    loan_id: str
    amount: float = Field(..., gt=0)
    currency: str = Field(default="NGN")
    payment_method: RepaymentMethod
    paid_at: datetime


class RepaymentRecord(BaseModel):
    repayment_id: str
    loan_id: str
    amount: float
    principal_portion: float
    interest_portion: float
    penalty_portion: float
    balance_before: float
    balance_after: float
    payment_method: str
    paid_at: datetime


class LoanRepaymentStatus(BaseModel):
    loan_id: str
    customer_id: str
    original_amount: float
    outstanding_principal: float
    accrued_interest: float
    accrued_penalties: float
    total_outstanding: float
    status: RepaymentStatus
    days_past_due: int
    next_due_date: date | None
    next_due_amount: float | None
    repayments_made: int
    repayments_remaining: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy", "service": "repayment", "version": "0.1.0-alpha"}


@app.post(
    "/api/v1/repayments/webhook",
    status_code=status.HTTP_200_OK,
    tags=["Repayments"],
    summary="Receive payment notification from provider",
)
async def receive_payment_webhook(payload: RepaymentWebhookPayload):
    """
    TODO: Full implementation:
    1. Verify HMAC signature from provider
    2. Idempotency check (dedupe by provider_reference)
    3. Fetch loan from DB
    4. Apply payment: allocate to penalties → interest → principal
    5. Update loan balance
    6. Emit repayment.received event
    7. Check if loan is now fully settled
    """
    return {
        "status": "received",
        "loan_id": payload.loan_id,
        "amount": payload.amount,
        "message": "Payment recorded (stub)",
    }


@app.get(
    "/api/v1/repayments/{loan_id}",
    response_model=LoanRepaymentStatus,
    tags=["Repayments"],
    summary="Get repayment status for a loan",
)
async def get_repayment_status(loan_id: str):
    """TODO: Fetch from DB."""
    return LoanRepaymentStatus(
        loan_id=loan_id,
        customer_id="stub",
        original_amount=50000.0,
        outstanding_principal=40000.0,
        accrued_interest=1200.0,
        accrued_penalties=0.0,
        total_outstanding=41200.0,
        status=RepaymentStatus.CURRENT,
        days_past_due=0,
        next_due_date=date.today(),
        next_due_amount=5000.0,
        repayments_made=2,
        repayments_remaining=10,
    )


@app.get("/api/v1/repayments/{loan_id}/schedule", tags=["Repayments"])
async def get_amortization_schedule(loan_id: str):
    """
    Return the full amortization schedule for a loan.
    TODO: Implement AmortizationSchedule.generate(principal, rate, tenure)
    """
    return {"loan_id": loan_id, "schedule": [], "status": "not_implemented"}


@app.get("/api/v1/defaults", tags=["Default Detection"])
async def list_defaulted_loans(days_past_due: int = 90):
    """
    List loans in default.
    Runs automatically via Celery beat — this endpoint is for manual review.
    """
    # TODO: query DB for loans where days_past_due >= threshold
    return {"loans_in_default": [], "threshold_days": days_past_due, "status": "not_implemented"}
