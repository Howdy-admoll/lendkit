"""
Repayment Service — Application Settings

All settings are read from environment variables (12-factor).
Defaults are development-safe; production overrides via k8s secrets / env.
"""

from __future__ import annotations

from pydantic import Field
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
    service_name: str = "repayment"
    log_level: str = "INFO"

    # HTTP server
    port: int = 8004

    # Database
    db_url: str = "postgresql+asyncpg://lendkit:lendkit@localhost:5432/repayment_dev"

    # Redis (event bus)
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_url: str = "redis://localhost:6379/1"

    # Security
    secret_key: str = "change-me-in-production-at-least-32-characters"

    # Downstream services
    loan_origination_service_url: str = "http://loan-origination:8003"
    service_timeout: float = 10.0
    service_retries: int = 3

    # Business rules
    grace_period_days: int = 7           # DPD ≤ this before penalty clock starts
    default_threshold_days: int = 90     # DPD ≥ this → DEFAULT status
    write_off_threshold_days: int = 360  # DPD ≥ this → write-off candidate
    daily_penalty_rate: float = 0.001    # 0.1% of outstanding principal per day
    offer_acceptance_window_hours: int = 48

    # Webhook security
    paystack_secret: str = ""
    flutterwave_secret: str = ""


settings = Settings()
