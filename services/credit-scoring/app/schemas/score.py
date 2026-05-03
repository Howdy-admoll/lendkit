"""
Credit Scoring Service — Pydantic Schemas

Request / response models for the scoring API.
"""

from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Input signals — callers POST these when requesting a score
# ---------------------------------------------------------------------------


class KYCSignal(BaseModel):
    """Snapshot of KYC outcome from the KYC service."""

    verification_id: str
    status: str  # KYCStatus string: pending | initiated | in_review | approved | rejected | expired
    level: str  # basic | standard | enhanced
    risk_score: int | None = None  # 0–100 from provider (lower = better)
    is_pep: bool = False
    is_sanctioned: bool = False
    # Documents that passed verification (e.g. ["bvn", "nin", "passport"])
    verified_documents: list[str] = Field(default_factory=list)
    provider_reference: str | None = None


class IncomeSignal(BaseModel):
    """Income & employment data, typically from bank statement analysis."""

    monthly_income_kobo: int | None = None  # gross monthly income in kobo
    employment_type: str | None = (
        None  # salary | self_employed | business | contract | retired | unemployed
    )
    months_employed: int | None = None  # tenure at current employer
    # For self-employed / business owners
    business_age_months: int | None = None
    # Average monthly inflow from bank statement (last 3–6 months)
    avg_monthly_inflow_kobo: int | None = None
    # Number of months with data available
    statement_months: int | None = None


class RepaymentSignal(BaseModel):
    """Historical loan repayment data from credit bureau or internal ledger."""

    total_loans: int = 0
    on_time_payments: int = 0
    late_payments: int = 0  # 1–29 days late
    missed_payments: int = 0  # 30+ days late
    defaults: int = 0  # written off / settled for less
    # Maximum days past due in the last 24 months
    max_days_past_due: int = 0
    # Outstanding balance across all active loans in kobo
    outstanding_balance_kobo: int = 0
    # Whether the customer has any active loans currently
    has_active_loans: bool = False


class ScoreRequest(BaseModel):
    """Full scoring request — caller provides all available signals."""

    customer_id: str = Field(..., min_length=1, max_length=64)
    tenant_id: str = Field(..., min_length=1, max_length=64)
    # Requested loan amount in kobo — used for debt-to-income calculation
    requested_loan_amount_kobo: int | None = None
    trigger: str = "manual"  # manual | kyc_approved | refresh | loan_application

    # Signal buckets — provide what you have; scoring adapts to available signals
    kyc: KYCSignal | None = None
    income: IncomeSignal | None = None
    repayment: RepaymentSignal | None = None


# ---------------------------------------------------------------------------
# Factor — one scoring signal contribution
# ---------------------------------------------------------------------------


class ScoreFactorOut(BaseModel):
    category: str
    factor_key: str
    factor_label: str
    points_awarded: int
    points_possible: int
    detail: str | None
    impact: str  # positive | negative | neutral

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Score response
# ---------------------------------------------------------------------------


class CreditScoreOut(BaseModel):
    id: str
    customer_id: str
    tenant_id: str
    score: int | None
    tier: str | None
    status: str
    max_possible_score: int | None
    trigger: str | None
    kyc_verification_id: str | None
    recommendation: str | None
    decline_reasons: dict | None
    is_sanctioned: bool
    is_pep: bool
    factors: list[ScoreFactorOut] = Field(default_factory=list)
    computed_at: datetime | None
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class ScoreListOut(BaseModel):
    items: list[CreditScoreOut]
    total: int
