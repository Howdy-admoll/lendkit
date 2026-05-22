"""
API Gateway — Proxy Router Unit Tests

Pure Python — no HTTP, no DB.
"""

import pytest

from app.core.config import get_settings
from app.routes.proxy import (
    build_routing_table,
    build_upstream_headers,
    new_request_id,
    resolve_upstream,
)

settings = get_settings()
_table = build_routing_table(settings)


# ===========================================================================
# resolve_upstream
# ===========================================================================


class TestResolveUpstream:
    @pytest.mark.parametrize("path,expected_prefix", [
        ("/kyc/v1/verify", "/kyc"),
        ("/scoring/v1/score", "/scoring"),
        ("/loans/v1/apply", "/loans"),
        ("/repayment/v1/schedule", "/repayment"),
        ("/disbursement/v1/initiate", "/disbursement"),
        ("/notifications/v1/send", "/notifications"),
        ("/collections/v1/cases", "/collections"),
    ])
    def test_known_prefixes_resolve(self, path, expected_prefix):
        result = resolve_upstream(path, _table)
        assert result is not None
        entry, _ = result
        assert entry.prefix == expected_prefix

    def test_unknown_path_returns_none(self):
        assert resolve_upstream("/unknown/path", _table) is None

    def test_root_path_returns_none(self):
        assert resolve_upstream("/", _table) is None

    def test_partial_prefix_does_not_match(self):
        """'/kycextra' must not match '/kyc'."""
        assert resolve_upstream("/kycextra/foo", _table) is None

    def test_exact_prefix_matches(self):
        """'/kyc' with no trailing slash should still resolve."""
        result = resolve_upstream("/kyc", _table)
        assert result is not None

    def test_upstream_path_strips_prefix(self):
        result = resolve_upstream("/kyc/v1/verify", _table)
        assert result is not None
        _, upstream_path = result
        assert upstream_path == "/v1/verify"

    def test_upstream_path_is_slash_for_exact_prefix(self):
        result = resolve_upstream("/kyc", _table)
        assert result is not None
        _, upstream_path = result
        assert upstream_path == "/"

    def test_upstream_url_points_to_correct_service(self):
        result = resolve_upstream("/kyc/anything", _table)
        assert result is not None
        entry, _ = result
        assert "8001" in entry.upstream_url or "kyc" in entry.upstream_url.lower()

    def test_collections_resolves_to_8007(self):
        result = resolve_upstream("/collections/cases", _table)
        assert result is not None
        entry, _ = result
        assert "8007" in entry.upstream_url or "collections" in entry.upstream_url.lower()


# ===========================================================================
# build_upstream_headers
# ===========================================================================


class TestBuildUpstreamHeaders:
    def test_tenant_id_injected(self):
        headers = build_upstream_headers({}, tenant_id="acme", request_id="req-123")
        assert headers["X-Tenant-ID"] == "acme"

    def test_request_id_injected(self):
        headers = build_upstream_headers({}, tenant_id="acme", request_id="req-123")
        assert headers["X-Request-ID"] == "req-123"

    def test_hop_by_hop_headers_stripped(self):
        incoming = {
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
            "host": "gateway.example.com",
            "content-type": "application/json",
        }
        headers = build_upstream_headers(incoming, tenant_id="acme", request_id="req-1")
        assert "connection" not in headers
        assert "transfer-encoding" not in headers
        assert "host" not in headers

    def test_non_hop_by_hop_headers_preserved(self):
        incoming = {
            "content-type": "application/json",
            "authorization": "Bearer token",
            "x-custom": "value",
        }
        headers = build_upstream_headers(incoming, tenant_id="acme", request_id="req-1")
        assert headers["content-type"] == "application/json"
        assert headers["authorization"] == "Bearer token"
        assert headers["x-custom"] == "value"

    def test_empty_incoming_headers(self):
        headers = build_upstream_headers({}, tenant_id="acme", request_id="req-1")
        assert "X-Tenant-ID" in headers
        assert "X-Request-ID" in headers


# ===========================================================================
# new_request_id
# ===========================================================================


class TestNewRequestId:
    def test_returns_string(self):
        assert isinstance(new_request_id(), str)

    def test_is_uuid_format(self):
        import uuid
        rid = new_request_id()
        uuid.UUID(rid)   # raises ValueError if not valid UUID

    def test_each_call_unique(self):
        ids = {new_request_id() for _ in range(100)}
        assert len(ids) == 100
