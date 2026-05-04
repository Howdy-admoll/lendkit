"""
Repayment Service — SQLAlchemy ORM Models

Three tables:
  loan_accounts        — live repayment state for each active loan
  repayment_records    — immutable ledger of every payment received
  schedule_installments — the amortization schedule rows (generated on disbursement)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RepaymentStatus(str, PyEnum):
    CURRENT = "current"
    AT_RISK = "at_risk"
    DELINQUENT = "delinquent"
    DEFAULT = "default"
    SETTLED = "settled"
    WRITTEN_OFF = "written_off"


class RepaymentMethod(str, PyEnum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    USSD = "ussd"
    DIRECT_DEBIT = "direct_debit"
    WALLET = "wallet"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# LoanAccount — live state of an active loan
# ---------------------------------------------------------------------------


class LoanAccount(Base):
    """
    One row per loan being tracked by the repayment service.

    Created when loan-origination emits a `loan.disbursed` event.
    Updated on every payment, daily interest accrual, and status change.
    """

    __tablename__ = "loan_accounts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )

    # External references (loan-origination service owns these)
    loan_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Loan terms (copied from loan offer at disbursement)
    original_principal_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    annual_percentage_rate: Mapped[float] = mapped_column(Float, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_installment_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    first_due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Live balances
    outstanding_principal_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accrued_interest_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    accrued_penalties_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Payment tracking
    installments_paid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_payment_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_payment_amount_kobo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Delinquency
    days_past_due: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[RepaymentStatus] = mapped_column(
        Enum(RepaymentStatus), default=RepaymentStatus.CURRENT, nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    repayment_records: Mapped[list[RepaymentRecord]] = relationship(
        back_populates="loan_account", cascade="all, delete-orphan", lazy="selectin"
    )
    schedule_installments: Mapped[list[ScheduleInstallment]] = relationship(
        back_populates="loan_account", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_loan_accounts_customer_tenant", "customer_id", "tenant_id"),
        Index("ix_loan_accounts_status", "status"),
        Index("ix_loan_accounts_next_due_date", "next_due_date"),
    )

    @property
    def total_outstanding_kobo(self) -> int:
        return (
            self.outstanding_principal_kobo
            + self.accrued_interest_kobo
            + self.accrued_penalties_kobo
        )

    @property
    def installments_remaining(self) -> int:
        return max(0, self.tenure_months - self.installments_paid)


# ---------------------------------------------------------------------------
# RepaymentRecord — immutable ledger entry per payment
# ---------------------------------------------------------------------------


class RepaymentRecord(Base):
    """
    Immutable record of a single payment event.

    Never updated after creation — corrections are represented as
    reversal + re-application pairs.
    """

    __tablename__ = "repayment_records"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    loan_account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("loan_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Idempotency — dedupe by provider_reference
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(128), nullable=False)

    # Payment amount breakdown (kobo)
    amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    penalty_portion_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    interest_portion_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    principal_portion_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    overpayment_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Snapshot balances
    balance_before_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)

    payment_method: Mapped[RepaymentMethod] = mapped_column(
        Enum(RepaymentMethod), default=RepaymentMethod.UNKNOWN, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)

    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # Relationship
    loan_account: Mapped[LoanAccount] = relationship(back_populates="repayment_records")

    __table_args__ = (
        UniqueConstraint("provider", "provider_reference", name="uq_repayment_provider_ref"),
        Index("ix_repayment_records_loan_account", "loan_account_id"),
        Index("ix_repayment_records_paid_at", "paid_at"),
    )


# ---------------------------------------------------------------------------
# ScheduleInstallment — amortization schedule row
# ---------------------------------------------------------------------------


class ScheduleInstallment(Base):
    """
    One row of the amortization schedule.

    Generated at disbursement time and stored for reference / statement
    generation. Rows are marked paid as repayments arrive.
    """

    __tablename__ = "schedule_installments"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    loan_account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("loan_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Amounts (kobo)
    opening_balance_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    principal_due_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interest_due_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_due_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closing_balance_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Payment state
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_amount_kobo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Relationship
    loan_account: Mapped[LoanAccount] = relationship(back_populates="schedule_installments")

    __table_args__ = (
        UniqueConstraint(
            "loan_account_id", "installment_number", name="uq_schedule_installment_number"
        ),
        Index("ix_schedule_installments_due_date", "due_date"),
        Index("ix_schedule_installments_unpaid", "loan_account_id", "is_paid"),
    )
