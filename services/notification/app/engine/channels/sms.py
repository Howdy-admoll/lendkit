"""
Notification Service — Termii SMS Channel

Termii is the leading SMS gateway in Nigeria, used by most local fintechs.
Docs: https://developers.termii.com/messaging

Endpoint: POST https://v3.api.termii.com/api/sms/send
Auth: api_key in the JSON body (not a header)

The provider also exposes a mock/sandbox mode via a flag in config — useful
for staging environments where you want real API calls to be swallowed.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.engine.channels.base import ChannelResult, ChannelType, NotificationChannel

logger = logging.getLogger(__name__)

_TERMII_BASE = "https://v3.api.termii.com"


class TermiiSMSChannel(NotificationChannel):
    """
    SMS delivery via Termii.

    Parameters
    ----------
    api_key:
        Termii API key.
    sender_id:
        Alphanumeric sender ID registered with Termii (e.g. "LendKit").
    channel:
        Termii channel type — "generic" for international, "dnd" for DND-registered
        Nigerian lines. Defaults to "generic".
    timeout:
        HTTP timeout in seconds.
    """

    channel_type = ChannelType.SMS

    def __init__(
        self,
        api_key: str,
        sender_id: str = "LendKit",
        channel: str = "generic",
        timeout: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._sender_id = sender_id
        self._channel = channel
        self._client = httpx.AsyncClient(
            base_url=_TERMII_BASE,
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
        subject: str = "",
        body: str,
        html_body: str = "",
    ) -> ChannelResult:
        payload = {
            "to": recipient,
            "from": self._sender_id,
            "sms": body,
            "type": "plain",
            "channel": self._channel,
            "api_key": self._api_key,
        }

        try:
            response = await self._client.post("/api/sms/send", json=payload)
            response.raise_for_status()
            data = response.json()

            # Termii returns {"message": "Successfully Sent", "message_id": "...", ...}
            # or {"code": "err", "message": "..."}
            if data.get("code") == "err" or data.get("message", "").lower().startswith("error"):
                logger.warning("Termii rejected SMS to %s: %s", recipient, data.get("message"))
                return ChannelResult(
                    success=False,
                    provider_error=data.get("message", "Unknown Termii error"),
                )

            return ChannelResult(
                success=True,
                provider_message_id=str(data.get("message_id", "")),
            )

        except httpx.HTTPStatusError as exc:
            logger.error("Termii HTTP error %s for %s", exc.response.status_code, recipient)
            return ChannelResult(success=False, provider_error=str(exc))

    async def aclose(self) -> None:
        await self._client.aclose()
