"""
Disbursement Service — Paystack Transfer Provider

Implements PaymentProvider using the Paystack Transfers API.

Key Paystack endpoints used:
  POST /transferrecipient          — create recipient
  POST /transfer                   — initiate transfer
  GET  /transfer/{transfer_code}   — poll status

Paystack works in Naira (NGN), not kobo, so all kobo amounts
are divided by 100 before being sent and multiplied on receipt.

Webhook events handled:
  transfer.success   → DisbursementState.COMPLETED
  transfer.failed    → DisbursementState.FAILED
  transfer.reversed  → DisbursementState.REVERSED

Docs: https://paystack.com/docs/transfers/
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.engine.providers.base import (
    PaymentProvider,
    RecipientResult,
    TransferResult,
    TransferStatus,
    TransferStatusResult,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.paystack.co"

# Paystack webhook event → our TransferStatus
_WEBHOOK_STATUS_MAP: dict[str, TransferStatus] = {
    "transfer.success": TransferStatus.SUCCESS,
    "transfer.failed": TransferStatus.FAILED,
    "transfer.reversed": TransferStatus.REVERSED,
}


class PaystackProvider(PaymentProvider):
    """
    Paystack implementation of PaymentProvider.

    Parameters
    ----------
    secret_key:
        Paystack secret key (sk_live_... or sk_test_...).
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(self, secret_key: str, timeout: float = 30.0) -> None:
        self._secret_key = secret_key
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            trust_env=False,  # ignore system proxy settings
        )

    # ------------------------------------------------------------------
    # Create recipient
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def create_recipient(
        self,
        *,
        account_number: str,
        bank_code: str,
        account_name: str,
        currency: str = "NGN",
    ) -> RecipientResult:
        payload = {
            "type": "nuban",
            "name": account_name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        }

        response = await self._client.post("/transferrecipient", json=payload)
        response.raise_for_status()
        data = response.json()

        if not data.get("status"):
            raise ValueError(f"Paystack create_recipient failed: {data.get('message')}")

        rec = data["data"]
        return RecipientResult(
            recipient_code=rec["recipient_code"],
            account_name=rec["details"]["account_name"],
            bank_code=rec["details"]["bank_code"],
            account_number=rec["details"]["account_number"],
            provider_reference=rec["recipient_code"],
        )

    # ------------------------------------------------------------------
    # Initiate transfer
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def initiate_transfer(
        self,
        *,
        recipient_code: str,
        amount_kobo: int,
        reference: str,
        reason: str = "Loan disbursement",
        currency: str = "NGN",
    ) -> TransferResult:
        # Paystack expects amount in kobo (their "amount" is kobo for NGN)
        payload = {
            "source": "balance",
            "amount": amount_kobo,
            "recipient": recipient_code,
            "reference": reference,
            "reason": reason,
            "currency": currency,
        }

        response = await self._client.post("/transfer", json=payload)
        response.raise_for_status()
        data = response.json()

        if not data.get("status"):
            raise ValueError(f"Paystack initiate_transfer failed: {data.get('message')}")

        transfer = data["data"]
        raw_status = transfer.get("status", "pending")

        # Map Paystack status strings to our enum
        status_map = {
            "success": TransferStatus.SUCCESS,
            "failed": TransferStatus.FAILED,
            "reversed": TransferStatus.REVERSED,
            "pending": TransferStatus.PENDING,
            "otp": TransferStatus.PENDING,       # awaiting OTP approval
            "processing": TransferStatus.PENDING,
        }
        status = status_map.get(raw_status, TransferStatus.PENDING)

        return TransferResult(
            transfer_code=transfer["transfer_code"],
            transfer_reference=transfer.get("reference", reference),
            status=status,
            amount_kobo=transfer.get("amount", amount_kobo),
            provider_message=data.get("message", ""),
        )

    # ------------------------------------------------------------------
    # Poll transfer status
    # ------------------------------------------------------------------

    async def get_transfer_status(self, transfer_code: str) -> TransferStatusResult:
        response = await self._client.get(f"/transfer/{transfer_code}")
        response.raise_for_status()
        data = response.json()

        transfer = data["data"]
        raw_status = transfer.get("status", "pending")

        status_map = {
            "success": TransferStatus.SUCCESS,
            "failed": TransferStatus.FAILED,
            "reversed": TransferStatus.REVERSED,
            "pending": TransferStatus.PENDING,
            "processing": TransferStatus.PENDING,
        }
        status = status_map.get(raw_status, TransferStatus.PENDING)

        return TransferStatusResult(
            transfer_code=transfer_code,
            status=status,
            amount_kobo=transfer.get("amount", 0),
            provider_message=data.get("message", ""),
            completed_at=transfer.get("updated_at"),
        )

    # ------------------------------------------------------------------
    # Webhook verification
    # ------------------------------------------------------------------

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """
        Verify Paystack webhook HMAC-SHA512 signature.

        Paystack signs the raw request body with your secret key using
        HMAC-SHA512 and sends the hex digest in the X-Paystack-Signature header.
        """
        try:
            expected = hmac.new(
                self._secret_key.encode("utf-8"),
                msg=payload,
                digestmod=hashlib.sha512,
            ).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Webhook event parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_webhook_event(body: dict) -> tuple[str, TransferStatus] | None:
        """
        Parse a Paystack webhook body and return (transfer_code, status).

        Returns None if the event is not a transfer event we care about.
        """
        event = body.get("event", "")
        status = _WEBHOOK_STATUS_MAP.get(event)
        if status is None:
            return None

        transfer_code = body.get("data", {}).get("transfer_code")
        if not transfer_code:
            return None

        return transfer_code, status

    async def aclose(self) -> None:
        await self._client.aclose()
