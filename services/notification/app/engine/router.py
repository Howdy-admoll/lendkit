"""
Notification Service — Channel Router

Decides which channels to use for each event type.

Rules:
  - Money events (disbursed, missed payment, default) → SMS + email
  - Soft reminders (due_soon, received) → SMS + email
  - Approval notice → SMS + email
  - All events respect per-recipient opt-out preferences

The router returns a list of (ChannelType, recipient_value) tuples. The
caller (NotificationService) fetches the actual channel instances and
delivers in parallel.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.channels.base import ChannelType


@dataclass(frozen=True)
class DeliveryTarget:
    """One channel + one recipient address."""
    channel_type: ChannelType
    recipient: str   # E.164 phone for SMS, email address for email


# ---------------------------------------------------------------------------
# Routing table — which channel types are used per event
# ---------------------------------------------------------------------------

_EVENT_CHANNELS: dict[str, list[ChannelType]] = {
    "loan.offer_accepted": [ChannelType.SMS, ChannelType.EMAIL],
    "loan.disbursed":      [ChannelType.SMS, ChannelType.EMAIL],
    "repayment.due_soon":  [ChannelType.SMS, ChannelType.EMAIL],
    "repayment.received":  [ChannelType.SMS, ChannelType.EMAIL],
    "repayment.missed":    [ChannelType.SMS, ChannelType.EMAIL],
    "loan.defaulted":      [ChannelType.SMS, ChannelType.EMAIL],
}


def route(
    event_type: str,
    *,
    phone: str | None,
    email: str | None,
    sms_opted_out: bool = False,
    email_opted_out: bool = False,
) -> list[DeliveryTarget]:
    """
    Return delivery targets for a given event and recipient.

    Parameters
    ----------
    event_type:
        Redis Stream event name (e.g. "loan.disbursed").
    phone:
        E.164 phone number, or None if unavailable.
    email:
        Email address, or None if unavailable.
    sms_opted_out:
        If True, skip SMS even if this event normally uses it.
    email_opted_out:
        If True, skip email even if this event normally uses it.

    Returns
    -------
    list[DeliveryTarget]:
        May be empty if all channels are opted-out or recipient data is missing.
    """
    channels = _EVENT_CHANNELS.get(event_type, [])
    targets: list[DeliveryTarget] = []

    for ch in channels:
        if ch == ChannelType.SMS and phone and not sms_opted_out:
            targets.append(DeliveryTarget(channel_type=ChannelType.SMS, recipient=phone))
        elif ch == ChannelType.EMAIL and email and not email_opted_out:
            targets.append(DeliveryTarget(channel_type=ChannelType.EMAIL, recipient=email))

    return targets


def supported_events() -> frozenset[str]:
    """Return the set of event types the router knows about."""
    return frozenset(_EVENT_CHANNELS.keys())
