"""
Loan Origination Service — ORM Models

Tables
------
loan_applications
    One row per loan application. Owns the state-machine lifecycle.

loan_offers
    The underwritten offer sent to the customer (one-to-one with the
    loan_application once underwriting passes).
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LoanState(StrEnum):
    DRAFT = "draft"
    UNDERWRITING = "underwriting"
    APPROVED = "approved"
    OFFER_SENT = "offer_sent"
    OFFER_ACCEPTED = "offer_accepted"
    DISBURSING = "disbursing"
    ACTIVE = "active"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LoanPurpose(StrEnum):
    BUSINESS = "business"
    PERSONAL = "personal"
    EDUCATION = "education"
    MEDICAL = "medical"
    OTHER = "other"


class DisbursementMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    MOBILE_MONEY = "mobile_money"
    WALLET = "wallet"


# ---------------------------------------------------------------------------
# loan_applications
# ---------------------------------------------------------------------------


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Loan request
    requested_amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default=LoanPurpose.OTHER)

    # Applicant signals (snapshotted at application time)
    kyc_verification_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    monthly_income_kobo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # State machine
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default=LoanState.DRAFT, index=True
    )

    # Decision
    decline_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    underwriting_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    offer: Mapped["LoanOffer | None"] = relationship(
        "LoanOffer", back_populates="loan", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# loan_offers
# ---------------------------------------------------------------------------


class LoanOffer(Base):
    __tablename__ = "loan_offers"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    loan_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("loan_applications.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Offer terms (may differ from requested if capped by underwriting)
    approved_amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_percentage_rate: Mapped[float] = mapped_column(Float, nullable=False)  # e.g. 0.24
    monthly_repayment_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_repayable_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)

    disbursement_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DisbursementMethod.BANK_TRANSFER
    )
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    loan: Mapped["LoanApplication"] = relationship("LoanApplication", back_populates="offer")
