"""
Notification Service — SendGrid Email Provider Unit Tests

Uses respx to mock HTTP calls. No real network calls are made.
"""

import httpx
import pytest
import respx

from app.engine.channels.email import SendGridEmailChannel

TEST_KEY = "SG.test-api-key-abc123"
RECIPIENT = "amara@example.com"
SUBJECT = "Your loan has been approved"
BODY = "Dear Amara,\n\nYour loan of ₦150,000 has been approved."
HTML = "<p>Dear <strong>Amara</strong>, your loan has been approved.</p>"


def _make_channel() -> SendGridEmailChannel:
    return SendGridEmailChannel(
        api_key=TEST_KEY,
        from_email="noreply@lendkit.io",
        from_name="LendKit",
    )


class TestSendGridSend:
    async def test_successful_send_returns_202(self):
        with respx.mock:
            respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(
                    202,
                    headers={"X-Message-Id": "sg-msg-abc123"},
                    text="",
                )
            )
            channel = _make_channel()
            result = await channel.send(
                recipient=RECIPIENT,
                subject=SUBJECT,
                body=BODY,
                html_body=HTML,
            )

        assert result.success is True
        assert result.provider_message_id == "sg-msg-abc123"
        assert result.provider_error == ""

    async def test_4xx_returns_failure(self):
        with respx.mock:
            respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(
                    400,
                    json={"errors": [{"message": "The from address does not match a verified Sender Identity"}]},
                )
            )
            channel = _make_channel()
            result = await channel.send(recipient=RECIPIENT, subject=SUBJECT, body=BODY)

        assert result.success is False
        assert result.provider_error != ""

    async def test_5xx_returns_failure(self):
        with respx.mock:
            respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(503, text="Service Unavailable")
            )
            channel = _make_channel()
            result = await channel.send(recipient=RECIPIENT, subject=SUBJECT, body=BODY)

        assert result.success is False

    async def test_html_body_included_when_provided(self):
        with respx.mock:
            route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(202, text="")
            )
            channel = _make_channel()
            await channel.send(
                recipient=RECIPIENT, subject=SUBJECT, body=BODY, html_body=HTML
            )

        import json
        request_body = json.loads(route.calls[0].request.content)
        content_types = [c["type"] for c in request_body["content"]]
        assert "text/plain" in content_types
        assert "text/html" in content_types

    async def test_html_body_omitted_when_empty(self):
        with respx.mock:
            route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(202, text="")
            )
            channel = _make_channel()
            await channel.send(recipient=RECIPIENT, subject=SUBJECT, body=BODY)

        import json
        request_body = json.loads(route.calls[0].request.content)
        content_types = [c["type"] for c in request_body["content"]]
        assert "text/plain" in content_types
        assert "text/html" not in content_types

    async def test_request_uses_bearer_auth(self):
        with respx.mock:
            route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(202, text="")
            )
            channel = _make_channel()
            await channel.send(recipient=RECIPIENT, subject=SUBJECT, body=BODY)

        auth_header = route.calls[0].request.headers.get("Authorization", "")
        assert auth_header.startswith("Bearer SG.")

    async def test_from_address_in_payload(self):
        with respx.mock:
            route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(202, text="")
            )
            channel = _make_channel()
            await channel.send(recipient=RECIPIENT, subject=SUBJECT, body=BODY)

        import json
        request_body = json.loads(route.calls[0].request.content)
        assert request_body["from"]["email"] == "noreply@lendkit.io"
        assert request_body["from"]["name"] == "LendKit"

    async def test_recipient_in_personalizations(self):
        with respx.mock:
            route = respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(202, text="")
            )
            channel = _make_channel()
            await channel.send(recipient=RECIPIENT, subject=SUBJECT, body=BODY)

        import json
        request_body = json.loads(route.calls[0].request.content)
        to_addresses = [
            e["email"]
            for p in request_body["personalizations"]
            for e in p["to"]
        ]
        assert RECIPIENT in to_addresses

    async def test_missing_x_message_id_header_is_ok(self):
        """202 without X-Message-Id header should still succeed."""
        with respx.mock:
            respx.post("https://api.sendgrid.com/v3/mail/send").mock(
                return_value=httpx.Response(202, text="")
            )
            channel = _make_channel()
            result = await channel.send(recipient=RECIPIENT, subject=SUBJECT, body=BODY)

        assert result.success is True
        assert result.provider_message_id == ""


class TestSendGridChannelType:
    def test_channel_type_is_email(self):
        from app.engine.channels.base import ChannelType
        channel = _make_channel()
        assert channel.channel_type == ChannelType.EMAIL
