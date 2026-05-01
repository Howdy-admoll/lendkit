"""
LendKit — Loan Origination & Disbursement Service

Orchestrates the full loan lifecycle:
  Application → KYC Check → Credit Score → Approval → Disbursement → Active

Integrates with:
  - KYC Service      : verify applicant identity
  - Credit Scoring   : evaluate creditworthiness
  - Disbursement API : Paystack / Flutterwave / Stripe payout
  - Event Bus        : emits loan.disbursed, loan.rejected events

Status: SCAFFOLD — workflow states and routes defined.
        Good first issue: implement DisbursementService for Paystack.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from fastapi import FastAPI, status
from pydantic import BaseModel, Field

app = FastAPI(
    title="LendKit Loan Origination Service",
    description="End-to-end loan origination and disbursement pipeline",
    version="0.1.0-alpha",
)


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

class LoanState(str, Enum):
    DRAFT           = "draft"
    KYC_PENDING     = "kyc_pending"
    KYC_APPROVED    = "kyc_approved"
    SCORING         = "scoring"
    UNDERWRITING    = "underwriting"
    APPROVED        = "approved"
    OFFER_SENT      = "offer_sent"
    OFFER_ACCEPTED  = "offer_accepted"
    DISBURSING      = "disbursing"
    ACTIVE          = "active"
    REJECTED        = "rejected"
    CANCELLED       = "cancelled"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoanApplicationRequest(BaseModel):
    customer_id: str
    tenant_id: str
    requested_amount: float = Field(..., gt=0)
    tenure_months: int = Field(..., ge=1, le=360)
    purpose: str = Field(..., description="Business | Personal | Education | Medical | Other")
    monthly_income: float = Field(..., gt=0)
    employment_type: str


class LoanApplicationResponse(BaseModel):
    loan_id: str
    customer_id: str
    state: LoanState
    requested_amount: float
    message: str
    next_steps: list[str]
    created_at: datetime


class LoanOffer(BaseModel):
    loan_id: str
    approved_amount: float
    tenure_months: int
    interest_rate: float    # APR
    monthly_repayment: float
    total_repayable: float
    disbursement_method: str
    offer_expires_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy", "service": "loan-origination", "version": "0.1.0-alpha"}


@app.post(
    "/api/v1/loans",
    response_model=LoanApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Loans"],
    summary="Submit a loan application",
)
async def apply_for_loan(payload: LoanApplicationRequest) -> LoanApplicationResponse:
    """
    TODO: Full implementation:
    1. Validate tenant + customer
    2. Check KYC status via KYC service
    3. Trigger credit scoring
    4. Run underwriting rules
    5. Generate loan offer
    6. Notify customer

    Currently creates a stub loan record.
    """
    import uuid
    loan_id = f"loan_{uuid.uuid4().hex[:12]}"

    return LoanApplicationResponse(
        loan_id=loan_id,
        customer_id=payload.customer_id,
        state=LoanState.KYC_PENDING,
        requested_amount=payload.requested_amount,
        message="Loan application received. KYC verification in progress.",
        next_steps=[
            "Complete KYC verification if not already done",
            "You will be notified once a credit decision is made",
        ],
        created_at=datetime.now(timezone.utc),
    )


@app.get("/api/v1/loans/{loan_id}", tags=["Loans"])
async def get_loan(loan_id: str):
    """Get loan application status and details."""
    return {"loan_id": loan_id, "status": "not_implemented"}


@app.post("/api/v1/loans/{loan_id}/accept-offer", tags=["Loans"])
async def accept_loan_offer(loan_id: str):
    """
    Customer accepts the loan offer.
    Triggers disbursement pipeline.
    """
    # TODO: validate offer hasn't expired, trigger disbursement
    return {"loan_id": loan_id, "state": LoanState.DISBURSING, "message": "Disbursement initiated"}


@app.get("/api/v1/loans/customer/{customer_id}", tags=["Loans"])
async def list_customer_loans(customer_id: str):
    """List all loans for a customer."""
    return {"customer_id": customer_id, "loans": [], "status": "not_implemented"}
