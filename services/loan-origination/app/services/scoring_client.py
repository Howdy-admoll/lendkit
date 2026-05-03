"""
Loan Origination Service — Credit Scoring HTTP Client

Calls the credit-scoring service to fetch the latest score for a customer.
Uses httpx with tenacity retry logic for transient failures.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)




class ScoringClient:
    """Async HTTP client for the credit-scoring service."""

    def __init__(self) -> None:
        self._base = settings.scoring_service_url.rstrip("/")
        self._timeout = settings.service_timeout

    @retry(
        stop=stop_after_attempt(settings.service_retries),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def get_latest_score(self, customer_id: str, tenant_id: str) -> dict | None:
        """
        Fetch the most recent computed credit score for a customer.

        Returns None if no score exists yet (HTTP 404).
        Raises httpx.HTTPError on other failures (after retries).
        """
        url = f"{self._base}/api/v1/scores/{customer_id}/latest"
        params = {"tenant_id": tenant_id}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    @retry(
        stop=stop_after_attempt(settings.service_retries),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def request_score(
        self,
        customer_id: str,
        tenant_id: str,
        kyc_verification_id: str | None,
        monthly_income_kobo: int | None,
        employment_type: str | None,
        requested_loan_amount_kobo: int | None,
    ) -> dict:
        """
        Request a fresh credit score computation.

        The credit-scoring service accepts the raw signals and returns
        a full ScoringResult. Use this when no pre-existing score is found.
        """
        url = f"{self._base}/api/v1/scores"
        payload: dict = {
            "customer_id": customer_id,
            "tenant_id": tenant_id,
            "trigger": "loan_application",
        }
        if kyc_verification_id:
            payload["kyc_verification_id"] = kyc_verification_id
        if monthly_income_kobo and employment_type:
            payload["income"] = {
                "monthly_income_kobo": monthly_income_kobo,
                "employment_type": employment_type,
            }
        if requested_loan_amount_kobo:
            payload["requested_loan_amount_kobo"] = requested_loan_amount_kobo

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()


scoring_client = ScoringClient()
