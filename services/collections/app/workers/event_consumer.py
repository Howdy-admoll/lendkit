"""
Collections Service — Redis Streams Event Consumer

Consumes:
  loan.events  →  loan.defaulted  →  open_case()

When a loan crosses into DEFAULT classification in the repayment service,
it publishes a loan.defaulted event. This consumer picks it up and opens
a collection case.
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.collection_service import CollectionService

logger = logging.getLogger(__name__)

_STREAMS = ["loan.events"]


async def _process_message(
    stream: str,
    message_id: str,
    fields: dict,
    settings,
    redis_client: aioredis.Redis,
) -> None:
    event_type = fields.get("event_type", "")

    if event_type != "loan.defaulted":
        # ACK and skip — we only care about defaults
        await redis_client.xack(stream, settings.consumer_group, message_id)
        return

    try:
        data = json.loads(fields.get("data", "{}"))
    except json.JSONDecodeError:
        logger.error("Invalid JSON in message %s — skipping", message_id)
        await redis_client.xack(stream, settings.consumer_group, message_id)
        return

    loan_id = data.get("loan_id", "")
    borrower_id = data.get("borrower_id", "")
    days_past_due = int(data.get("days_past_due", 0))
    outstanding_balance_kobo = int(data.get("outstanding_balance_kobo", 0))

    if not loan_id:
        logger.warning("loan.defaulted event missing loan_id — skipping %s", message_id)
        await redis_client.xack(stream, settings.consumer_group, message_id)
        return

    async with AsyncSessionLocal() as db:
        svc = CollectionService(db=db)
        case = await svc.open_case(
            loan_id=loan_id,
            borrower_id=borrower_id,
            days_past_due=days_past_due,
            outstanding_balance_kobo=outstanding_balance_kobo,
        )

    logger.info(
        "Processed loan.defaulted for loan %s → case %s (DPD=%d)",
        loan_id, case.id, days_past_due,
    )
    await redis_client.xack(stream, settings.consumer_group, message_id)


async def run_consumer() -> None:
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_stream_url, decode_responses=True)

    for stream in _STREAMS:
        try:
            await redis_client.xgroup_create(stream, settings.consumer_group, id="0", mkstream=True)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    logger.info("Collections event consumer started, watching: %s", _STREAMS)

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
                    await _process_message(stream, message_id, fields, settings, redis_client)

        except asyncio.CancelledError:
            logger.info("Consumer cancelled — shutting down")
            break
        except Exception as exc:
            logger.exception("Unexpected consumer error: %s", exc)
            await asyncio.sleep(5)
