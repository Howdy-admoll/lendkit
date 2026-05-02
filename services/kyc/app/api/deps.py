"""
KYC Service — FastAPI Dependencies
"""

from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import verify_token
from app.db.session import get_db

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DBDep = Annotated[AsyncSession, Depends(get_db)]

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

_redis_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_pool


RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def get_current_tenant(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """
    Extract and validate the tenant JWT from the Authorization header.
    Returns the tenant_id (sub claim).
    """
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization format. Expected: Bearer <token>",
        )

    tenant_id = verify_token(token)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return tenant_id


TenantDep = Annotated[str, Depends(get_current_tenant)]
