"""Notification Service — FastAPI Application Entry Point."""

from __future__ import annotations

import asyncio
import logging
import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.app_env == "development" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LendKit Notification Service",
    version="1.0.0",
    description="SMS, email, and push notification dispatch for the LendKit loan lifecycle.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "notification"}


@app.on_event("startup")
async def _startup() -> None:
    from app.workers.event_consumer import run_consumer
    asyncio.create_task(run_consumer())
    logger.info("Notification event consumer started")
