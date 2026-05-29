"""Collections Service — FastAPI Application Entry Point."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.cases import router as cases_router
from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.app_env == "development" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LendKit Collections Service",
    version="1.0.0",
    description="Automated collections workflow, agent queue, and escalation for defaulted loans.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(cases_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "collections"}


@app.on_event("startup")
async def _startup() -> None:
    from app.workers.event_consumer import run_consumer
    asyncio.create_task(run_consumer())
    logger.info("Collections event consumer started")
