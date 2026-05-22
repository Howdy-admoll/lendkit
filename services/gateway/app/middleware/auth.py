"""
API Gateway — Authentication Middleware

Enforces JWT auth on all routes except the public allowlist.

Public routes (no token required):
  POST /auth/token   — obtain a token
  GET  /health       — gateway + upstream health

For all other routes:
  1. Extract Bearer token from Authorization header
  2. Verify signature and expiry
  3. Attach decoded payload to request.state for downstream use
  4. Return 401 if token is missing/invalid/expired
"""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.jwt import TokenError, extract_bearer_token, verify_token

_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/auth/token",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        try:
            token = extract_bearer_token(authorization)
            payload = verify_token(token)
        except TokenError as exc:
            return JSONResponse(
                status_code=401,
                content={"detail": str(exc)},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Attach payload to request state for rate limiter and proxy
        request.state.jwt_payload = payload
        request.state.tenant_id = payload.get("tenant_id", "unknown")
        return await call_next(request)
