"""
Collections Service — Database Models

Three tables:

  collection_cases
    One per defaulted loan. Tracks current state, assigned agent, DPD,
    and promise-to-pay commitments.

  collection_activities
    Immutable audit log of every action taken on a case (outreach sent,
    agent assigned, promise recorded, escalation applied, etc.).

  collection_agents
    Agent registry with workload tracking.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as PgEnum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.engine.state_machine import CollectionState


class Base(DeclarativeBase):
    pass


class CollectionCase(Base):
    """
    Active or historical collection case for a defaulted loan.

    One row per loan — re-opened cases update the existing row.
    """

    __tablename__ = "collection_cases"
    __table_args__ = (
        UniqueConstraint("loan_id", name="uq_case_loan_id"),
        Index("ix_case_state", "state"),
        Index("ix_case_assigned_agent_id", "assigned_agent_id"),
        Index("ix_case_dpd", "days_past_due"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    loan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    borrower_id: Mapped[str] = mapped_column(String(64), nullable=False)

    state: Mapped[CollectionState] = mapped_column(
        PgEnum(CollectionState, name="collection_state_enum"), nullable=False
    )
    days_past_due: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outstanding_balance_kobo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Agent assignment
    assigned_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Promise-to-pay tracking
    promise_to_pay_date: Mapped[str | None] = mapped_column(String(10), nullable=True)   # ISO date
    promise_to_pay_amount_kobo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Amount recovered (may be partial settlement)
    recovered_amount_kobo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def is_terminal(self) -> bool:
        from app.engine.state_machine import is_terminal
        return is_terminal(self.state)


class CollectionActivity(Base):
    """
    Immutable audit log of every action on a collection case.

    Never updated — append-only.
    """

    __tablename__ = "collection_activities"
    __table_args__ = (
        Index("ix_activity_case_id", "case_id"),
        Index("ix_activity_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # e.g. "state_transition", "outreach_sent", "agent_assigned",
    #       "promise_recorded", "legal_referral", "payment_received"

    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)

    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CollectionAgent(Base):
    """
    Collections agent registry.

    Tracks each agent's current caseload so the assignment logic can
    balance work evenly across the team.
    """

    __tablename__ = "collection_agents"
    __table_args__ = (
        UniqueConstraint("agent_code", name="uq_agent_code"),
        Index("ix_agent_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_code: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active_case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
