"""
API Gateway — Request Logging Middleware

Logs every request and response with:
  - method, path, status code, latency
  - X-Request-ID (generated here if not present)
  - tenant_id from JWT (if authenticated)

The request ID is also injected into the response headers so clients
can correlate logs end-to-end.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("gateway.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        start = time.perf_counter()
        response: Response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000

        tenant_id = getattr(request.state, "tenant_id", "-")

        logger.info(
            "%s %s %d %.1fms tenant=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
            tenant_id,
            request_id,
        )

        response.headers["X-Request-ID"] = request_id
        return response
