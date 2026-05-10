"""Collections Service — Configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    service_name: str = "collections"

    db_url: str = "postgresql+asyncpg://lendkit:lendkit@localhost:5432/collections"

    redis_url: str = "redis://localhost:6379/0"
    redis_stream_url: str = "redis://localhost:6379/1"

    # Notification service base URL (for publishing escalation outreach requests)
    notification_service_url: str = "http://localhost:8006"

    # Agent queue config
    max_cases_per_agent: int = 50

    # Write-off threshold (days past due)
    write_off_dpd_threshold: int = 90

    # Event consumer
    consumer_group: str = "collections-service"
    consumer_name: str = "collections-worker-1"
    consumer_block_ms: int = 5_000
    consumer_batch_size: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
