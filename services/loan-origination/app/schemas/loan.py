"""
Loan Origination Service — Pydantic Schemas
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class LoanApplicationRequest(BaseModel):
    customer_id: str
    tenant_id: str

    # Loan details
    requested_amount_kobo: int = Field(..., gt=0, description="Loan amount in kobo (₦1 = 100 kobo)")
    tenure_months: int = Field(..., ge=3, le=36, description="Repayment period in months")
    purpose: str = Field(
        default="other",
        description="business | personal | education | medical | other",
    )

    # Applicant signals — snapshotted at application time
    kyc_verification_id: str | None = None
    monthly_income_kobo: int | None = Field(default=None, gt=0)
    employment_type: str | None = None

    @field_validator("purpose")
    @classmethod
    def normalise_purpose(cls, v: str) -> str:
        return v.lower()


class OfferAcceptRequest(BaseModel):
    disbursement_method: str = Field(
        default="bank_transfer",
        description="bank_transfer | mobile_money | wallet",
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class LoanOfferOut(BaseModel):
    offer_id: str
    approved_amount_kobo: int
    approved_amount_ngn: float
    tenure_months: int
    annual_percentage_rate: float
    monthly_repayment_kobo: int
    monthly_repayment_ngn: float
    total_repayable_kobo: int
    total_repayable_ngn: float
    disbursement_method: str
    is_accepted: bool
    expires_at: datetime

    model_config = {"from_attributes": True}


class LoanApplicationOut(BaseModel):
    loan_id: str
    customer_id: str
    tenant_id: str
    state: str
    requested_amount_kobo: int
    requested_amount_ngn: float
    tenure_months: int
    purpose: str
    credit_score: int | None
    credit_tier: str | None
    decline_reasons: dict[str, Any] | None
    offer: LoanOfferOut | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LoanListOut(BaseModel):
    items: list[LoanApplicationOut]
    total: int


# ---------------------------------------------------------------------------
# Internal transfer objects (not exposed via API)
# ---------------------------------------------------------------------------


class UnderwritingDecision(BaseModel):
    """Result returned by the underwriting engine."""

    approved: bool
    approved_amount_kobo: int = 0
    tenure_months: int = 0
    annual_percentage_rate: float = 0.0
    monthly_repayment_kobo: int = 0
    total_repayable_kobo: int = 0
    decline_reasons: dict[str, str] = Field(default_factory=dict)
    notes: str = ""
