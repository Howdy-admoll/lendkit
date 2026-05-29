"""
LendKit — Loan Origination & Disbursement Service

Orchestrates the full loan lifecycle:
  Application → Credit Score → Underwriting → Offer → Acceptance → Disbursement → Active

Port: 8003
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.v1.loans import router as loans_router
from app.core.config import settings

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger(__name__)
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("loan_origination.startup", env=settings.app_env, port=settings.port)
    yield
    logger.info("loan_origination.shutdown")


app = FastAPI(
    title="LendKit Loan Origination Service",
    description="End-to-end loan origination and disbursement pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Routers
app.include_router(loans_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["System"])
async def health() -> dict:
    return {
        "status": "healthy",
        "service": "loan-origination",
        "version": "0.1.0",
        "env": settings.app_env,
        "integrations": {
            "kyc_service": settings.kyc_service_url,
            "scoring_service": settings.scoring_service_url,
        },
    }
