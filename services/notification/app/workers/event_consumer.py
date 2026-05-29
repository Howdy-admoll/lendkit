"""
Notification Service — Redis Streams Event Consumer

Consumes events from multiple streams and dispatches notifications.

Streams consumed:
  loan.events       — loan.offer_accepted, loan.disbursed, loan.defaulted
  repayment.events  — repayment.received, repayment.missed

For each event we build a NotificationRequest and call NotificationService.dispatch().
Missing fields in the event payload are handled gracefully — we log and ACK
to avoid poison-pill messages blocking the consumer.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.engine.channels.base import ChannelType
from app.engine.channels.email import SendGridEmailChannel
from app.engine.channels.sms import TermiiSMSChannel
from app.services.notification_service import NotificationRequest, NotificationService

logger = logging.getLogger(__name__)

_STREAMS = ["loan.events", "repayment.events"]


def _build_channels(settings) -> dict[ChannelType, Any]:
    return {
        ChannelType.SMS: TermiiSMSChannel(
            api_key=settings.termii_api_key,
            sender_id=settings.termii_sender_id,
            channel=settings.termii_channel,
        ),
        ChannelType.EMAIL: SendGridEmailChannel(
            api_key=settings.sendgrid_api_key,
            from_email=settings.sendgrid_from_email,
            from_name=settings.sendgrid_from_name,
        ),
    }


def _build_context(event_type: str, data: dict, settings) -> dict:
    """
    Map raw stream data to template context variables.
    Provides safe defaults for missing fields.
    """
    base = {
        "first_name": data.get("first_name", "Customer"),
        "support_email": settings.support_email,
        "support_phone": settings.support_phone,
    }

    if event_type == "loan.offer_accepted":
        base.update({
            "amount": data.get("amount_formatted", "₦0.00"),
            "tenure_months": data.get("tenure_months", "—"),
            "monthly_installment": data.get("monthly_installment_formatted", "₦0.00"),
            "bank_name": data.get("bank_name", "your bank"),
            "account_number": data.get("account_number", "****"),
            "account_last4": data.get("account_number", "****")[-4:],
        })
    elif event_type == "loan.disbursed":
        base.update({
            "amount": data.get("amount_formatted", "₦0.00"),
            "bank_name": data.get("bank_name", "your bank"),
            "account_last4": data.get("account_number", "****")[-4:],
            "transfer_reference": data.get("transfer_reference", "—"),
            "transfer_date": data.get("transfer_date", "today"),
            "monthly_installment": data.get("monthly_installment_formatted", "₦0.00"),
            "first_due_date": data.get("first_due_date", "—"),
        })
    elif event_type == "repayment.due_soon":
        base.update({
            "amount": data.get("amount_formatted", "₦0.00"),
            "due_date": data.get("due_date", "—"),
            "days_left": data.get("days_left", "—"),
            "installment_number": data.get("installment_number", "—"),
            "total_installments": data.get("total_installments", "—"),
        })
    elif event_type == "repayment.received":
        base.update({
            "amount": data.get("amount_formatted", "₦0.00"),
            "payment_date": data.get("payment_date", "today"),
            "principal_paid": data.get("principal_paid_formatted", "₦0.00"),
            "interest_paid": data.get("interest_paid_formatted", "₦0.00"),
            "outstanding_balance": data.get("outstanding_balance_formatted", "₦0.00"),
        })
    elif event_type == "repayment.missed":
        base.update({
            "amount": data.get("amount_formatted", "₦0.00"),
            "due_date": data.get("due_date", "—"),
            "days_overdue": data.get("days_overdue", "—"),
            "penalty_amount": data.get("penalty_amount_formatted", "₦0.00"),
        })
    elif event_type == "loan.defaulted":
        base.update({
            "days_overdue": data.get("days_overdue", "—"),
        })

    return base


async def _process_message(
    stream: str,
    message_id: str,
    fields: dict,
    settings,
    channels: dict,
    redis_client: aioredis.Redis,
) -> None:
    event_type = fields.get("event_type", "")
    if not event_type:
        logger.warning("Message %s on %s has no event_type — ACKing and skipping", message_id, stream)
        await redis_client.xack(stream, settings.consumer_group, message_id)
        return

    try:
        data = json.loads(fields.get("data", "{}"))
    except json.JSONDecodeError:
        logger.error("Invalid JSON in message %s — skipping", message_id)
        await redis_client.xack(stream, settings.consumer_group, message_id)
        return

    loan_id = data.get("loan_id", "unknown")
    borrower_id = data.get("borrower_id", "unknown")
    phone = data.get("phone") or None
    email = data.get("email") or None

    context = _build_context(event_type, data, settings)

    req = NotificationRequest(
        event_type=event_type,
        loan_id=loan_id,
        borrower_id=borrower_id,
        phone=phone,
        email=email,
        idempotency_key=f"{event_type}:{loan_id}:{message_id}",
        template_context=context,
    )

    async with AsyncSessionLocal() as db:
        svc = NotificationService(db=db, channels=channels)
        result = await svc.dispatch(req)

    logger.info(
        "Dispatched %s for loan %s: sent=%d skipped=%d failed=%d opted_out=%d",
        event_type, loan_id,
        result.sent, result.skipped, result.failed, result.opted_out,
    )

    await redis_client.xack(stream, settings.consumer_group, message_id)


async def run_consumer() -> None:
    settings = get_settings()
    channels = _build_channels(settings)

    redis_client = aioredis.from_url(
        settings.redis_stream_url,
        decode_responses=True,
        socket_timeout=30,          # must exceed consumer_block_ms (5s)
        socket_connect_timeout=10,
    )

    # Create consumer groups (BUSYGROUP = already exists, safe to ignore)
    for stream in _STREAMS:
        try:
            await redis_client.xgroup_create(stream, settings.consumer_group, id="0", mkstream=True)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    logger.info("Notification event consumer started, watching: %s", _STREAMS)

    stream_specs = {s: ">" for s in _STREAMS}

    while True:
        try:
            results = await redis_client.xreadgroup(
                groupname=settings.consumer_group,
                consumername=settings.consumer_name,
                streams=stream_specs,
                count=settings.consumer_batch_size,
                block=settings.consumer_block_ms,
            )

            if not results:
                continue

            for stream, messages in results:
                for message_id, fields in messages:
                    await _process_message(
                        stream, message_id, fields, settings, channels, redis_client
                    )

        except asyncio.CancelledError:
            logger.info("Consumer cancelled — shutting down")
            break
        except Exception as exc:
            logger.exception("Unexpected consumer error: %s", exc)
            await asyncio.sleep(5)
