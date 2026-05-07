"""
Notification Service — Abstract Channel Base

A channel is responsible for delivering one message via one transport
(SMS, email, push, etc.). Each concrete channel receives a rendered
message and returns a ChannelResult.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ChannelType(str, Enum):
    SMS = "sms"
    EMAIL = "email"
    PUSH = "push"


@dataclass(frozen=True)
class ChannelResult:
    """
    Result returned by a channel after a send attempt.

    Attributes
    ----------
    success:
        True if the provider accepted the message.
    provider_message_id:
        ID returned by the upstream provider (Termii message_id,
        SendGrid X-Message-Id, etc.). Empty string if unavailable.
    provider_error:
        Human-readable error string on failure. Empty string on success.
    """

    success: bool
    provider_message_id: str = ""
    provider_error: str = ""


class NotificationChannel(ABC):
    """Abstract base for all delivery channels."""

    channel_type: ChannelType

    @abstractmethod
    async def send(
        self,
        *,
        recipient: str,   # phone (E.164) for SMS, email address for email
        subject: str,     # used by email; ignored by SMS
        body: str,        # plain-text body
        html_body: str = "",  # optional HTML for email
    ) -> ChannelResult:
        """Deliver the message and return a result."""
