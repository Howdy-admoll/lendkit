"""
LendKit — Disbursement Service

Port:      8005
Database:  PostgreSQL (async via asyncpg)
Events:    Redis Streams (loan.events consumer · disbursement.events producer)

Responsibilities:
  - Receive loan.offer_accepted events from Redis Streams
  - Register borrower bank accounts as Paystack transfer recipients
  - Initiate bank transfers via Paystack Transfers API
  - Track disbursement state: PENDING → RECIPIENT_READY → TRANSFER_INITIATED
      → COMPLETED | FAILED | REVERSED
  - Verify Paystack webhook HMAC signatures (transfer.success/failed/reversed)
  - Retry failed transfers with exponential backoff (up to 3 attempts)
  - Emit loan.disbursed event on success (consumed by repayment service)

Transfer flow:
  loan.offer_accepted (Redis) → create_recipient → initiate_transfer
  → Paystack webhook → handle_webhook → loan.disbursed (Redis)
"""

from __future__ import annotations

import asyncio

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.disbursements import router as disbursements_router
from app.core.config import settings
from app.db.session import engine
from app.db.models import Base

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "disbursement_service_starting",
        env=settings.app_env,
        db=settings.db_url.split("@")[-1],
    )

    if settings.app_env == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("disbursement_tables_ready")

    # Start Redis Stream consumer in background (production only)
    consumer_task = None
    if settings.app_env != "test" and settings.redis_stream_url:
        try:
            from app.workers.event_consumer import start_consumer
            consumer_task = asyncio.create_task(start_consumer())
            logger.info("disbursement_event_consumer_started")
        except Exception as exc:
            logger.warning("Could not start event consumer", error=str(exc))

    yield

    if consumer_task:
        consumer_task.cancel()
    await engine.dispose()
    logger.info("disbursement_service_stopped")


app = FastAPI(
    title="LendKit Disbursement Service",
    description=__doc__,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(disbursements_router)


@app.get("/health", tags=["System"], include_in_schema=False)
async def health():
    return {
        "status": "healthy",
        "service": "disbursement",
        "version": "0.1.0",
        "env": settings.app_env,
    }


@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    return {"service": "lendkit-disbursement", "docs": "/docs"}
