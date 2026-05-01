"""
LendKit Shared — Structured Logging Middleware

Adds request correlation IDs and structured log context to every FastAPI request.
Each log line includes: request_id, method, path, status_code, duration_ms, tenant_id.
"""
import time
import uuid
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("lendkit.access")

# Header name for request tracing
X_REQUEST_ID = "X-Request-ID"
X_CORRELATION_ID = "X-Correlation-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:
    1. Assigns a unique request_id to every request
    2. Propagates or generates a correlation_id for distributed tracing
    3. Logs structured access logs on every response
    4. Attaches request_id to response headers
    """

    SKIP_PATHS = {"/health", "/metrics", "/"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        # Generate or propagate request ID
        request_id    = request.headers.get(X_REQUEST_ID) or uuid.uuid4().hex
        correlation_id = request.headers.get(X_CORRELATION_ID) or request_id

        # Attach to request state for downstream access
        request.state.request_id     = request_id
        request.state.correlation_id = correlation_id

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            log.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc),
                },
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000

        log.info(
            "%s %s %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "request_id": request_id,
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": request.client.host if request.client else "unknown",
            },
        )

        # Add tracing headers to response
        response.headers[X_REQUEST_ID]     = request_id
        response.headers[X_CORRELATION_ID] = correlation_id

        return response


def get_request_id(request: Request) -> str:
    """FastAPI dependency — retrieve request_id from request state."""
    return getattr(request.state, "request_id", "unknown")
