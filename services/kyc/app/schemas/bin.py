"""
KYC Service — BIN Lookup Schemas
"""
from pydantic import BaseModel, Field, field_validator


class BINLookupRequest(BaseModel):
    bin: str = Field(..., min_length=6, max_length=8, description="First 6–8 digits of a card number")

    @field_validator("bin")
    @classmethod
    def digits_only(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("BIN must contain only digits")
        return v


class BankInfo(BaseModel):
    name: str | None
    url: str | None
    phone: str | None


class BINLookupResponse(BaseModel):
    bin: str
    card_brand: str | None       # VISA | MASTERCARD | AMEX | VERVE | etc.
    card_type: str | None        # DEBIT | CREDIT | PREPAID
    card_category: str | None    # CLASSIC | GOLD | PLATINUM | etc.
    bank: BankInfo
    country_name: str | None
    country_code: str | None
    currency: str | None
    is_prepaid: bool | None
    source: str = "api"          # "api" | "cache" | "db"


class BINValidationResult(BaseModel):
    """Result of validating a card BIN against business rules."""
    bin: str
    is_valid: bool
    is_allowed: bool             # passes lender's allowed card rules
    rejection_reasons: list[str] = []
    bin_info: BINLookupResponse | None
