"""
KYC Service — Application Configuration
Loaded from environment variables with pydantic-settings.
"""
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn
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
    service_port: int = 8001
    log_level: str = "INFO"
    secret_key: str = Field(..., min_length=32)

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    db_url: PostgresDsn = Field(
        default="postgresql+asyncpg://lendkit:lendkit@postgres:5432/kyc"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # -------------------------------------------------------------------------
    # Redis / Celery
    # -------------------------------------------------------------------------
    redis_url: RedisDsn = Field(default="redis://redis:6379/0")
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"
    celery_task_serializer: str = "json"
    celery_result_expires: int = 3600  # seconds

    # -------------------------------------------------------------------------
    # BIN Lookup
    # -------------------------------------------------------------------------
    bin_api_url: AnyHttpUrl = Field(default="https://lookup.binlist.net")
    bin_api_key: str = ""
    bin_cache_ttl: int = 86400  # 24 hours — BIN data changes infrequently
    bin_request_timeout: int = 10  # seconds

    # -------------------------------------------------------------------------
    # Identity Verification Provider
    # -------------------------------------------------------------------------
    identity_provider: Literal["smile_id", "onfido", "mock"] = "mock"
    identity_api_key: str = ""
    identity_api_url: str = "https://api.smileidentity.com/v1"
    identity_request_timeout: int = 30

    # -------------------------------------------------------------------------
    # Document Validation
    # -------------------------------------------------------------------------
    document_provider: Literal["mock", "aws_textract", "google_vision"] = "mock"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # -------------------------------------------------------------------------
    # Event Bus
    # -------------------------------------------------------------------------
    event_backend: Literal["redis", "kafka"] = "redis"
    redis_stream_url: str = "redis://redis:6379/1"
    kafka_bootstrap_servers: str = "kafka:9092"

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
    otel_service_name: str = "kyc-service"

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
