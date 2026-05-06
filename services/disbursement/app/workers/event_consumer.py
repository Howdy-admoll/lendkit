"""
Disbursement Service — Redis Stream Event Consumer

Listens to the `loan.events` Redis Stream for `loan.offer_accepted` events
and automatically initiates disbursement for each accepted loan offer.

Stream message schema (published by loan-origination):
    {
        "event": "loan.offer_accepted",
        "loan_id": "<uuid>",
        "customer_id": "<uuid>",
        "tenant_id": "<uuid>",
        "amount_kobo": "15000000",
        "recipient_id": "<uuid>",      # TransferRecipient ID (optional)
        "timestamp": "2025-03-01T..."
    }

Uses XREADGROUP with a consumer group so:
  - Multiple instances of this service can run without duplicate processing
  - Messages are acknowledged after successful processing
  - Unacknowledged messages (crashes) stay in the PEL and are retried
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.engine.providers.paystack import PaystackProvider
from app.schemas.disbursement import DisbursementProvider, InitiateDisbursementRequest
from app.services.disbursement_service import initiate

logger = logging.getLogger(__name__)

_CONSUMER_NAME = "disbursement-worker-1"


async def start_consumer() -> None:
    """
    Start consuming `loan.offer_accepted` events from Redis Streams.

    Blocks indefinitely — run in a background task via asyncio.create_task().
    """
    redis = aioredis.from_url(settings.redis_stream_url, decode_responses=True)

    # Create consumer group — BUSYGROUP error means it already exists (fine)
    try:
        await redis.xgroup_create(
            settings.loan_events_stream,
            settings.consumer_group,
            id="0",
            mkstream=True,
        )
        logger.info(
            "Consumer group created",
            extra={
                "stream": settings.loan_events_stream,
                "group": settings.consumer_group,
            },
        )
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    provider = PaystackProvider(secret_key=settings.paystack_secret_key)

    logger.info(
        "Disbursement event consumer started",
        extra={"stream": settings.loan_events_stream},
    )

    while True:
        try:
            messages = await redis.xreadgroup(
                groupname=settings.consumer_group,
                consumername=_CONSUMER_NAME,
                streams={settings.loan_events_stream: ">"},
                count=10,
                block=5000,  # 5 second block
            )

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for message_id, fields in stream_messages:
                    await _process_message(message_id, fields, redis, provider)

        except Exception as exc:
            logger.exception("Consumer loop error", extra={"error": str(exc)})


async def _process_message(
    message_id: str,
    fields: dict,
    redis: aioredis.Redis,
    provider: PaystackProvider,
) -> None:
    event = fields.get("event", "")

    if event != "loan.offer_accepted":
        # Acknowledge and skip non-disbursement events
        await redis.xack(settings.loan_events_stream, settings.consumer_group, message_id)
        return

    loan_id = fields.get("loan_id", "")
    logger.info("Processing loan.offer_accepted", extra={"loan_id": loan_id})

    try:
        payload = InitiateDisbursementRequest(
            loan_id=loan_id,
            customer_id=fields.get("customer_id", ""),
            tenant_id=fields.get("tenant_id", ""),
            amount_kobo=int(fields.get("amount_kobo", 0)),
            currency=fields.get("currency", "NGN"),
            recipient_id=fields.get("recipient_id") or None,
            provider=DisbursementProvider.PAYSTACK,
        )

        async with AsyncSessionLocal() as db:
            result = await initiate(payload, db, provider)
            await db.commit()

        logger.info(
            "Disbursement initiated from event",
            extra={"loan_id": loan_id, "state": result.state.value},
        )

        # Acknowledge — message successfully processed
        await redis.xack(settings.loan_events_stream, settings.consumer_group, message_id)

    except Exception as exc:
        logger.exception(
            "Failed to process loan.offer_accepted",
            extra={"loan_id": loan_id, "message_id": message_id, "error": str(exc)},
        )
        # Do NOT acknowledge — message stays in PEL for retry
