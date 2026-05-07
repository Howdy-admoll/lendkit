"""
Notification Service — Database Models

Two tables:

  notification_logs
    Immutable record of every send attempt. Idempotency is enforced via
    (idempotency_key, channel_type) — re-delivering the same event on the
    same channel is a no-op.

  notification_preferences
    Per-borrower opt-in/opt-out flags. A missing row means "opted in to all".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as PgEnum,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.engine.channels.base import ChannelType


class Base(DeclarativeBase):
    pass


class NotificationLog(Base):
    """
    Immutable log of every notification delivery attempt.

    idempotency_key is built by the caller as:
        {event_type}:{loan_id}:{attempt_specific_suffix}

    The unique constraint on (idempotency_key, channel_type) ensures we never
    send the same event on the same channel twice.
    """

    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "channel_type", name="uq_log_key_channel"),
        Index("ix_log_loan_id", "loan_id"),
        Index("ix_log_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    loan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    borrower_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_type: Mapped[ChannelType] = mapped_column(
        PgEnum(ChannelType, name="channel_type_enum"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body_preview: Mapped[str] = mapped_column(String(200), nullable=False)

    # Delivery result
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    provider_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationPreference(Base):
    """
    Per-borrower channel opt-out flags.

    A missing row = opted in to everything.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (Index("ix_pref_borrower_id", "borrower_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    borrower_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    sms_opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
