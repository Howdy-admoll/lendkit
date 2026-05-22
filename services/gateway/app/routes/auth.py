"""
API Gateway — Auth Routes

POST /auth/token
  Issue a JWT token. In production this would validate against a user store
  or API key registry. Here we accept a simple API key per tenant that is
  configured via environment variables (good enough for v1; swap for a real
  identity provider later).

GET /auth/verify
  Verify a token and return the decoded payload (useful for debugging and
  downstream service-to-service auth checks).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth.jwt import TokenError, create_access_token, extract_bearer_token, verify_token
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    tenant_id: str
    api_key: str
    role: str = "admin"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class VerifyResponse(BaseModel):
    sub: str
    tenant_id: str
    role: str


@router.post("/token", response_model=TokenResponse)
async def issue_token(body: TokenRequest) -> TokenResponse:
    """
    Issue a JWT access token.

    Validates the API key against TENANT_{TENANT_ID}_API_KEY environment variable.
    For a tenant_id of "acme", the key is read from TENANT_ACME_API_KEY.

    This is a simple but secure approach for v1 — no user store needed.
    """
    settings = get_settings()
    env_key_name = f"TENANT_{body.tenant_id.upper().replace('-', '_')}_API_KEY"

    import os
    expected_key = os.environ.get(env_key_name)

    # In development mode, accept any key to make local testing easy
    if settings.app_env != "development" and not expected_key:
        raise HTTPException(status_code=401, detail="Unknown tenant")

    if expected_key and body.api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    token = create_access_token(
        subject=body.tenant_id,
        tenant_id=body.tenant_id,
        role=body.role,
    )

    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.jwt_access_token_expire_minutes,
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify(authorization: str | None = None) -> VerifyResponse:
    """Verify a token and return its decoded claims."""
    try:
        token = extract_bearer_token(authorization)
        payload = verify_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    return VerifyResponse(
        sub=payload.get("sub", ""),
        tenant_id=payload.get("tenant_id", ""),
        role=payload.get("role", ""),
    )
