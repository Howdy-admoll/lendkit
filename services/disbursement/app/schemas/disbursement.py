"""Disbursement Service — Pydantic Schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class DisbursementState(str, Enum):
    PENDING = "pending"
    RECIPIENT_READY = "recipient_ready"
    TRANSFER_INITIATED = "transfer_initiated"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"
    CANCELLED = "cancelled"


class DisbursementProvider(str, Enum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    MOCK = "mock"


# ---------------------------------------------------------------------------
# Inbound: initiate disbursement (called by loan origination on offer_accepted)
# ---------------------------------------------------------------------------


class InitiateDisbursementRequest(BaseModel):
    loan_id: str = Field(..., description="Loan UUID from loan-origination service")
    customer_id: str
    tenant_id: str
    amount_kobo: int = Field(..., gt=0, description="Disbursement amount in kobo")
    currency: str = Field(default="NGN", max_length=3)
    recipient_id: str | None = Field(
        None, description="Existing TransferRecipient ID — skip if creating new"
    )
    provider: DisbursementProvider = DisbursementProvider.PAYSTACK

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()


# ---------------------------------------------------------------------------
# Inbound: register a transfer recipient (borrower's bank account)
# ---------------------------------------------------------------------------


class CreateRecipientRequest(BaseModel):
    customer_id: str
    tenant_id: str
    account_number: str = Field(..., min_length=10, max_length=10)
    bank_code: str = Field(..., min_length=3, max_length=6)
    bank_name: str
    account_name: str
    currency: str = Field(default="NGN", max_length=3)
    provider: DisbursementProvider = DisbursementProvider.PAYSTACK


# ---------------------------------------------------------------------------
# Inbound: Paystack webhook
# ---------------------------------------------------------------------------


class PaystackWebhookPayload(BaseModel):
    event: str
    data: dict


# ---------------------------------------------------------------------------
# Outbound: transfer recipient
# ---------------------------------------------------------------------------


class TransferRecipientOut(BaseModel):
    id: str
    customer_id: str
    tenant_id: str
    account_number: str
    bank_code: str
    bank_name: str
    account_name: str
    currency: str
    provider: DisbursementProvider
    recipient_code: str
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Outbound: disbursement event row
# ---------------------------------------------------------------------------


class DisbursementEventOut(BaseModel):
    id: str
    from_state: str
    to_state: str
    event_type: str
    detail: str | None
    provider_reference: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Outbound: disbursement request status
# ---------------------------------------------------------------------------


class DisbursementStatusOut(BaseModel):
    id: str
    loan_id: str
    customer_id: str
    tenant_id: str
    amount_kobo: int
    currency: str
    state: DisbursementState
    attempt_count: int
    max_attempts: int
    provider: DisbursementProvider
    transfer_code: str | None
    transfer_reference: str | None
    failure_reason: str | None
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    events: list[DisbursementEventOut]


# ---------------------------------------------------------------------------
# Outbound: webhook acknowledgement
# ---------------------------------------------------------------------------


class WebhookAckOut(BaseModel):
    status: str
    event: str
    transfer_code: str | None
    message: str
