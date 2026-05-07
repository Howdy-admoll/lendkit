"""
Notification Service — Termii SMS Provider Unit Tests

Uses respx to mock HTTP calls. No real network calls are made.
"""

import httpx
import pytest
import respx

from app.engine.channels.sms import TermiiSMSChannel

TEST_KEY = "termii-test-key-abc"
PHONE = "+2348012345678"
MSG = "Hi Amara, your loan has been approved!"


def _make_channel() -> TermiiSMSChannel:
    return TermiiSMSChannel(api_key=TEST_KEY, sender_id="LendKit", channel="generic")


class TestTermiiSend:
    async def test_successful_send(self):
        with respx.mock:
            respx.post("https://v3.api.termii.com/api/sms/send").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": "Successfully Sent",
                        "message_id": "termii-msg-001",
                        "balance": 100,
                        "user": "LendKit",
                    },
                )
            )
            channel = _make_channel()
            result = await channel.send(recipient=PHONE, body=MSG)

        assert result.success is True
        assert result.provider_message_id == "termii-msg-001"
        assert result.provider_error == ""

    async def test_api_error_response_returns_failure(self):
        """Termii returns HTTP 200 but with code='err' on rejection."""
        with respx.mock:
            respx.post("https://v3.api.termii.com/api/sms/send").mock(
                return_value=httpx.Response(
                    200,
                    json={"code": "err", "message": "Invalid phone number"},
                )
            )
            channel = _make_channel()
            result = await channel.send(recipient="bad-number", body=MSG)

        assert result.success is False
        assert "Invalid phone number" in result.provider_error

    async def test_http_5xx_returns_failure(self):
        with respx.mock:
            respx.post("https://v3.api.termii.com/api/sms/send").mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            channel = _make_channel()
            result = await channel.send(recipient=PHONE, body=MSG)

        assert result.success is False

    async def test_message_id_captured(self):
        with respx.mock:
            respx.post("https://v3.api.termii.com/api/sms/send").mock(
                return_value=httpx.Response(
                    200,
                    json={"message": "Successfully Sent", "message_id": "msg-xyz-999"},
                )
            )
            channel = _make_channel()
            result = await channel.send(recipient=PHONE, body=MSG)

        assert result.provider_message_id == "msg-xyz-999"

    async def test_subject_and_html_body_are_ignored(self):
        """SMS channel ignores subject and html_body parameters."""
        with respx.mock:
            route = respx.post("https://v3.api.termii.com/api/sms/send").mock(
                return_value=httpx.Response(
                    200,
                    json={"message": "Successfully Sent", "message_id": "x"},
                )
            )
            channel = _make_channel()
            result = await channel.send(
                recipient=PHONE,
                subject="Ignored Subject",
                body=MSG,
                html_body="<b>Ignored HTML</b>",
            )

        assert result.success is True
        # Verify the request body did not include an HTML field
        request_body = route.calls[0].request.content.decode()
        assert "html" not in request_body.lower()

    async def test_missing_message_id_in_response(self):
        """Gracefully handles response without message_id field."""
        with respx.mock:
            respx.post("https://v3.api.termii.com/api/sms/send").mock(
                return_value=httpx.Response(
                    200,
                    json={"message": "Successfully Sent"},
                )
            )
            channel = _make_channel()
            result = await channel.send(recipient=PHONE, body=MSG)

        assert result.success is True
        assert result.provider_message_id == ""


class TestTermiiChannelType:
    def test_channel_type_is_sms(self):
        from app.engine.channels.base import ChannelType
        channel = _make_channel()
        assert channel.channel_type == ChannelType.SMS
