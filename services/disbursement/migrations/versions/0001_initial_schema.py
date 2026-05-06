"""initial schema — transfer_recipients, disbursement_requests, disbursement_events

Revision ID: 0001
Revises:
Create Date: 2025-03-01 00:00:00.000000
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
    # Enums
    disbursement_state = sa.Enum(
        "pending", "recipient_ready", "transfer_initiated",
        "completed", "failed", "reversed", "cancelled",
        name="disbursementstate",
    )
    disbursement_provider = sa.Enum(
        "paystack", "flutterwave", "mock",
        name="disbursementprovider",
    )

    # ------------------------------------------------------------------
    # transfer_recipients
    # ------------------------------------------------------------------
    op.create_table(
        "transfer_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("customer_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("account_number", sa.String(20), nullable=False),
        sa.Column("bank_code", sa.String(10), nullable=False),
        sa.Column("bank_name", sa.String(128), nullable=False),
        sa.Column("account_name", sa.String(256), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("provider", disbursement_provider, nullable=False),
        sa.Column("recipient_code", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "recipient_code", name="uq_recipient_provider_code"),
    )
    op.create_index("ix_recipients_customer", "transfer_recipients", ["customer_id", "tenant_id"])
    op.create_index("ix_recipients_account", "transfer_recipients", ["account_number", "bank_code"])

    # ------------------------------------------------------------------
    # disbursement_requests
    # ------------------------------------------------------------------
    op.create_table(
        "disbursement_requests",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("loan_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("state", disbursement_state, nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("provider", disbursement_provider, nullable=False, server_default="paystack"),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("transfer_code", sa.String(128), nullable=True),
        sa.Column("transfer_reference", sa.String(128), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["recipient_id"], ["transfer_recipients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loan_id", name="uq_disbursement_loan_id"),
    )
    op.create_index("ix_disbursement_state", "disbursement_requests", ["state"])
    op.create_index("ix_disbursement_customer", "disbursement_requests", ["customer_id", "tenant_id"])
    op.create_index("ix_disbursement_retry", "disbursement_requests", ["state", "next_retry_at"])

    # ------------------------------------------------------------------
    # disbursement_events
    # ------------------------------------------------------------------
    op.create_table(
        "disbursement_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("disbursement_request_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("from_state", sa.String(32), nullable=False),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("provider_reference", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["disbursement_request_id"], ["disbursement_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_disbursement_events_request", "disbursement_events", ["disbursement_request_id"])
    op.create_index("ix_disbursement_events_created", "disbursement_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("disbursement_events")
    op.drop_table("disbursement_requests")
    op.drop_table("transfer_recipients")
    op.execute("DROP TYPE IF EXISTS disbursementstate")
    op.execute("DROP TYPE IF EXISTS disbursementprovider")
