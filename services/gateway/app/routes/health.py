"""
API Gateway — Aggregate Health Check

GET /health

Polls the /health endpoint of every upstream service concurrently and
returns a combined status. The gateway is considered healthy even if some
upstreams are down — the caller can see which ones.

Response:
  {
    "status": "ok" | "degraded",
    "gateway": "ok",
    "services": {
      "kyc": "ok" | "unreachable",
      "credit-scoring": "ok" | "unreachable",
      ...
    }
  }
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])

_SERVICES: list[tuple[str, str]] = [
    ("kyc",              "kyc_url"),
    ("credit-scoring",   "credit_scoring_url"),
    ("loan-origination", "loan_origination_url"),
    ("repayment",        "repayment_url"),
    ("disbursement",     "disbursement_url"),
    ("notifications",    "notification_url"),
    ("collections",      "collections_url"),
]


async def _ping(name: str, base_url: str, client: httpx.AsyncClient) -> tuple[str, str]:
    try:
        resp = await client.get(f"{base_url}/health", timeout=3.0)
        return name, "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
    except Exception:
        return name, "unreachable"


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    async with httpx.AsyncClient(trust_env=False) as client:
        tasks = [
            _ping(name, getattr(settings, attr), client)
            for name, attr in _SERVICES
        ]
        results = await asyncio.gather(*tasks)

    services = dict(results)
    all_ok = all(v == "ok" for v in services.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "gateway": "ok",
        "services": services,
    }
