"""
Integration Test — Gateway Health & Auth

Tests that don't need the full loan lifecycle:
  - /health returns gateway + all service statuses
  - /auth/token issues a valid JWT
  - Protected routes reject unauthenticated requests
  - X-Request-ID is present in every response
"""

from __future__ import annotations

import httpx
import pytest


class TestHealth:
    def test_health_returns_200(self, gateway_url: str):
        resp = httpx.get(f"{gateway_url}/health", timeout=5.0)
        assert resp.status_code == 200

    def test_health_contains_gateway_ok(self, gateway_url: str):
        data = httpx.get(f"{gateway_url}/health").json()
        assert data["gateway"] == "ok"

    def test_health_lists_all_services(self, gateway_url: str):
        data = httpx.get(f"{gateway_url}/health").json()
        expected = {
            "kyc", "credit-scoring", "loan-origination", "repayment",
            "disbursement", "notifications", "collections",
        }
        assert expected == set(data["services"].keys())

    def test_health_status_is_ok_or_degraded(self, gateway_url: str):
        data = httpx.get(f"{gateway_url}/health").json()
        assert data["status"] in {"ok", "degraded"}


class TestAuth:
    def test_token_endpoint_is_public(self, gateway_url: str):
        """No auth header needed for /auth/token."""
        resp = httpx.post(
            f"{gateway_url}/auth/token",
            json={"tenant_id": "lendkit-test", "api_key": "any-key", "role": "admin"},
        )
        # In development mode, any key is accepted
        assert resp.status_code == 200

    def test_token_response_has_access_token(self, gateway_url: str):
        resp = httpx.post(
            f"{gateway_url}/auth/token",
            json={"tenant_id": "lendkit-test", "api_key": "any-key", "role": "admin"},
        )
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_protected_route_without_token_returns_401(self, gateway_url: str):
        resp = httpx.get(f"{gateway_url}/kyc/health")
        assert resp.status_code == 401

    def test_protected_route_with_bad_token_returns_401(self, gateway_url: str):
        resp = httpx.get(
            f"{gateway_url}/kyc/health",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_authenticated_request_succeeds(self, client: httpx.Client):
        """Authenticated request to /kyc/health should proxy and return 200."""
        resp = client.get("/kyc/health")
        assert resp.status_code == 200

    def test_response_contains_request_id_header(self, client: httpx.Client):
        resp = client.get("/kyc/health")
        assert "x-request-id" in {k.lower() for k in resp.headers}


class TestRouting:
    @pytest.mark.parametrize("path,expected_service", [
        ("/kyc/health",           "kyc"),
        ("/scoring/health",       "credit-scoring"),
        ("/loans/health",         "loan-origination"),
        ("/repayment/health",     "repayment"),
        ("/disbursement/health",  "disbursement"),
        ("/notifications/health", "notifications"),
        ("/collections/health",   "collections"),
    ])
    def test_service_health_reachable_via_gateway(
        self, client: httpx.Client, path: str, expected_service: str
    ):
        resp = client.get(path)
        # 200 = service up and healthy; 502 = service down (still a routing success)
        assert resp.status_code in {200, 502}, (
            f"Unexpected status {resp.status_code} for {path}: {resp.text}"
        )

    def test_unknown_path_returns_404(self, client: httpx.Client):
        resp = client.get("/nonexistent/path")
        assert resp.status_code == 404
