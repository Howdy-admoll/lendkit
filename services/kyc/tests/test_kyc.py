"""
KYC Service — Identity Verification Tests
"""
import uuid

import pytest

from app.db.models import KYCStatus, KYCVerification, VerificationLevel
from app.services.identity import MockIdentityProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_verification(customer_id: str = "cust_001", level: str = "basic") -> KYCVerification:
    v = KYCVerification()
    v.id          = uuid.uuid4()
    v.customer_id = customer_id
    v.tenant_id   = "tenant_test"
    v.status      = KYCStatus.INITIATED
    v.level       = VerificationLevel(level)
    v.first_name  = "John"
    v.last_name   = "Doe"
    v.date_of_birth = "1990-01-15"
    v.phone_number  = "+2348012345678"
    v.country       = "NGA"
    return v


# ---------------------------------------------------------------------------
# Mock Provider Tests
# ---------------------------------------------------------------------------

class TestMockIdentityProvider:
    @pytest.fixture
    def provider(self):
        return MockIdentityProvider()

    async def test_approved_for_standard_customer(self, provider):
        verification = make_verification(customer_id="cust_abc123")
        result = await provider.initiate(verification)

        assert result.status == KYCStatus.APPROVED
        assert result.risk_score == 10
        assert result.is_pep is False
        assert result.provider_reference.startswith("mock_")

    async def test_rejected_when_id_ends_in_zero(self, provider):
        verification = make_verification(customer_id="cust_abc0")
        result = await provider.initiate(verification)

        assert result.status == KYCStatus.REJECTED
        assert result.risk_score == 20
        assert "rejection" in result.rejection_reason.lower()

    async def test_pep_flag_when_id_ends_in_nine(self, provider):
        verification = make_verification(customer_id="cust_abc9")
        result = await provider.initiate(verification)

        assert result.status == KYCStatus.APPROVED
        assert result.is_pep is True
        assert result.risk_score == 30  # higher risk for PEPs

    async def test_get_status_always_approved(self, provider):
        result = await provider.get_status("mock_ref_12345")
        assert result.status == KYCStatus.APPROVED

    async def test_webhook_returns_approved(self, provider):
        payload = {"reference": "mock_ref_99", "event": "kyc.approved"}
        result = await provider.handle_webhook(payload)
        assert result.status == KYCStatus.APPROVED
        assert result.provider_reference == "mock_ref_99"


# ---------------------------------------------------------------------------
# KYC Schema Tests
# ---------------------------------------------------------------------------

class TestKYCSchemas:
    def test_kyc_initiate_request_valid(self):
        from app.schemas.kyc import KYCInitiateRequest
        req = KYCInitiateRequest(
            customer_id="cust_123",
            tenant_id="tenant_abc",
            level="standard",
            first_name="Ada",
            last_name="Lovelace",
            date_of_birth="1815-12-10",
            phone_number="+2348012345678",
            email="ada@example.com",
            country="NGA",
        )
        assert req.customer_id == "cust_123"
        assert req.level == "standard"

    def test_kyc_initiate_request_invalid_level(self):
        from pydantic import ValidationError

        from app.schemas.kyc import KYCInitiateRequest

        with pytest.raises(ValidationError):
            KYCInitiateRequest(
                customer_id="cust_123",
                tenant_id="tenant_abc",
                level="super_enhanced",  # invalid
            )

    def test_kyc_initiate_request_invalid_phone(self):
        from pydantic import ValidationError

        from app.schemas.kyc import KYCInitiateRequest

        with pytest.raises(ValidationError):
            KYCInitiateRequest(
                customer_id="cust_123",
                tenant_id="tenant_abc",
                phone_number="12",  # too short
            )

    def test_kyc_initiate_request_invalid_dob_format(self):
        from pydantic import ValidationError

        from app.schemas.kyc import KYCInitiateRequest

        with pytest.raises(ValidationError):
            KYCInitiateRequest(
                customer_id="cust_123",
                tenant_id="tenant_abc",
                date_of_birth="15-01-1990",  # wrong format, must be YYYY-MM-DD
            )
