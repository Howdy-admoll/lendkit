"""
Disbursement Service — Paystack Provider Unit Tests

Tests the PaystackProvider using respx to mock HTTP calls.
No real network calls are made.
"""

import hashlib
import hmac

import httpx
import pytest
import respx

from app.engine.providers.base import TransferStatus
from app.engine.providers.paystack import PaystackProvider

TEST_SECRET = "sk_test_abc123"


def _make_provider() -> PaystackProvider:
    return PaystackProvider(secret_key=TEST_SECRET)


# ===========================================================================
# create_recipient
# ===========================================================================


class TestCreateRecipient:
    async def test_success(self):
        with respx.mock:
            respx.post("https://api.paystack.co/transferrecipient").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": True,
                        "message": "Recipient created",
                        "data": {
                            "recipient_code": "RCP_xyz123",
                            "details": {
                                "account_name": "AMARA OKAFOR",
                                "account_number": "0123456789",
                                "bank_code": "058",
                            },
                        },
                    },
                )
            )
            provider = _make_provider()
            result = await provider.create_recipient(
                account_number="0123456789",
                bank_code="058",
                account_name="Amara Okafor",
            )

        assert result.recipient_code == "RCP_xyz123"
        assert result.account_name == "AMARA OKAFOR"
        assert result.bank_code == "058"
        assert result.account_number == "0123456789"

    async def test_paystack_error_raises(self):
        with respx.mock:
            respx.post("https://api.paystack.co/transferrecipient").mock(
                return_value=httpx.Response(
                    200,
                    json={"status": False, "message": "Invalid account number"},
                )
            )
            provider = _make_provider()
            with pytest.raises(ValueError, match="Invalid account number"):
                await provider.create_recipient(
                    account_number="0000000000",
                    bank_code="058",
                    account_name="Test",
                )


# ===========================================================================
# initiate_transfer
# ===========================================================================


class TestInitiateTransfer:
    async def test_pending_transfer(self):
        with respx.mock:
            respx.post("https://api.paystack.co/transfer").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": True,
                        "message": "Transfer has been queued",
                        "data": {
                            "transfer_code": "TRF_abc999",
                            "reference": "lk-a3f2b1c4-01-d7e9f2",
                            "amount": 5_000_000,
                            "status": "pending",
                        },
                    },
                )
            )
            provider = _make_provider()
            result = await provider.initiate_transfer(
                recipient_code="RCP_xyz123",
                amount_kobo=5_000_000,
                reference="lk-a3f2b1c4-01-d7e9f2",
            )

        assert result.transfer_code == "TRF_abc999"
        assert result.status == TransferStatus.PENDING
        assert result.amount_kobo == 5_000_000

    async def test_immediate_success(self):
        with respx.mock:
            respx.post("https://api.paystack.co/transfer").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": True,
                        "message": "Transfer successful",
                        "data": {
                            "transfer_code": "TRF_done",
                            "reference": "lk-aaaaaaaa-01-abc123",
                            "amount": 1_000_000,
                            "status": "success",
                        },
                    },
                )
            )
            provider = _make_provider()
            result = await provider.initiate_transfer(
                recipient_code="RCP_xyz",
                amount_kobo=1_000_000,
                reference="lk-aaaaaaaa-01-abc123",
            )
        assert result.status == TransferStatus.SUCCESS

    async def test_provider_error_raises(self):
        with respx.mock:
            respx.post("https://api.paystack.co/transfer").mock(
                return_value=httpx.Response(
                    200,
                    json={"status": False, "message": "Insufficient balance"},
                )
            )
            provider = _make_provider()
            with pytest.raises(ValueError, match="Insufficient balance"):
                await provider.initiate_transfer(
                    recipient_code="RCP_xyz",
                    amount_kobo=999_999_999,
                    reference="lk-aaaaaaaa-01-xyz",
                )


# ===========================================================================
# get_transfer_status
# ===========================================================================


class TestGetTransferStatus:
    async def test_success_status(self):
        with respx.mock:
            respx.get("https://api.paystack.co/transfer/TRF_abc").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": True,
                        "message": "Transfer retrieved",
                        "data": {
                            "transfer_code": "TRF_abc",
                            "amount": 2_000_000,
                            "status": "success",
                            "updated_at": "2025-03-01T10:00:00.000Z",
                        },
                    },
                )
            )
            provider = _make_provider()
            result = await provider.get_transfer_status("TRF_abc")

        assert result.status == TransferStatus.SUCCESS
        assert result.amount_kobo == 2_000_000
        assert result.completed_at is not None

    async def test_failed_status(self):
        with respx.mock:
            respx.get("https://api.paystack.co/transfer/TRF_bad").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": True,
                        "message": "Transfer retrieved",
                        "data": {
                            "transfer_code": "TRF_bad",
                            "amount": 500_000,
                            "status": "failed",
                            "updated_at": None,
                        },
                    },
                )
            )
            provider = _make_provider()
            result = await provider.get_transfer_status("TRF_bad")
        assert result.status == TransferStatus.FAILED


# ===========================================================================
# verify_webhook
# ===========================================================================


class TestVerifyWebhook:
    def test_valid_signature(self):
        provider = _make_provider()
        payload = b'{"event":"transfer.success","data":{"transfer_code":"TRF_abc"}}'
        sig = hmac.new(
            TEST_SECRET.encode(), msg=payload, digestmod=hashlib.sha512
        ).hexdigest()
        assert provider.verify_webhook(payload, sig)

    def test_invalid_signature_returns_false(self):
        provider = _make_provider()
        payload = b'{"event":"transfer.success"}'
        assert not provider.verify_webhook(payload, "bad-signature")

    def test_tampered_payload_returns_false(self):
        provider = _make_provider()
        original = b'{"event":"transfer.success","data":{"amount":100}}'
        sig = hmac.new(
            TEST_SECRET.encode(), msg=original, digestmod=hashlib.sha512
        ).hexdigest()
        tampered = b'{"event":"transfer.success","data":{"amount":999999}}'
        assert not provider.verify_webhook(tampered, sig)


# ===========================================================================
# parse_webhook_event
# ===========================================================================


class TestParseWebhookEvent:
    def test_transfer_success_parsed(self):
        body = {"event": "transfer.success", "data": {"transfer_code": "TRF_abc"}}
        result = PaystackProvider.parse_webhook_event(body)
        assert result is not None
        code, status = result
        assert code == "TRF_abc"
        assert status == TransferStatus.SUCCESS

    def test_transfer_failed_parsed(self):
        body = {"event": "transfer.failed", "data": {"transfer_code": "TRF_xyz"}}
        result = PaystackProvider.parse_webhook_event(body)
        assert result is not None
        _, status = result
        assert status == TransferStatus.FAILED

    def test_transfer_reversed_parsed(self):
        body = {"event": "transfer.reversed", "data": {"transfer_code": "TRF_rev"}}
        result = PaystackProvider.parse_webhook_event(body)
        assert result is not None
        _, status = result
        assert status == TransferStatus.REVERSED

    def test_unknown_event_returns_none(self):
        body = {"event": "charge.success", "data": {"reference": "REF_abc"}}
        assert PaystackProvider.parse_webhook_event(body) is None

    def test_missing_transfer_code_returns_none(self):
        body = {"event": "transfer.success", "data": {}}
        assert PaystackProvider.parse_webhook_event(body) is None
