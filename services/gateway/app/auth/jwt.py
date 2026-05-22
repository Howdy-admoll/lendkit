"""
API Gateway — JWT Authentication

Issues and verifies HS256-signed JSON Web Tokens.

Token payload:
  sub        — subject (tenant_id or user_id)
  tenant_id  — tenant identifier for routing and rate limiting
  role       — "admin" | "agent" | "service"
  exp        — expiry (UTC unix timestamp)
  iat        — issued-at (UTC unix timestamp)

Usage:
  token = create_access_token(subject="tenant-abc", tenant_id="tenant-abc", role="admin")
  payload = verify_token(token)   # raises TokenError on failure
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings


class TokenError(Exception):
    """Raised when a token is invalid, expired, or tampered with."""


def create_access_token(
    *,
    subject: str,
    tenant_id: str,
    role: str = "admin",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Issue a signed JWT access token.

    Parameters
    ----------
    subject:
        Unique identifier for the token holder (user_id or tenant_id).
    tenant_id:
        Tenant this token belongs to — used for per-tenant rate limiting
        and upstream request tagging.
    role:
        Access role: "admin", "agent", or "service".
    extra_claims:
        Optional additional claims merged into the payload.

    Returns
    -------
    str
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict[str, Any]:
    """
    Verify and decode a JWT access token.

    Parameters
    ----------
    token:
        Raw JWT string (without "Bearer " prefix).

    Returns
    -------
    dict
        Decoded payload.

    Raises
    ------
    TokenError
        If the token is expired, tampered, or otherwise invalid.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise TokenError("Token has expired")
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"Invalid token: {exc}")


def extract_bearer_token(authorization: str | None) -> str:
    """
    Extract the raw token from an Authorization header value.

    Parameters
    ----------
    authorization:
        Header value e.g. "Bearer eyJ..."

    Returns
    -------
    str
        The raw token string.

    Raises
    ------
    TokenError
        If the header is missing or malformed.
    """
    if not authorization:
        raise TokenError("Authorization header missing")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise TokenError("Authorization header must be 'Bearer <token>'")
    return parts[1]
