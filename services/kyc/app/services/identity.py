"""
KYC Service — Identity Verification Service

Pluggable provider pattern:
  - mock     : deterministic responses for dev/testing
  - smile_id : Smile Identity API (Africa-focused)
  - onfido   : Onfido API (global)

Add new providers by subclassing IdentityProvider and registering in get_provider().
"""
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.db.models import KYCStatus, KYCVerification, VerificationLevel

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------

class IdentityCheckResult:
    __slots__ = (
        "provider_reference", "status", "risk_score",
        "is_pep", "is_sanctioned", "raw_response", "rejection_reason"
    )

    def __init__(
        self,
        provider_reference: str,
        status: KYCStatus,
        risk_score: int,
        is_pep: bool = False,
        is_sanctioned: bool = False,
        raw_response: dict[str, Any] | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        self.provider_reference = provider_reference
        self.status             = status
        self.risk_score         = risk_score
        self.is_pep             = is_pep
        self.is_sanctioned      = is_sanctioned
        self.raw_response       = raw_response or {}
        self.rejection_reason   = rejection_reason


# ---------------------------------------------------------------------------
# Abstract Provider
# ---------------------------------------------------------------------------

class IdentityProvider(ABC):
    """All identity verification providers implement this interface."""

    @abstractmethod
    async def initiate(self, verification: KYCVerification) -> IdentityCheckResult:
        """Start an identity check and return initial result."""

    @abstractmethod
    async def get_status(self, provider_reference: str) -> IdentityCheckResult:
        """Poll for a result by provider's reference ID."""

    @abstractmethod
    async def handle_webhook(self, payload: dict[str, Any]) -> IdentityCheckResult:
        """Process inbound webhook from provider."""


# ---------------------------------------------------------------------------
# Mock Provider (dev / CI)
# ---------------------------------------------------------------------------

class MockIdentityProvider(IdentityProvider):
    """
    Deterministic mock provider.
    - Customers whose customer_id ends in '0' are rejected (easy to test).
    - customer_id ending in '9' triggers PEP flag.
    - Everyone else is approved with score 750.
    """

    async def initiate(self, verification: KYCVerification) -> IdentityCheckResult:
        ref = f"mock_{uuid.uuid4().hex[:12]}"

        if verification.customer_id.endswith("0"):
            return IdentityCheckResult(
                provider_reference=ref,
                status=KYCStatus.REJECTED,
                risk_score=20,
                rejection_reason="Mock rejection: customer ID ends in 0",
                raw_response={"mock": True, "scenario": "rejected"},
            )

        is_pep = verification.customer_id.endswith("9")
        return IdentityCheckResult(
            provider_reference=ref,
            status=KYCStatus.APPROVED,
            risk_score=30 if is_pep else 10,
            is_pep=is_pep,
            raw_response={"mock": True, "scenario": "approved", "is_pep": is_pep},
        )

    async def get_status(self, provider_reference: str) -> IdentityCheckResult:
        return IdentityCheckResult(
            provider_reference=provider_reference,
            status=KYCStatus.APPROVED,
            risk_score=10,
            raw_response={"mock": True},
        )

    async def handle_webhook(self, payload: dict[str, Any]) -> IdentityCheckResult:
        return IdentityCheckResult(
            provider_reference=payload.get("reference", "mock"),
            status=KYCStatus.APPROVED,
            risk_score=10,
            raw_response=payload,
        )


# ---------------------------------------------------------------------------
# Smile Identity Provider
# ---------------------------------------------------------------------------

class SmileIDProvider(IdentityProvider):
    """
    Smile Identity v2 API integration.
    Docs: https://docs.smileidentity.com/
    """

    BASE_URL = "https://api.smileidentity.com/v1"

    def __init__(self) -> None:
        self.api_key  = settings.identity_api_key
        self.base_url = settings.identity_api_url or self.BASE_URL

    async def initiate(self, verification: KYCVerification) -> IdentityCheckResult:
        payload = {
            "source_sdk": "lendkit",
            "source_sdk_version": "0.1.0",
            "partner_id": self.api_key,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "callback_url": f"{settings.identity_api_url}/kyc/webhooks/smile",
            "country": verification.country,
            "id_type": "BVN",
            "id_number": "",   # populated after document upload
            "first_name": verification.first_name,
            "last_name": verification.last_name,
            "dob": verification.date_of_birth,
            "phone_number": verification.phone_number,
            "partner_params": {
                "verification_id": str(verification.id),
                "customer_id": verification.customer_id,
                "job_type": 5,  # Enhanced KYC
            },
        }

        async with httpx.AsyncClient(timeout=settings.identity_request_timeout) as client:
            resp = await client.post(
                f"{self.base_url}/id_verification",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        result_code = data.get("ResultCode", "")
        is_approved = result_code == "1012"

        return IdentityCheckResult(
            provider_reference=data.get("SmileJobID", ""),
            status=KYCStatus.APPROVED if is_approved else KYCStatus.REJECTED,
            risk_score=self._score_from_result(data),
            is_pep=data.get("IsPEP", False),
            is_sanctioned=data.get("IsSanctioned", False),
            raw_response=data,
            rejection_reason=None if is_approved else data.get("ResultText"),
        )

    async def get_status(self, provider_reference: str) -> IdentityCheckResult:
        async with httpx.AsyncClient(timeout=settings.identity_request_timeout) as client:
            resp = await client.get(
                f"{self.base_url}/job_status",
                params={"smile_job_id": provider_reference},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        is_approved = data.get("ResultCode") == "1012"
        return IdentityCheckResult(
            provider_reference=provider_reference,
            status=KYCStatus.APPROVED if is_approved else KYCStatus.IN_REVIEW,
            risk_score=self._score_from_result(data),
            raw_response=data,
        )

    async def handle_webhook(self, payload: dict[str, Any]) -> IdentityCheckResult:
        result_code = payload.get("ResultCode", "")
        is_approved = result_code == "1012"
        return IdentityCheckResult(
            provider_reference=payload.get("SmileJobID", ""),
            status=KYCStatus.APPROVED if is_approved else KYCStatus.REJECTED,
            risk_score=self._score_from_result(payload),
            is_pep=payload.get("IsPEP", False),
            is_sanctioned=payload.get("IsSanctioned", False),
            raw_response=payload,
            rejection_reason=None if is_approved else payload.get("ResultText"),
        )

    @staticmethod
    def _score_from_result(data: dict[str, Any]) -> int:
        """Derive a normalized 0–100 risk score from provider confidence."""
        confidence = data.get("ConfidenceValue", "50")
        try:
            # Smile returns confidence as a string percentage
            conf = float(str(confidence).rstrip("%"))
            # Invert: high confidence → low risk score
            return max(0, min(100, int(100 - conf)))
        except (ValueError, TypeError):
            return 50


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_identity_provider() -> IdentityProvider:
    """Return the configured identity provider singleton."""
    provider = settings.identity_provider
    if provider == "smile_id":
        return SmileIDProvider()
    if provider == "onfido":
        # TODO: implement OnfidoProvider
        raise NotImplementedError("Onfido provider not yet implemented — PRs welcome!")
    # Default: mock
    return MockIdentityProvider()
