"""
API Gateway — FastAPI Application Entry Point

Port 8000. Single entry point for all LendKit services.

Request flow:
  Client → [RequestLogging] → [Auth] → route handler
                                         ├─ /auth/*       (public)
                                         ├─ /health       (public)
                                         └─ /{service}/*  → upstream proxy
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from app.core.config import get_settings
from app.middleware.auth import AuthMiddleware
from app.middleware.logging import RequestLoggingMiddleware
from app.routes.auth import router as auth_router
from app.routes.health import router as health_router
from app.routes.proxy import (
    build_routing_table,
    build_upstream_headers,
    new_request_id,
    resolve_upstream,
)

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.app_env == "development" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LendKit API Gateway",
    version="1.0.0",
    description="Single entry point for all LendKit microservices. JWT auth, rate limiting, request logging.",
)

# ── Middleware (applied outermost-first) ─────────────────────────────────────
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static routes ─────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(health_router)

# ── Shared state ──────────────────────────────────────────────────────────────
_routing_table = build_routing_table(settings)
_http_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def _startup() -> None:
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=settings.proxy_timeout_seconds,
        trust_env=False,
        follow_redirects=True,
    )
    logger.info("API Gateway started on port 8000")


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _http_client:
        await _http_client.aclose()


# ── Catch-all proxy route ─────────────────────────────────────────────────────

@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy(request: Request, full_path: str) -> Response:
    """
    Forward any unmatched request to the appropriate upstream service.
    """
    path = "/" + full_path
    match = resolve_upstream(path, _routing_table)

    if match is None:
        raise HTTPException(status_code=404, detail=f"No upstream service for path: {path}")

    entry, upstream_path = match
    tenant_id = getattr(request.state, "tenant_id", "anonymous")
    request_id = getattr(request.state, "request_id", new_request_id())

    upstream_url = entry.upstream_url.rstrip("/") + upstream_path
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    headers = build_upstream_headers(
        dict(request.headers),
        tenant_id=tenant_id,
        request_id=request_id,
    )

    body = await request.body()

    try:
        upstream_response = await _http_client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body,
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502,
            detail=f"Upstream service unreachable: {entry.prefix}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=f"Upstream service timed out: {entry.prefix}",
        )

    # Strip hop-by-hop response headers before forwarding
    _skip = {"transfer-encoding", "connection"}
    response_headers = {
        k: v for k, v in upstream_response.headers.items()
        if k.lower() not in _skip
    }
    response_headers["X-Request-ID"] = request_id

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
