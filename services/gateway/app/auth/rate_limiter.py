"""
API Gateway — Redis-backed Rate Limiter

Uses a sliding window counter in Redis.

Strategy:
  Key:   "rl:{scope}:{identifier}:{current_minute_bucket}"
  Value: integer request count
  TTL:   120 seconds (2 buckets so we never lose counts mid-rotation)

Two scopes are enforced independently:
  ip       — per client IP address
  tenant   — per tenant_id from the JWT payload

Both must pass for the request to proceed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.core.config import get_settings


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    scope: str          # "ip" or "tenant"
    identifier: str
    current_count: int
    limit: int


def _minute_bucket() -> int:
    """Current UTC minute as an integer (resets every minute)."""
    return int(time.time()) // 60


async def check_rate_limit(
    redis_client: aioredis.Redis,
    *,
    ip: str,
    tenant_id: str | None,
) -> RateLimitResult:
    """
    Check both IP and tenant rate limits.

    Returns the first limit that is exceeded, or an allowed result
    if both pass.

    Parameters
    ----------
    redis_client:
        Connected async Redis client.
    ip:
        Client IP address string.
    tenant_id:
        JWT tenant_id, or None for unauthenticated requests.

    Returns
    -------
    RateLimitResult
        allowed=True if both limits pass, False with scope/identifier
        indicating which limit was hit.
    """
    settings = get_settings()
    bucket = _minute_bucket()

    # ── IP limit ──────────────────────────────────────────────────────────
    ip_key = f"rl:ip:{ip}:{bucket}"
    ip_count = await _increment(redis_client, ip_key)
    if ip_count > settings.rate_limit_per_ip_per_minute:
        return RateLimitResult(
            allowed=False,
            scope="ip",
            identifier=ip,
            current_count=ip_count,
            limit=settings.rate_limit_per_ip_per_minute,
        )

    # ── Tenant limit ──────────────────────────────────────────────────────
    if tenant_id:
        tenant_key = f"rl:tenant:{tenant_id}:{bucket}"
        tenant_count = await _increment(redis_client, tenant_key)
        if tenant_count > settings.rate_limit_per_tenant_per_minute:
            return RateLimitResult(
                allowed=False,
                scope="tenant",
                identifier=tenant_id,
                current_count=tenant_count,
                limit=settings.rate_limit_per_tenant_per_minute,
            )

    return RateLimitResult(
        allowed=True,
        scope="ip",
        identifier=ip,
        current_count=ip_count,
        limit=settings.rate_limit_per_ip_per_minute,
    )


async def _increment(redis_client: aioredis.Redis, key: str) -> int:
    """Atomically increment a rate limit counter, setting TTL on first write."""
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 120)   # 2 minutes TTL
    results = await pipe.execute()
    return int(results[0])


# ---------------------------------------------------------------------------
# In-memory rate limiter for tests (no Redis dependency)
# ---------------------------------------------------------------------------

class InMemoryRateLimiter:
    """
    Lightweight in-memory rate limiter for unit tests.

    Counts per (scope, identifier, bucket) — same logic as Redis version
    but stored in a plain dict.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def _key(self, scope: str, identifier: str) -> str:
        bucket = _minute_bucket()
        return f"rl:{scope}:{identifier}:{bucket}"

    def increment(self, scope: str, identifier: str) -> int:
        key = self._key(scope, identifier)
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    def get_count(self, scope: str, identifier: str) -> int:
        return self._counts.get(self._key(scope, identifier), 0)

    def reset(self, scope: str, identifier: str) -> None:
        key = self._key(scope, identifier)
        self._counts.pop(key, None)

    def check(
        self,
        *,
        ip: str,
        tenant_id: str | None,
        ip_limit: int,
        tenant_limit: int,
    ) -> RateLimitResult:
        ip_count = self.increment("ip", ip)
        if ip_count > ip_limit:
            return RateLimitResult(
                allowed=False, scope="ip", identifier=ip,
                current_count=ip_count, limit=ip_limit,
            )

        if tenant_id:
            tenant_count = self.increment("tenant", tenant_id)
            if tenant_count > tenant_limit:
                return RateLimitResult(
                    allowed=False, scope="tenant", identifier=tenant_id,
                    current_count=tenant_count, limit=tenant_limit,
                )

        return RateLimitResult(
            allowed=True, scope="ip", identifier=ip,
            current_count=ip_count, limit=ip_limit,
        )
