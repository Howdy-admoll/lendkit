"""Initial schema — notification_logs, notification_preferences.

Revision ID: 0001
Revises:
Create Date: 2025-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE channel_type_enum AS ENUM ('sms', 'email', 'push');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$
    """)

    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("loan_id", sa.String(64), nullable=False),
        sa.Column("borrower_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "channel_type",
            sa.Enum("sms", "email", "push", name="channel_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("recipient", sa.String(200), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("body_preview", sa.String(200), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("provider_message_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("provider_error", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_log_key_channel", "notification_logs", ["idempotency_key", "channel_type"]
    )
    op.create_index("ix_log_loan_id", "notification_logs", ["loan_id"])
    op.create_index("ix_log_created_at", "notification_logs", ["created_at"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("borrower_id", sa.String(64), unique=True, nullable=False),
        sa.Column("sms_opted_out", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_opted_out", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_pref_borrower_id", "notification_preferences", ["borrower_id"])


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_table("notification_logs")
    op.execute("DROP TYPE IF EXISTS channel_type_enum")
