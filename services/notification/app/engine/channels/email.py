"""
Notification Service — SendGrid Email Channel

SendGrid v3 Mail Send API.
Docs: https://docs.sendgrid.com/api-reference/mail-send/mail-send

Endpoint: POST https://api.sendgrid.com/v3/mail/send
Auth:     Authorization: Bearer <api_key>

We send both plain-text and HTML in one API call using the
`content` array so clients can render either.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.engine.channels.base import ChannelResult, ChannelType, NotificationChannel

logger = logging.getLogger(__name__)

_SENDGRID_BASE = "https://api.sendgrid.com"


class SendGridEmailChannel(NotificationChannel):
    """
    Email delivery via SendGrid.

    Parameters
    ----------
    api_key:
        SendGrid API key (starts with SG.).
    from_email:
        Verified sender email address.
    from_name:
        Display name shown in the From field.
    timeout:
        HTTP timeout in seconds.
    """

    channel_type = ChannelType.EMAIL

    def __init__(
        self,
        api_key: str,
        from_email: str,
        from_name: str = "LendKit",
        timeout: float = 15.0,
    ) -> None:
        self._from_email = from_email
        self._from_name = from_name
        self._client = httpx.AsyncClient(
            base_url=_SENDGRID_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            trust_env=False,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        html_body: str = "",
    ) -> ChannelResult:
        content = [{"type": "text/plain", "value": body}]
        if html_body:
            content.append({"type": "text/html", "value": html_body})

        payload = {
            "personalizations": [{"to": [{"email": recipient}]}],
            "from": {"email": self._from_email, "name": self._from_name},
            "subject": subject,
            "content": content,
        }

        try:
            response = await self._client.post("/v3/mail/send", json=payload)

            # SendGrid returns 202 Accepted on success (no body)
            if response.status_code == 202:
                message_id = response.headers.get("X-Message-Id", "")
                return ChannelResult(success=True, provider_message_id=message_id)

            # 4xx/5xx
            response.raise_for_status()

            # Unexpected 2xx
            return ChannelResult(success=True)

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text[:200]
            logger.error(
                "SendGrid HTTP %s for %s: %s",
                exc.response.status_code,
                recipient,
                error_body,
            )
            return ChannelResult(success=False, provider_error=error_body)

    async def aclose(self) -> None:
        await self._client.aclose()
