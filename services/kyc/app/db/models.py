"""
KYC Service — SQLAlchemy ORM Models
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class KYCStatus(StrEnum):
    PENDING = "pending"
    INITIATED = "initiated"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class VerificationLevel(StrEnum):
    BASIC = "basic"  # BVN / phone / email only
    STANDARD = "standard"  # + government ID
    ENHANCED = "enhanced"  # + liveness check + document scan


class DocumentType(StrEnum):
    NIN = "nin"
    BVN = "bvn"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    VOTERS_CARD = "voters_card"
    UTILITY_BILL = "utility_bill"


class DocumentStatus(StrEnum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    VERIFIED = "verified"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# KYC Verification
# ---------------------------------------------------------------------------


class KYCVerification(Base):
    __tablename__ = "kyc_verifications"
    __table_args__ = (
        Index("ix_kyc_customer_id", "customer_id"),
        Index("ix_kyc_status", "status"),
        Index("ix_kyc_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[KYCStatus] = mapped_column(
        Enum(KYCStatus), default=KYCStatus.PENDING, nullable=False
    )
    level: Mapped[VerificationLevel] = mapped_column(
        Enum(VerificationLevel), default=VerificationLevel.BASIC, nullable=False
    )

    # Personal information
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    date_of_birth: Mapped[str | None] = mapped_column(String(10))  # ISO date
    phone_number: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))

    # Address
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(3), default="NGA")
    postal_code: Mapped[str | None] = mapped_column(String(20))

    # Provider info
    provider_reference: Mapped[str | None] = mapped_column(String(128), unique=True)
    provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Risk flags
    is_pep: Mapped[bool] = mapped_column(Boolean, default=False)  # politically exposed person
    is_sanctioned: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_score: Mapped[int | None] = mapped_column(Integer)  # 0–100
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    documents: Mapped[list["KYCDocument"]] = relationship(
        "KYCDocument", back_populates="verification", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<KYCVerification id={self.id} customer={self.customer_id} status={self.status}>"


# ---------------------------------------------------------------------------
# KYC Documents
# ---------------------------------------------------------------------------


class KYCDocument(Base):
    __tablename__ = "kyc_documents"
    __table_args__ = (
        Index("ix_doc_verification_id", "verification_id"),
        Index("ix_doc_type_status", "document_type", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    verification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kyc_verifications.id", ondelete="CASCADE")
    )

    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.SUBMITTED, nullable=False
    )

    # Storage references (S3 keys / GCS paths — never store raw files in DB)
    front_image_key: Mapped[str | None] = mapped_column(String(512))
    back_image_key: Mapped[str | None] = mapped_column(String(512))

    # Extraction results
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4))

    rejection_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    verification: Mapped["KYCVerification"] = relationship(
        "KYCVerification", back_populates="documents"
    )


# ---------------------------------------------------------------------------
# BIN Cache
# ---------------------------------------------------------------------------


class BINRecord(Base):
    """
    Local cache of BIN (Bank Identification Number) lookups.
    Reduces external API calls for repeat lookups.
    """

    __tablename__ = "bin_records"
    __table_args__ = (UniqueConstraint("bin", name="uq_bin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bin: Mapped[str] = mapped_column(String(8), nullable=False)
    card_brand: Mapped[str | None] = mapped_column(String(32))  # VISA, MASTERCARD, etc.
    card_type: Mapped[str | None] = mapped_column(String(32))  # DEBIT, CREDIT, PREPAID
    card_category: Mapped[str | None] = mapped_column(String(64))
    bank_name: Mapped[str | None] = mapped_column(String(200))
    bank_url: Mapped[str | None] = mapped_column(String(512))
    bank_phone: Mapped[str | None] = mapped_column(String(20))
    country_name: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(3))
    currency: Mapped[str | None] = mapped_column(String(3))
    is_prepaid: Mapped[bool | None] = mapped_column(Boolean)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
