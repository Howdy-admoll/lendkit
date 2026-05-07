"""
Notification Service — Configuration

All settings are read from environment variables with sensible defaults
for local development.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────
    app_env: str = "development"
    service_name: str = "notification"

    # ── Database ─────────────────────────────────────────────────────────
    db_url: str = "postgresql+asyncpg://lendkit:lendkit@localhost:5432/notification"

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_url: str = "redis://localhost:6379/1"

    # ── Termii (SMS) ─────────────────────────────────────────────────────
    termii_api_key: str = "termii-test-key"
    termii_sender_id: str = "LendKit"
    termii_channel: str = "generic"

    # ── SendGrid (Email) ─────────────────────────────────────────────────
    sendgrid_api_key: str = "SG.test-key"
    sendgrid_from_email: str = "noreply@lendkit.io"
    sendgrid_from_name: str = "LendKit"

    # ── Support contact (used in templates) ──────────────────────────────
    support_email: str = "support@lendkit.io"
    support_phone: str = "+2348001234567"

    # ── Reminder schedule ────────────────────────────────────────────────
    # Days before due date at which we send reminders
    reminder_days_before: list[int] = [3, 1]

    # ── Event consumer ───────────────────────────────────────────────────
    consumer_group: str = "notification-service"
    consumer_name: str = "notification-worker-1"
    consumer_block_ms: int = 5_000   # XREADGROUP block timeout
    consumer_batch_size: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
