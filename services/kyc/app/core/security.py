"""
KYC Service — Security utilities
JWT decoding, API key validation, HMAC signature verification.
"""
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(
    subject: str | int,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed JWT access token."""
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": datetime.now(UTC),
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def verify_token(token: str) -> str | None:
    """Return subject (user_id) from token or None if invalid."""
    try:
        payload = decode_access_token(token)
        return payload.get("sub")
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Webhook / provider signature verification
# ---------------------------------------------------------------------------

def verify_hmac_signature(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256",
) -> bool:
    """
    Constant-time HMAC verification for inbound webhook payloads.
    Supports hex-encoded or 'sha256=...' prefixed signatures.
    """
    signature = signature.removeprefix(f"{algorithm}=")
    expected = hmac.new(
        secret.encode(), payload, getattr(hashlib, algorithm)
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# API Key helpers
# ---------------------------------------------------------------------------

def mask_api_key(key: str, visible: int = 6) -> str:
    """Return partially masked key safe for logging: sk_test_abc•••••"""
    if len(key) <= visible:
        return "*" * len(key)
    return key[:visible] + "•" * (len(key) - visible)


def generate_api_key(prefix: str = "lk") -> tuple[str, str]:
    """
    Generate a raw API key and its bcrypt hash.
    Returns (raw_key, hashed_key) — store only the hash.
    """
    import secrets
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    return raw, hash_password(raw)


# ---------------------------------------------------------------------------
# Rate limiting token bucket (simple in-memory, for testing)
# ---------------------------------------------------------------------------

class TokenBucket:
    """Simple token bucket for per-IP rate limiting (use Redis in prod)."""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self._tokens = capacity
        self._last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.capacity, self._tokens + elapsed * self.refill_rate
        )
        self._last_refill = now

        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False
