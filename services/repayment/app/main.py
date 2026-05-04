"""
LendKit — Repayment Tracking & Default Detection Service

Port:       8004
Database:   PostgreSQL (async via asyncpg)
Events:     Redis Streams (repayment.events)

Responsibilities:
  - Record incoming repayments (webhook from Paystack / Flutterwave)
  - Maintain amortization schedule and track installments
  - Calculate outstanding balance and accrued interest / penalties
  - Detect delinquency and classify default risk
      CURRENT → AT_RISK → DELINQUENT → DEFAULT → WRITTEN_OFF
  - Run hourly sweep to update DPD across all active loans
  - Emit domain events: repayment.received, loan.delinquent,
      loan.default_detected, loan.settled

Delinquency thresholds (CBN-aligned):
  0 days       → CURRENT
  1–7 days     → AT_RISK      (grace period, no penalty clock)
  8–89 days    → DELINQUENT   (0.1%/day penalty, collections)
  90+ days     → DEFAULT      (recovery escalation)
  360+ days    → WRITTEN_OFF  (balance write-off candidate)
"""

from __future__ import annotations

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.repayments import router as repayments_router
from app.core.config import settings
from app.db.session import engine
from app.db.models import Base

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(
        "repayment_service_starting",
        env=settings.app_env,
        db=settings.db_url.split("@")[-1],  # log host only, not credentials
    )

    # In development, auto-create tables (production uses Alembic migrations)
    if settings.app_env == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("repayment_tables_ready")

    yield

    # Shutdown
    await engine.dispose()
    logger.info("repayment_service_stopped")


app = FastAPI(
    title="LendKit Repayment Service",
    description=__doc__,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
)

# CORS — restrict to internal services in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(repayments_router)


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------


@app.get("/health", tags=["System"], include_in_schema=False)
async def health():
    return {
        "status": "healthy",
        "service": "repayment",
        "version": "0.1.0",
        "env": settings.app_env,
    }


@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    return {"service": "lendkit-repayment", "docs": "/docs"}
