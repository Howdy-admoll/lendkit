"""
API Gateway — Rate Limiter Unit Tests

Uses InMemoryRateLimiter — no Redis required.
"""

import pytest

from app.auth.rate_limiter import InMemoryRateLimiter

IP = "192.168.1.1"
TENANT = "acme"
IP_LIMIT = 5
TENANT_LIMIT = 10


def _make_limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter()


class TestInMemoryRateLimiter:
    def test_first_request_is_allowed(self):
        limiter = _make_limiter()
        result = limiter.check(ip=IP, tenant_id=TENANT, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        assert result.allowed is True

    def test_requests_within_limit_are_allowed(self):
        limiter = _make_limiter()
        for _ in range(IP_LIMIT):
            result = limiter.check(ip=IP, tenant_id=TENANT, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
            assert result.allowed is True

    def test_request_exceeding_ip_limit_is_blocked(self):
        limiter = _make_limiter()
        for _ in range(IP_LIMIT):
            limiter.check(ip=IP, tenant_id=TENANT, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        # This one exceeds
        result = limiter.check(ip=IP, tenant_id=TENANT, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        assert result.allowed is False
        assert result.scope == "ip"
        assert result.identifier == IP

    def test_result_contains_limit_and_count(self):
        limiter = _make_limiter()
        result = limiter.check(ip=IP, tenant_id=TENANT, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        assert result.limit == IP_LIMIT
        assert result.current_count == 1

    def test_different_ips_have_independent_counters(self):
        limiter = _make_limiter()
        ip2 = "10.0.0.1"
        for _ in range(IP_LIMIT):
            limiter.check(ip=IP, tenant_id=TENANT, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        # ip2 has not been used — should still be allowed
        result = limiter.check(ip=ip2, tenant_id=TENANT, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        assert result.allowed is True

    def test_tenant_limit_is_enforced(self):
        limiter = _make_limiter()
        # Different IPs, same tenant — exhaust tenant limit
        for i in range(TENANT_LIMIT):
            limiter.check(
                ip=f"10.0.0.{i}",
                tenant_id=TENANT,
                ip_limit=1000,           # high IP limit so it won't trigger
                tenant_limit=TENANT_LIMIT,
            )
        result = limiter.check(
            ip="10.0.0.99",
            tenant_id=TENANT,
            ip_limit=1000,
            tenant_limit=TENANT_LIMIT,
        )
        assert result.allowed is False
        assert result.scope == "tenant"
        assert result.identifier == TENANT

    def test_no_tenant_id_skips_tenant_check(self):
        limiter = _make_limiter()
        # Even with tenant_limit=0, no tenant_id means no tenant check
        result = limiter.check(ip=IP, tenant_id=None, ip_limit=IP_LIMIT, tenant_limit=0)
        assert result.allowed is True

    def test_reset_clears_counter(self):
        limiter = _make_limiter()
        for _ in range(IP_LIMIT + 1):
            limiter.check(ip=IP, tenant_id=None, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        limiter.reset("ip", IP)
        result = limiter.check(ip=IP, tenant_id=None, ip_limit=IP_LIMIT, tenant_limit=TENANT_LIMIT)
        assert result.allowed is True

    def test_get_count_returns_current_count(self):
        limiter = _make_limiter()
        limiter.increment("ip", IP)
        limiter.increment("ip", IP)
        assert limiter.get_count("ip", IP) == 2

    def test_get_count_returns_zero_for_unseen_key(self):
        limiter = _make_limiter()
        assert limiter.get_count("ip", "unseen") == 0
