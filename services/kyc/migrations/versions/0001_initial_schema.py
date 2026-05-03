"""Initial KYC schema — kyc_verifications, kyc_documents, bin_records

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
    # kyc_verifications
    # Enum types (kycstatus, verificationlevel) are created by SQLAlchemy
    # automatically on first use — do not call .create() separately.
    # ---------------------------------------------------------------------------
    op.create_table(
        "kyc_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "initiated", "in_review", "approved", "rejected", "expired",
                name="kycstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "level",
            sa.Enum("basic", "standard", "enhanced", name="verificationlevel"),
            nullable=False,
            server_default="basic",
        ),
        # Personal info
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("date_of_birth", sa.String(10), nullable=True),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        # Address
        sa.Column("address_line1", sa.String(200), nullable=True),
        sa.Column("address_line2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("country", sa.String(3), nullable=False, server_default="NGA"),
        sa.Column("postal_code", sa.String(20), nullable=True),
        # Provider
        sa.Column("provider_reference", sa.String(128), nullable=True, unique=True),
        sa.Column("provider_response", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        # Risk
        sa.Column("is_pep", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_sanctioned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        # Timestamps
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
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_kyc_customer_id", "kyc_verifications", ["customer_id"])
    op.create_index("ix_kyc_status", "kyc_verifications", ["status"])
    op.create_index("ix_kyc_created_at", "kyc_verifications", ["created_at"])

    # ---------------------------------------------------------------------------
    # kyc_documents
    # Enum types (documenttype, documentstatus) created on first use here.
    # ---------------------------------------------------------------------------
    op.create_table(
        "kyc_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "verification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("kyc_verifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_type",
            sa.Enum(
                "nin", "bvn", "passport", "drivers_license", "voters_card", "utility_bill",
                name="documenttype",
            ),
            nullable=False,
        ),
        sa.Column("document_number", sa.String(64), nullable=True),
        sa.Column(
            "status",
            sa.Enum("submitted", "processing", "verified", "rejected", name="documentstatus"),
            nullable=False,
            server_default="submitted",
        ),
        sa.Column("front_image_key", sa.String(512), nullable=True),
        sa.Column("back_image_key", sa.String(512), nullable=True),
        sa.Column("extracted_data", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
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
    )
    op.create_index("ix_doc_verification_id", "kyc_documents", ["verification_id"])
    op.create_index("ix_doc_type_status", "kyc_documents", ["document_type", "status"])

    # ---------------------------------------------------------------------------
    # bin_records  (no enums — all plain scalar types)
    # ---------------------------------------------------------------------------
    op.create_table(
        "bin_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bin", sa.String(8), nullable=False),
        sa.Column("card_brand", sa.String(32), nullable=True),
        sa.Column("card_type", sa.String(32), nullable=True),
        sa.Column("card_category", sa.String(64), nullable=True),
        sa.Column("bank_name", sa.String(200), nullable=True),
        sa.Column("bank_url", sa.String(512), nullable=True),
        sa.Column("bank_phone", sa.String(20), nullable=True),
        sa.Column("country_name", sa.String(100), nullable=True),
        sa.Column("country_code", sa.String(3), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("is_prepaid", sa.Boolean(), nullable=True),
        sa.Column("raw_response", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("bin", name="uq_bin"),
    )


def downgrade() -> None:
    op.drop_table("bin_records")

    op.drop_index("ix_doc_type_status", table_name="kyc_documents")
    op.drop_index("ix_doc_verification_id", table_name="kyc_documents")
    op.drop_table("kyc_documents")

    op.drop_index("ix_kyc_created_at", table_name="kyc_verifications")
    op.drop_index("ix_kyc_status", table_name="kyc_verifications")
    op.drop_index("ix_kyc_customer_id", table_name="kyc_verifications")
    op.drop_table("kyc_verifications")

    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP TYPE IF EXISTS documenttype")
    op.execute("DROP TYPE IF EXISTS verificationlevel")
    op.execute("DROP TYPE IF EXISTS kycstatus")
