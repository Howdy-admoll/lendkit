"""
Credit Scoring Service — Application Configuration
Loaded from environment variables with pydantic-settings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    app_env: Literal["development", "staging", "production"] = "development"
    service_port: int = 8002
    log_level: str = "INFO"
    secret_key: str = Field(..., min_length=32)

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    db_url: PostgresDsn = Field(
        default="postgresql+asyncpg://lendkit:lendkit@postgres:5432/credit_scoring"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # -------------------------------------------------------------------------
    # Redis — broker + stream consumer
    # -------------------------------------------------------------------------
    redis_url: RedisDsn = Field(default="redis://redis:6379/0")
    redis_stream_url: str = "redis://redis:6379/1"

    # The Redis stream where KYC service publishes approved verification events
    kyc_stream_key: str = "lendkit:kyc:events"
    kyc_consumer_group: str = "credit-scoring"
    kyc_consumer_name: str = "credit-scoring-worker-1"
    # How many events to pull per XREADGROUP call
    kyc_batch_size: int = 10
    # Block up to N ms waiting for new events (0 = no block)
    kyc_block_ms: int = 5000

    # -------------------------------------------------------------------------
    # Scoring Engine
    # -------------------------------------------------------------------------
    # Score range emitted to callers: 300–850 (FICO-like)
    score_min: int = 300
    score_max: int = 850

    # Tier thresholds (inclusive lower bound)
    tier_excellent_min: int = 750  # Tier A — best rates
    tier_good_min: int = 650  # Tier B
    tier_fair_min: int = 550  # Tier C
    tier_poor_min: int = 450  # Tier D
    # < tier_poor_min → declined

    # -------------------------------------------------------------------------
    # JWT / Security
    # -------------------------------------------------------------------------
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # -------------------------------------------------------------------------
    # Observability
    # -------------------------------------------------------------------------
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"
    otel_service_name: str = "credit-scoring-service"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — call this everywhere."""
    return Settings()


settings = get_settings()
