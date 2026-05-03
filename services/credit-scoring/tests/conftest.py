"""
Credit Scoring — Test Configuration

Engine unit tests require NO database or Redis connection — the scoring
engine is pure Python and fully testable in isolation.
"""

import os

# Set required env vars before any app code imports
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-do-not-use-in-production-32ch")
os.environ.setdefault(
    "DB_URL", "postgresql+asyncpg://lendkit:lendkit@localhost:5432/credit_scoring_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("REDIS_STREAM_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "development")
