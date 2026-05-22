"""
API Gateway — Configuration

All upstream service URLs, JWT settings, and rate limit thresholds
are read from environment variables.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────
    app_env: str = "development"
    service_name: str = "gateway"

    # ── JWT ──────────────────────────────────────────────────────────────
    jwt_secret_key: str = "change-me-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # ── Redis (rate limiting) ─────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Rate limits ───────────────────────────────────────────────────────
    rate_limit_per_ip_per_minute: int = 120
    rate_limit_per_tenant_per_minute: int = 600

    # ── Upstream service URLs ─────────────────────────────────────────────
    kyc_url: str = "http://localhost:8001"
    credit_scoring_url: str = "http://localhost:8002"
    loan_origination_url: str = "http://localhost:8003"
    repayment_url: str = "http://localhost:8004"
    disbursement_url: str = "http://localhost:8005"
    notification_url: str = "http://localhost:8006"
    collections_url: str = "http://localhost:8007"

    # ── Proxy ─────────────────────────────────────────────────────────────
    proxy_timeout_seconds: float = 30.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
