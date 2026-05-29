"""
LendKit — Integration Test Configuration

These tests require the full stack to be running:
  docker compose up --build -d

The GATEWAY_URL environment variable (default: http://localhost:8000)
points all requests through the API Gateway.

Run with:
  pytest tests/ -v --tb=short

Skip if the stack is not up:
  pytest tests/ -v --ignore=tests/ -k "not integration"
"""

from __future__ import annotations

import os

import httpx
import pytest

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
TENANT_ID = os.environ.get("TEST_TENANT_ID", "lendkit-test")
API_KEY = os.environ.get("TEST_API_KEY", "test-api-key")


def is_gateway_up() -> bool:
    """Check if the gateway is reachable before running any tests."""
    try:
        resp = httpx.get(f"{GATEWAY_URL}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


# Skip all integration tests if the stack isn't running
pytestmark = pytest.mark.skipif(
    not is_gateway_up(),
    reason="Integration stack not running — start with `docker compose up -d`",
)


@pytest.fixture(scope="session")
def gateway_url() -> str:
    return GATEWAY_URL


@pytest.fixture(scope="session")
def auth_token(gateway_url: str) -> str:
    """Obtain a JWT token from the gateway for the test tenant."""
    resp = httpx.post(
        f"{gateway_url}/auth/token",
        json={"tenant_id": TENANT_ID, "api_key": API_KEY, "role": "admin"},
        timeout=10.0,
    )
    assert resp.status_code == 200, f"Could not obtain token: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def client(gateway_url: str, auth_token: str) -> httpx.Client:
    """Authenticated HTTP client pointed at the gateway."""
    return httpx.Client(
        base_url=gateway_url,
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30.0,
    )
