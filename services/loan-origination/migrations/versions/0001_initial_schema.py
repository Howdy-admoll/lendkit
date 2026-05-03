"""Initial schema — loan_applications and loan_offers

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "loan_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("requested_amount_kobo", sa.BigInteger, nullable=False),
        sa.Column("tenure_months", sa.Integer, nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False, server_default="other"),
        sa.Column("kyc_verification_id", sa.String(64), nullable=True),
        sa.Column("credit_score", sa.Integer, nullable=True),
        sa.Column("credit_tier", sa.String(16), nullable=True),
        sa.Column("monthly_income_kobo", sa.BigInteger, nullable=True),
        sa.Column("employment_type", sa.String(32), nullable=True),
        sa.Column("state", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("decline_reasons", sa.dialects.postgresql.JSON(), nullable=True),
        sa.Column("underwriting_notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_loan_applications_customer_id", "loan_applications", ["customer_id"])
    op.create_index("ix_loan_applications_tenant_id", "loan_applications", ["tenant_id"])
    op.create_index("ix_loan_applications_state", "loan_applications", ["state"])
    op.create_index(
        "ix_loan_applications_customer_tenant_created",
        "loan_applications",
        ["customer_id", "tenant_id", "created_at"],
    )

    op.create_table(
        "loan_offers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "loan_id",
            sa.String(36),
            sa.ForeignKey("loan_applications.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("approved_amount_kobo", sa.BigInteger, nullable=False),
        sa.Column("tenure_months", sa.Integer, nullable=False),
        sa.Column("annual_percentage_rate", sa.Float, nullable=False),
        sa.Column("monthly_repayment_kobo", sa.BigInteger, nullable=False),
        sa.Column("total_repayable_kobo", sa.BigInteger, nullable=False),
        sa.Column(
            "disbursement_method",
            sa.String(32),
            nullable=False,
            server_default="bank_transfer",
        ),
        sa.Column("is_accepted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_loan_offers_loan_id", "loan_offers", ["loan_id"])


def downgrade() -> None:
    op.drop_table("loan_offers")
    op.drop_table("loan_applications")
