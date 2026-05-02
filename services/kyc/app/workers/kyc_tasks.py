"""
KYC Service — Celery Task Definitions

Async tasks that run outside the request cycle:
  - run_identity_check    : call identity provider and update DB
  - run_document_verify   : run OCR/extraction on uploaded document
  - expire_stale_kyc      : scheduled cleanup task
  - emit_kyc_event        : publish domain events to event bus
"""
import logging
import uuid
from datetime import datetime, timedelta

from celery import Celery, Task
from celery.utils.log import get_task_logger
from sqlalchemy import select, update

from app.core.config import settings

log: logging.Logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------

celery_app = Celery(
    "kyc",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer=settings.celery_task_serializer,
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # only ack after task completes (at-least-once)
    worker_prefetch_multiplier=1, # one task at a time per worker slot
    result_expires=settings.celery_result_expires,
    beat_schedule={
        # Expire KYC records older than 90 days with no activity
        "expire-stale-kyc-daily": {
            "task": "app.workers.kyc_tasks.expire_stale_kyc",
            "schedule": 86400,  # every 24h
        },
    },
)


# ---------------------------------------------------------------------------
# Base task with DB session injection
# ---------------------------------------------------------------------------

class DBTask(Task):
    """Abstract base that provides a scoped async session per task."""
    abstract = True

    def __call__(self, *args, **kwargs):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._async_call(*args, **kwargs)
        )

    async def _async_call(self, *args, **kwargs):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Identity Verification Task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="kyc.run_identity_check",
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # 1 min
    queue="kyc",
)
def run_identity_check(self: Task, verification_id: str) -> dict:
    """
    Run identity check for a KYC verification record.
    Retries on transient provider failures.
    """
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        _async_run_identity_check(self, verification_id)
    )


async def _async_run_identity_check(task: Task, verification_id: str) -> dict:
    from app.db.models import KYCStatus, KYCVerification
    from app.db.session import get_session_factory
    from app.services.identity import get_identity_provider

    log.info("Running identity check for verification: %s", verification_id)

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(KYCVerification).where(
                KYCVerification.id == uuid.UUID(verification_id)
            )
        )
        verification = result.scalar_one_or_none()

        if not verification:
            log.error("Verification not found: %s", verification_id)
            return {"error": "not_found"}

        provider = get_identity_provider()
        try:
            check_result = await provider.initiate(verification)
        except Exception as exc:
            log.warning("Identity provider error: %s — retrying", exc)
            raise task.retry(exc=exc) from exc

        # Update the record
        verification.status              = check_result.status
        verification.provider_reference  = check_result.provider_reference
        verification.provider_response   = check_result.raw_response
        verification.risk_score          = check_result.risk_score
        verification.is_pep              = check_result.is_pep
        verification.is_sanctioned       = check_result.is_sanctioned
        verification.rejection_reason    = check_result.rejection_reason

        if check_result.status == KYCStatus.APPROVED:
            verification.approved_at = datetime.now(datetime.UTC)
            verification.expires_at  = datetime.now(datetime.UTC) + timedelta(days=365)

        await db.commit()

    # Emit domain event
    emit_kyc_event.delay(verification_id=verification_id, event=f"kyc.{check_result.status.value}")

    log.info(
        "Identity check complete: %s → %s (risk=%s)",
        verification_id, check_result.status.value, check_result.risk_score,
    )
    return {
        "verification_id": verification_id,
        "status": check_result.status.value,
        "risk_score": check_result.risk_score,
    }


# ---------------------------------------------------------------------------
# Document Verification Task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="kyc.run_document_verify",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    queue="kyc",
)
def run_document_verify(self: Task, document_id: str) -> dict:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        _async_run_document_verify(self, document_id)
    )


async def _async_run_document_verify(task: Task, document_id: str) -> dict:
    from app.db.models import KYCDocument
    from app.db.session import get_session_factory
    from app.services.document import get_document_processor

    log.info("Verifying document: %s", document_id)

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(KYCDocument).where(KYCDocument.id == uuid.UUID(document_id))
        )
        doc = result.scalar_one_or_none()

        if not doc:
            return {"error": "not_found"}

        processor = get_document_processor()
        try:
            extraction = await processor.extract(
                doc.front_image_key or "", doc.document_type
            )
        except Exception as exc:
            log.warning("Document extraction error: %s — retrying", exc)
            raise task.retry(exc=exc) from exc

        doc.status           = extraction.status
        doc.confidence_score = extraction.confidence_score
        doc.extracted_data   = extraction.extracted_data
        doc.rejection_reason = extraction.rejection_reason

        await db.commit()

    log.info("Document verification complete: %s → %s", document_id, extraction.status.value)
    return {
        "document_id": document_id,
        "status": extraction.status.value,
        "confidence_score": extraction.confidence_score,
    }


# ---------------------------------------------------------------------------
# Expiry Task (beat)
# ---------------------------------------------------------------------------

@celery_app.task(name="kyc.expire_stale_kyc", queue="kyc")
def expire_stale_kyc() -> dict:
    import asyncio
    return asyncio.get_event_loop().run_until_complete(_async_expire_stale_kyc())


async def _async_expire_stale_kyc() -> dict:
    from app.db.models import KYCStatus, KYCVerification
    from app.db.session import get_session_factory

    cutoff = datetime.now(datetime.UTC) - timedelta(days=90)
    factory = get_session_factory()

    async with factory() as db:
        result = await db.execute(
            update(KYCVerification)
            .where(
                KYCVerification.status.in_([KYCStatus.PENDING, KYCStatus.INITIATED]),
                KYCVerification.created_at < cutoff,
            )
            .values(status=KYCStatus.EXPIRED)
            .returning(KYCVerification.id)
        )
        expired_ids = result.scalars().all()
        await db.commit()

    count = len(expired_ids)
    log.info("Expired %d stale KYC records", count)
    return {"expired_count": count}


# ---------------------------------------------------------------------------
# Event Emission Task
# ---------------------------------------------------------------------------

@celery_app.task(name="kyc.emit_kyc_event", queue="kyc")
def emit_kyc_event(verification_id: str, event: str) -> None:
    """
    Publish a KYC domain event to the configured event bus.
    Other services (loan, credit) consume these events.
    """
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        _async_emit_kyc_event(verification_id, event)
    )


async def _async_emit_kyc_event(verification_id: str, event: str) -> None:
    import json

    import redis.asyncio as aioredis

    payload = json.dumps({
        "event": event,
        "verification_id": verification_id,
        "timestamp": datetime.now(datetime.UTC).isoformat(),
        "source": "kyc-service",
    })

    try:
        client = aioredis.from_url(str(settings.redis_stream_url))
        await client.xadd(
            "lendkit:kyc:events",
            {"data": payload},
            maxlen=10_000,  # trim to last 10k events
        )
        await client.aclose()
        log.debug("Published event: %s for %s", event, verification_id)
    except Exception as exc:
        log.error("Failed to publish event %s: %s", event, exc)
