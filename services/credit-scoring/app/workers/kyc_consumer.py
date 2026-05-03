"""
Credit Scoring Service — KYC Event Consumer

Listens on the Redis Stream `lendkit:kyc:events` (published by the KYC service)
and automatically triggers a credit score computation whenever a KYC verification
is approved.

Stream message format (published by KYC service):
    {
        "event_type": "kyc.approved",
        "customer_id": "cust_xxx",
        "tenant_id":   "tenant_xxx",
        "verification_id": "uuid",
        "level":       "standard",
        "risk_score":  42,
        "is_pep":      "false",
        "is_sanctioned": "false",
        "verified_documents": '["bvn", "nin"]',  # JSON-encoded list
    }

Consumer group setup:
    The consumer creates the group on first start (MKSTREAM). If the group
    already exists (subsequent restarts), the BUSYGROUP error is silently ignored.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.schemas.score import KYCSignal, ScoreRequest
from app.services.score_service import request_score

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).lower() in ("true", "1", "yes")


def _parse_docs(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        # Fallback: comma-separated
        return [d.strip() for d in value.split(",") if d.strip()]


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class KYCEventConsumer:
    """
    Long-running async consumer that reads from the KYC Redis stream and
    triggers credit score computation on approved verifications.
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._running = False

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_stream_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            engine = create_async_engine(str(settings.db_url), pool_pre_ping=True)
            self._session_factory = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )
        return self._session_factory

    async def _ensure_group(self, r: aioredis.Redis) -> None:
        """Create the consumer group, ignoring BUSYGROUP if it already exists."""
        try:
            await r.xgroup_create(
                settings.kyc_stream_key,
                settings.kyc_consumer_group,
                id="0",  # start from the beginning
                mkstream=True,
            )
            log.info("kyc_consumer.group_created", group=settings.kyc_consumer_group)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                log.debug("kyc_consumer.group_exists", group=settings.kyc_consumer_group)
            else:
                raise

    async def _handle_event(self, msg_id: str, data: dict, db: AsyncSession) -> None:
        """Process one KYC stream event."""
        event_type = data.get("event_type", "")
        customer_id = data.get("customer_id", "")
        tenant_id = data.get("tenant_id", "")

        log.info(
            "kyc_consumer.event_received",
            msg_id=msg_id,
            event_type=event_type,
            customer_id=customer_id,
        )

        # Only score on approvals
        if event_type != "kyc.approved":
            log.debug("kyc_consumer.event_skipped", event_type=event_type, msg_id=msg_id)
            return

        if not customer_id or not tenant_id:
            log.warning("kyc_consumer.missing_ids", msg_id=msg_id, data=data)
            return

        kyc_signal = KYCSignal(
            verification_id=data.get("verification_id", ""),
            status="approved",
            level=data.get("level", "basic"),
            risk_score=int(data["risk_score"]) if data.get("risk_score") else None,
            is_pep=_parse_bool(data.get("is_pep")),
            is_sanctioned=_parse_bool(data.get("is_sanctioned")),
            verified_documents=_parse_docs(data.get("verified_documents")),
        )

        req = ScoreRequest(
            customer_id=customer_id,
            tenant_id=tenant_id,
            trigger="kyc_approved",
            kyc=kyc_signal,
        )

        cs = await request_score(db, req)
        log.info(
            "kyc_consumer.score_computed",
            customer_id=customer_id,
            score=cs.score,
            tier=cs.tier,
            score_id=cs.id,
        )

    async def _process_batch(
        self,
        r: aioredis.Redis,
        factory: async_sessionmaker[AsyncSession],
    ) -> int:
        """
        Pull one batch from the stream and process each message.
        Returns number of messages processed.
        """
        messages = await r.xreadgroup(
            groupname=settings.kyc_consumer_group,
            consumername=settings.kyc_consumer_name,
            streams={settings.kyc_stream_key: ">"},
            count=settings.kyc_batch_size,
            block=settings.kyc_block_ms,
        )
        if not messages:
            return 0

        processed = 0
        for _stream, entries in messages:
            for msg_id, data in entries:
                async with factory() as db:
                    try:
                        await self._handle_event(msg_id, data, db)
                        await db.commit()
                        # ACK the message after successful processing
                        await r.xack(settings.kyc_stream_key, settings.kyc_consumer_group, msg_id)
                        processed += 1
                    except Exception as exc:
                        await db.rollback()
                        log.error(
                            "kyc_consumer.event_error",
                            msg_id=msg_id,
                            exc=str(exc),
                            exc_info=True,
                        )
                        # Don't ACK — message stays in PEL for retry / dead-letter
        return processed

    async def run(self) -> None:
        """Main loop — runs until stop() is called."""
        self._running = True
        log.info(
            "kyc_consumer.starting",
            stream=settings.kyc_stream_key,
            group=settings.kyc_consumer_group,
            consumer=settings.kyc_consumer_name,
        )

        r = await self._get_redis()
        factory = await self._get_session_factory()
        await self._ensure_group(r)

        while self._running:
            try:
                count = await self._process_batch(r, factory)
                if count > 0:
                    log.debug("kyc_consumer.batch_done", processed=count)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("kyc_consumer.loop_error", exc=str(exc), exc_info=True)
                await asyncio.sleep(5)  # back off before retrying

        log.info("kyc_consumer.stopped")

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Standalone entry point (run as a separate process / container)
# ---------------------------------------------------------------------------


async def _main() -> None:
    consumer = KYCEventConsumer()

    loop = asyncio.get_running_loop()

    def _shutdown(sig: int) -> None:
        log.info("kyc_consumer.shutdown_signal", sig=sig)
        consumer.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    await consumer.run()


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(_main())
