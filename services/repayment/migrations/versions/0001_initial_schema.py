"""initial schema — loan_accounts, repayment_records, schedule_installments

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
    # ------------------------------------------------------------------
    # loan_accounts — live repayment state per active loan
    # ------------------------------------------------------------------
    op.create_table(
        "loan_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("loan_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("original_principal_kobo", sa.BigInteger(), nullable=False),
        sa.Column("annual_percentage_rate", sa.Float(), nullable=False),
        sa.Column("tenure_months", sa.Integer(), nullable=False),
        sa.Column("monthly_installment_kobo", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("first_due_date", sa.Date(), nullable=False),
        sa.Column("outstanding_principal_kobo", sa.BigInteger(), nullable=False),
        sa.Column("accrued_interest_kobo", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("accrued_penalties_kobo", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("installments_paid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("last_payment_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_payment_amount_kobo", sa.BigInteger(), nullable=True),
        sa.Column("days_past_due", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum(
                "current", "at_risk", "delinquent", "default", "settled", "written_off",
                name="repaymentstatus",
            ),
            nullable=False,
            server_default="current",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loan_id", name="uq_loan_accounts_loan_id"),
    )
    op.create_index("ix_loan_accounts_customer_tenant", "loan_accounts", ["customer_id", "tenant_id"])
    op.create_index("ix_loan_accounts_status", "loan_accounts", ["status"])
    op.create_index("ix_loan_accounts_next_due_date", "loan_accounts", ["next_due_date"])

    # ------------------------------------------------------------------
    # repayment_records — immutable payment ledger
    # ------------------------------------------------------------------
    op.create_table(
        "repayment_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("loan_account_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_reference", sa.String(128), nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column("penalty_portion_kobo", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("interest_portion_kobo", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("principal_portion_kobo", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("overpayment_kobo", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("balance_before_kobo", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_kobo", sa.BigInteger(), nullable=False),
        sa.Column(
            "payment_method",
            sa.Enum(
                "card", "bank_transfer", "ussd", "direct_debit", "wallet", "unknown",
                name="repaymentmethod",
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["loan_account_id"], ["loan_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_reference", name="uq_repayment_provider_ref"
        ),
    )
    op.create_index("ix_repayment_records_loan_account", "repayment_records", ["loan_account_id"])
    op.create_index("ix_repayment_records_paid_at", "repayment_records", ["paid_at"])

    # ------------------------------------------------------------------
    # schedule_installments — amortization schedule rows
    # ------------------------------------------------------------------
    op.create_table(
        "schedule_installments",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("loan_account_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("opening_balance_kobo", sa.BigInteger(), nullable=False),
        sa.Column("principal_due_kobo", sa.BigInteger(), nullable=False),
        sa.Column("interest_due_kobo", sa.BigInteger(), nullable=False),
        sa.Column("total_due_kobo", sa.BigInteger(), nullable=False),
        sa.Column("closing_balance_kobo", sa.BigInteger(), nullable=False),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_amount_kobo", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["loan_account_id"], ["loan_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "loan_account_id", "installment_number", name="uq_schedule_installment_number"
        ),
    )
    op.create_index(
        "ix_schedule_installments_due_date", "schedule_installments", ["due_date"]
    )
    op.create_index(
        "ix_schedule_installments_unpaid",
        "schedule_installments",
        ["loan_account_id", "is_paid"],
    )


def downgrade() -> None:
    op.drop_table("schedule_installments")
    op.drop_table("repayment_records")
    op.drop_table("loan_accounts")
    op.execute("DROP TYPE IF EXISTS repaymentstatus")
    op.execute("DROP TYPE IF EXISTS repaymentmethod")
