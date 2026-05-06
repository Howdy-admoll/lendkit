"""
Disbursement Service — SQLAlchemy ORM Models

Three tables:
  transfer_recipients   — bank account details registered with Paystack
  disbursement_requests — one per loan, tracks the full disbursement lifecycle
  disbursement_events   — immutable log of every state transition
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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


class DisbursementState(str, PyEnum):
    PENDING = "pending"
    RECIPIENT_READY = "recipient_ready"
    TRANSFER_INITIATED = "transfer_initiated"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"
    CANCELLED = "cancelled"


class DisbursementProvider(str, PyEnum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    MOCK = "mock"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# TransferRecipient — bank account registered with provider
# ---------------------------------------------------------------------------


class TransferRecipient(Base):
    """
    A borrower's bank account registered as a transfer recipient.

    Created once per customer+bank_account combination.
    Reused across multiple loans for the same customer.
    """

    __tablename__ = "transfer_recipients"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Bank account details
    account_number: Mapped[str] = mapped_column(String(20), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(10), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_name: Mapped[str] = mapped_column(String(256), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)

    # Provider reference
    provider: Mapped[DisbursementProvider] = mapped_column(
        Enum(DisbursementProvider), nullable=False
    )
    recipient_code: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relationships
    disbursement_requests: Mapped[list[DisbursementRequest]] = relationship(
        back_populates="recipient", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("provider", "recipient_code", name="uq_recipient_provider_code"),
        Index("ix_recipients_customer", "customer_id", "tenant_id"),
        Index("ix_recipients_account", "account_number", "bank_code"),
    )


# ---------------------------------------------------------------------------
# DisbursementRequest — one per loan disbursement lifecycle
# ---------------------------------------------------------------------------


class DisbursementRequest(Base):
    """
    Tracks the full disbursement lifecycle for a single loan.

    Created when `loan.offer_accepted` event is received.
    Updated on every state transition.
    """

    __tablename__ = "disbursement_requests"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)

    # External references
    loan_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Amount
    amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)

    # State machine
    state: Mapped[DisbursementState] = mapped_column(
        Enum(DisbursementState), default=DisbursementState.PENDING, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # Provider details
    provider: Mapped[DisbursementProvider] = mapped_column(
        Enum(DisbursementProvider), default=DisbursementProvider.PAYSTACK, nullable=False
    )
    recipient_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("transfer_recipients.id"), nullable=True
    )
    transfer_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transfer_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Failure tracking
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    recipient: Mapped[TransferRecipient | None] = relationship(
        back_populates="disbursement_requests", lazy="selectin"
    )
    events: Mapped[list[DisbursementEvent]] = relationship(
        back_populates="disbursement_request",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="DisbursementEvent.created_at",
    )

    __table_args__ = (
        Index("ix_disbursement_state", "state"),
        Index("ix_disbursement_customer", "customer_id", "tenant_id"),
        Index("ix_disbursement_retry", "state", "next_retry_at"),
    )

    @property
    def is_terminal(self) -> bool:
        from app.engine.state_machine import is_terminal, DisbursementState as SM
        return is_terminal(SM(self.state.value))

    @property
    def can_retry(self) -> bool:
        from app.engine.state_machine import is_retry_eligible, DisbursementState as SM
        return is_retry_eligible(SM(self.state.value), self.attempt_count)


# ---------------------------------------------------------------------------
# DisbursementEvent — immutable audit log
# ---------------------------------------------------------------------------


class DisbursementEvent(Base):
    """
    Immutable record of every state transition in a disbursement lifecycle.

    Never updated — new row per transition.
    """

    __tablename__ = "disbursement_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    disbursement_request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("disbursement_requests.id", ondelete="CASCADE"),
        nullable=False,
    )

    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # Relationship
    disbursement_request: Mapped[DisbursementRequest] = relationship(
        back_populates="events"
    )

    __table_args__ = (
        Index("ix_disbursement_events_request", "disbursement_request_id"),
        Index("ix_disbursement_events_created", "created_at"),
    )
