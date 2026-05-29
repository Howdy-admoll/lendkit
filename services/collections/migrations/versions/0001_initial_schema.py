"""Initial schema — collection_cases, collection_activities, collection_agents.

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
            CREATE TYPE collection_state_enum AS ENUM
                ('open','agent_assigned','promise_to_pay','broken_promise','legal','recovered','written_off');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$
    """)

    op.create_table(
        "collection_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("loan_id", sa.String(64), nullable=False),
        sa.Column("borrower_id", sa.String(64), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "open", "agent_assigned", "promise_to_pay", "broken_promise",
                "legal", "recovered", "written_off",
                name="collection_state_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("days_past_due", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outstanding_balance_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assigned_agent_id", sa.String(64), nullable=True),
        sa.Column("promise_to_pay_date", sa.String(10), nullable=True),
        sa.Column("promise_to_pay_amount_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovered_amount_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_case_loan_id", "collection_cases", ["loan_id"])
    op.create_index("ix_case_state", "collection_cases", ["state"])
    op.create_index("ix_case_assigned_agent_id", "collection_cases", ["assigned_agent_id"])
    op.create_index("ix_case_dpd", "collection_cases", ["days_past_due"])

    op.create_table(
        "collection_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", sa.String(64), nullable=False),
        sa.Column("from_state", sa.String(32), nullable=True),
        sa.Column("to_state", sa.String(32), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False, server_default="system"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_activity_case_id", "collection_activities", ["case_id"])
    op.create_index("ix_activity_created_at", "collection_activities", ["created_at"])

    op.create_table(
        "collection_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_code", sa.String(32), nullable=False),
        sa.Column("full_name", sa.String(128), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("active_case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_agent_code", "collection_agents", ["agent_code"])
    op.create_index("ix_agent_is_active", "collection_agents", ["is_active"])


def downgrade() -> None:
    op.drop_table("collection_agents")
    op.drop_table("collection_activities")
    op.drop_table("collection_cases")
    op.execute("DROP TYPE IF EXISTS collection_state_enum")
