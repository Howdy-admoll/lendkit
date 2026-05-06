"""Disbursement Service — Application Settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App identity
    app_env: str = "development"
    service_name: str = "disbursement"
    log_level: str = "INFO"

    # HTTP server
    port: int = 8005

    # Database
    db_url: str = "postgresql+asyncpg://lendkit:lendkit@localhost:5432/disbursement_dev"

    # Redis (event bus)
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_url: str = "redis://localhost:6379/1"
    loan_events_stream: str = "loan.events"
    disbursement_events_stream: str = "disbursement.events"
    consumer_group: str = "disbursement-service"

    # Security
    secret_key: str = "change-me-in-production-at-least-32-characters"

    # Paystack
    paystack_secret_key: str = ""          # sk_live_... or sk_test_...
    paystack_webhook_secret: str = ""      # for HMAC verification

    # Downstream services
    loan_origination_service_url: str = "http://loan-origination:8003"
    repayment_service_url: str = "http://repayment:8004"
    service_timeout: float = 30.0
    service_retries: int = 3

    # Business rules
    max_disbursement_attempts: int = 3
    retry_delay_seconds: int = 60          # base delay; worker applies backoff
    disbursement_currency: str = "NGN"


settings = Settings()
