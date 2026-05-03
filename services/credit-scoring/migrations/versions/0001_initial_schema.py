"""Initial credit scoring schema — credit_scores, score_factors

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------------------------------------------------------------------
    # credit_scores
    # ---------------------------------------------------------------------------
    op.create_table(
        "credit_scores",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        # Numeric score 300–850
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("tier", sa.String(16), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "computed", "failed", "stale", name="scorestatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("max_possible_score", sa.Integer(), nullable=True),
        # Trigger / linkage
        sa.Column("trigger", sa.String(64), nullable=True),
        sa.Column("kyc_verification_id", sa.String(64), nullable=True),
        # Outcome
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("decline_reasons", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        # Hard-stop flags
        sa.Column("is_sanctioned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_pep", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_detail", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
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
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_cs_customer_id", "credit_scores", ["customer_id"])
    op.create_index("ix_cs_tenant_id", "credit_scores", ["tenant_id"])
    op.create_index("ix_cs_status", "credit_scores", ["status"])
    op.create_index("ix_cs_created_at", "credit_scores", ["created_at"])
    # Composite index for the most common query: latest score per customer per tenant
    op.create_index(
        "ix_cs_customer_tenant_computed",
        "credit_scores",
        ["customer_id", "tenant_id", "computed_at"],
    )

    # ---------------------------------------------------------------------------
    # score_factors  (explainability breakdown)
    # ---------------------------------------------------------------------------
    op.create_table(
        "score_factors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "credit_score_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("credit_scores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("factor_key", sa.String(64), nullable=False),
        sa.Column("factor_label", sa.String(128), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points_possible", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("impact", sa.String(16), nullable=False, server_default="neutral"),
        sa.UniqueConstraint("credit_score_id", "factor_key", name="uq_score_factor"),
    )

    op.create_index("ix_sf_credit_score_id", "score_factors", ["credit_score_id"])


def downgrade() -> None:
    op.drop_index("ix_sf_credit_score_id", table_name="score_factors")
    op.drop_table("score_factors")

    op.drop_index("ix_cs_customer_tenant_computed", table_name="credit_scores")
    op.drop_index("ix_cs_created_at", table_name="credit_scores")
    op.drop_index("ix_cs_status", table_name="credit_scores")
    op.drop_index("ix_cs_tenant_id", table_name="credit_scores")
    op.drop_index("ix_cs_customer_id", table_name="credit_scores")
    op.drop_table("credit_scores")

    op.execute("DROP TYPE IF EXISTS scorestatus")
