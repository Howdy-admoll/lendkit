"""
Notification Service — Orchestration Layer

NotificationService ties together:
  1. Template rendering
  2. Channel routing (respecting opt-outs)
  3. Idempotency check (skip if already sent on this channel)
  4. Parallel delivery across channels
  5. Logging the result

The service is intentionally stateless — it takes a DB session and channel
instances as dependencies, making it trivial to test without mocking globals.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationLog, NotificationPreference
from app.engine.channels.base import ChannelType, NotificationChannel
from app.engine.router import DeliveryTarget, route
from app.engine.templates import render

logger = logging.getLogger(__name__)


@dataclass
class NotificationRequest:
    """All the data needed to dispatch a notification."""

    event_type: str
    loan_id: str
    borrower_id: str
    phone: str | None
    email: str | None
    idempotency_key: str          # caller-supplied, unique per event occurrence
    template_context: dict[str, Any]


@dataclass
class NotificationResult:
    sent: int         # number of channels successfully delivered
    skipped: int      # channels skipped due to idempotency
    failed: int       # channels attempted but failed
    opted_out: int    # channels suppressed by preferences


class NotificationService:
    def __init__(
        self,
        db: AsyncSession,
        channels: dict[ChannelType, NotificationChannel],
    ) -> None:
        self._db = db
        self._channels = channels

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(self, req: NotificationRequest) -> NotificationResult:
        """
        Render, route, deduplicate, and deliver a notification.
        """
        # 1. Load opt-out preferences
        pref = await self._get_preferences(req.borrower_id)
        sms_out = pref.sms_opted_out if pref else False
        email_out = pref.email_opted_out if pref else False

        # 2. Determine targets
        targets = route(
            req.event_type,
            phone=req.phone,
            email=req.email,
            sms_opted_out=sms_out,
            email_opted_out=email_out,
        )

        opted_out_count = 0
        if not targets:
            # All channels suppressed
            opted_out_count = 2 if (req.phone and req.email) else 1
            return NotificationResult(
                sent=0, skipped=0, failed=0, opted_out=opted_out_count
            )

        # 3. Render templates once
        try:
            message = render(req.event_type, req.template_context)
        except KeyError as exc:
            logger.error(
                "Template render failed for %s: %s", req.event_type, exc
            )
            return NotificationResult(sent=0, skipped=0, failed=len(targets), opted_out=0)

        # 4. Dispatch each channel concurrently
        tasks = [
            self._deliver_one(req, target, message)
            for target in targets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        sent = skipped = failed = 0
        for r in results:
            if isinstance(r, Exception):
                failed += 1
            elif r == "sent":
                sent += 1
            elif r == "skipped":
                skipped += 1
            else:
                failed += 1

        return NotificationResult(
            sent=sent, skipped=skipped, failed=failed, opted_out=opted_out_count
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _deliver_one(
        self,
        req: NotificationRequest,
        target: DeliveryTarget,
        message: Any,
    ) -> str:
        """Deliver to one channel. Returns 'sent', 'skipped', or 'failed'."""
        idem_key = f"{req.idempotency_key}:{target.channel_type.value}"

        # Idempotency check
        existing = await self._db.execute(
            select(NotificationLog).where(
                NotificationLog.idempotency_key == idem_key,
                NotificationLog.channel_type == target.channel_type,
            )
        )
        if existing.scalar_one_or_none():
            logger.debug("Skipping duplicate %s via %s", req.event_type, target.channel_type)
            return "skipped"

        channel = self._channels.get(target.channel_type)
        if channel is None:
            logger.warning("No channel configured for %s", target.channel_type)
            return "failed"

        # Send
        result = await channel.send(
            recipient=target.recipient,
            subject=message.subject,
            body=message.sms_body if target.channel_type == ChannelType.SMS else message.email_body,
            html_body=message.email_html if target.channel_type == ChannelType.EMAIL else "",
        )

        # Persist log
        log = NotificationLog(
            loan_id=req.loan_id,
            borrower_id=req.borrower_id,
            event_type=req.event_type,
            channel_type=target.channel_type,
            idempotency_key=idem_key,
            recipient=target.recipient,
            subject=message.subject if target.channel_type == ChannelType.EMAIL else "",
            body_preview=(
                (message.sms_body if target.channel_type == ChannelType.SMS else message.email_body)[:200]
            ),
            success=result.success,
            provider_message_id=result.provider_message_id,
            provider_error=result.provider_error,
        )
        self._db.add(log)
        await self._db.commit()

        if result.success:
            logger.info(
                "Sent %s via %s to %s (msg_id=%s)",
                req.event_type,
                target.channel_type.value,
                target.recipient,
                result.provider_message_id,
            )
            return "sent"
        else:
            logger.warning(
                "Failed %s via %s to %s: %s",
                req.event_type,
                target.channel_type.value,
                target.recipient,
                result.provider_error,
            )
            return "failed"

    async def _get_preferences(self, borrower_id: str) -> NotificationPreference | None:
        result = await self._db.execute(
            select(NotificationPreference).where(
                NotificationPreference.borrower_id == borrower_id
            )
        )
        return result.scalar_one_or_none()
