"""
Repayment Service — Pydantic Schemas (request / response models)
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums (mirrored from models for API surface)
# ---------------------------------------------------------------------------


class RepaymentStatus(str, Enum):
    CURRENT = "current"
    AT_RISK = "at_risk"
    DELINQUENT = "delinquent"
    DEFAULT = "default"
    SETTLED = "settled"
    WRITTEN_OFF = "written_off"


class RepaymentMethod(str, Enum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    USSD = "ussd"
    DIRECT_DEBIT = "direct_debit"
    WALLET = "wallet"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Inbound: webhook payload from payment provider
# ---------------------------------------------------------------------------


class RepaymentWebhookPayload(BaseModel):
    """Payment notification from Paystack / Flutterwave / etc."""

    provider: str = Field(..., description="Payment provider identifier, e.g. 'paystack'")
    provider_reference: str = Field(..., description="Provider's unique transaction reference")
    loan_id: str = Field(..., description="Loan UUID from the loan-origination service")
    amount_kobo: int = Field(..., gt=0, description="Payment amount in kobo")
    currency: str = Field(default="NGN", max_length=3)
    payment_method: RepaymentMethod = RepaymentMethod.UNKNOWN
    paid_at: datetime

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()


# ---------------------------------------------------------------------------
# Inbound: register a new loan account (called on disbursement event)
# ---------------------------------------------------------------------------


class RegisterLoanRequest(BaseModel):
    """
    Register a newly disbursed loan with the repayment service.

    Sent by the loan-origination service after funds hit the customer's account.
    """

    loan_id: str
    customer_id: str
    tenant_id: str
    original_principal_kobo: int = Field(..., gt=0)
    annual_percentage_rate: float = Field(..., gt=0.0, lt=5.0)
    tenure_months: int = Field(..., gt=0, le=360)
    monthly_installment_kobo: int = Field(..., gt=0)
    start_date: date
    first_due_date: date


# ---------------------------------------------------------------------------
# Outbound: installment row (used in schedule response)
# ---------------------------------------------------------------------------


class InstallmentOut(BaseModel):
    installment_number: int
    due_date: date
    opening_balance_kobo: int
    principal_due_kobo: int
    interest_due_kobo: int
    total_due_kobo: int
    closing_balance_kobo: int
    is_paid: bool
    paid_at: datetime | None
    paid_amount_kobo: int | None


# ---------------------------------------------------------------------------
# Outbound: single repayment record
# ---------------------------------------------------------------------------


class RepaymentRecordOut(BaseModel):
    id: str
    loan_account_id: str
    provider: str
    provider_reference: str
    amount_kobo: int
    penalty_portion_kobo: int
    interest_portion_kobo: int
    principal_portion_kobo: int
    overpayment_kobo: int
    balance_before_kobo: int
    balance_after_kobo: int
    payment_method: RepaymentMethod
    paid_at: datetime
    created_at: datetime


# ---------------------------------------------------------------------------
# Outbound: full loan repayment status
# ---------------------------------------------------------------------------


class LoanRepaymentStatusOut(BaseModel):
    loan_id: str
    customer_id: str
    tenant_id: str

    original_principal_kobo: int
    outstanding_principal_kobo: int
    accrued_interest_kobo: int
    accrued_penalties_kobo: int

    annual_percentage_rate: float
    tenure_months: int
    monthly_installment_kobo: int
    installments_paid: int

    status: RepaymentStatus
    days_past_due: int

    next_due_date: date | None
    last_payment_date: datetime | None
    last_payment_amount_kobo: int | None

    start_date: date
    settled_at: datetime | None

    @property
    def total_outstanding_kobo(self) -> int:
        return self.outstanding_principal_kobo + self.accrued_interest_kobo + self.accrued_penalties_kobo

    @property
    def installments_remaining(self) -> int:
        return max(0, self.tenure_months - self.installments_paid)

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Outbound: schedule response
# ---------------------------------------------------------------------------


class AmortizationScheduleOut(BaseModel):
    loan_id: str
    principal_kobo: int
    annual_percentage_rate: float
    tenure_months: int
    monthly_installment_kobo: int
    total_interest_kobo: int
    total_repayable_kobo: int
    schedule: list[InstallmentOut]


# ---------------------------------------------------------------------------
# Outbound: webhook acknowledgement
# ---------------------------------------------------------------------------


class WebhookAckOut(BaseModel):
    status: str
    loan_id: str
    amount_kobo: int
    provider_reference: str
    message: str


# ---------------------------------------------------------------------------
# Outbound: default loan summary (for /api/v1/defaults)
# ---------------------------------------------------------------------------


class DefaultedLoanOut(BaseModel):
    loan_id: str
    customer_id: str
    tenant_id: str
    days_past_due: int
    outstanding_principal_kobo: int
    accrued_penalties_kobo: int
    status: RepaymentStatus
    last_payment_date: datetime | None


class DefaultsListOut(BaseModel):
    threshold_days: int
    total: int
    loans: list[DefaultedLoanOut]
