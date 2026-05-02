"""
KYC Service — Request/Response Schemas (Pydantic v2)
"""
import uuid
from datetime import datetime
from typing import Any  # noqa: UP035

from pydantic import BaseModel, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class LendKitBaseModel(BaseModel):
    model_config = {"from_attributes": True, "populate_by_name": True}


# ---------------------------------------------------------------------------
# KYC Initiation
# ---------------------------------------------------------------------------

class KYCInitiateRequest(LendKitBaseModel):
    """Payload to start a KYC flow for a customer."""
    customer_id: str = Field(..., min_length=1, max_length=64, description="Your internal customer UUID/ID")
    tenant_id: str   = Field(..., min_length=1, max_length=64, description="Tenant / lender identifier")
    level: str       = Field(default="basic", pattern="^(basic|standard|enhanced)$")

    # Personal info — collected up-front or later via separate endpoint
    first_name: str | None   = Field(None, max_length=100)
    last_name: str | None    = Field(None, max_length=100)
    date_of_birth: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="ISO 8601 date")
    phone_number: str | None = Field(None, max_length=20)
    email: EmailStr | None   = None

    # Address
    address_line1: str | None = Field(None, max_length=200)
    address_line2: str | None = Field(None, max_length=200)
    city: str | None          = Field(None, max_length=100)
    state: str | None         = Field(None, max_length=100)
    country: str              = Field(default="NGA", min_length=2, max_length=3)
    postal_code: str | None   = Field(None, max_length=20)

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        digits = "".join(c for c in v if c.isdigit() or c == "+")
        if not (7 <= len(digits) <= 15):
            raise ValueError("Phone number must be 7–15 digits (E.164 format preferred)")
        return v


class KYCUpdateRequest(LendKitBaseModel):
    """Update mutable fields on an existing KYC record."""
    first_name: str | None    = None
    last_name: str | None     = None
    date_of_birth: str | None = None
    phone_number: str | None  = None
    email: EmailStr | None    = None
    address_line1: str | None = None
    city: str | None          = None
    state: str | None         = None
    country: str | None       = None


# ---------------------------------------------------------------------------
# Document Upload
# ---------------------------------------------------------------------------

class DocumentUploadRequest(LendKitBaseModel):
    document_type: str   = Field(..., description="nin | bvn | passport | drivers_license | voters_card | utility_bill")
    document_number: str | None = Field(None, max_length=64)
    # front_image and back_image arrive as multipart files — handled by route


class DocumentVerificationResult(LendKitBaseModel):
    document_id: uuid.UUID
    status: str
    document_type: str
    confidence_score: float | None
    extracted_data: dict[str, Any] | None
    rejection_reason: str | None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class KYCStatusResponse(LendKitBaseModel):
    id: uuid.UUID
    customer_id: str
    tenant_id: str
    status: str
    level: str
    risk_score: int | None
    is_pep: bool
    is_sanctioned: bool
    rejection_reason: str | None
    documents: list[DocumentVerificationResult]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    expires_at: datetime | None


class KYCInitiateResponse(LendKitBaseModel):
    verification_id: uuid.UUID
    customer_id: str
    status: str
    level: str
    message: str = "KYC verification initiated successfully"


# ---------------------------------------------------------------------------
# Webhook / Events
# ---------------------------------------------------------------------------

class KYCWebhookPayload(LendKitBaseModel):
    event: str         # kyc.approved | kyc.rejected | kyc.expired
    verification_id: uuid.UUID
    customer_id: str
    tenant_id: str
    status: str
    risk_score: int | None
    timestamp: datetime
