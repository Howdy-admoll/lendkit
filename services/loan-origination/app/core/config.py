"""
Loan Origination Service — Configuration

Port 8003 (KYC=8001, Credit Scoring=8002, Loan Origination=8003)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service identity
    app_name: str = "lendkit-loan-origination"
    app_env: str = "development"
    port: int = 8003
    secret_key: str

    # Database
    db_url: str  # postgresql+asyncpg://...

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Downstream service base URLs (internal network)
    kyc_service_url: str = "http://kyc:8001"
    scoring_service_url: str = "http://credit-scoring:8002"

    # HTTP client timeouts (seconds)
    service_timeout: float = 10.0
    service_retries: int = 3

    # Underwriting limits (kobo — 1 NGN = 100 kobo)
    min_loan_amount_kobo: int = 10_000_00       # ₦100,000
    max_loan_amount_kobo: int = 500_000_000     # ₦5,000,000
    min_tenure_months: int = 3
    max_tenure_months: int = 36

    # Offer expiry
    offer_validity_hours: int = 48


settings = Settings()  # type: ignore[call-arg]
