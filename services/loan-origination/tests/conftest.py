"""
Loan Origination — Test Configuration

Underwriting engine tests are fully isolated — no DB, no HTTP calls.
"""

import os

os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-do-not-use-in-production-32ch")
os.environ.setdefault(
    "DB_URL", "postgresql+asyncpg://lendkit:lendkit@localhost:5432/loan_origination_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "development")
