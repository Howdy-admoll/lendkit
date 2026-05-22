"""
API Gateway — Reverse Proxy Router

Maps URL path prefixes to upstream service base URLs and streams
the response back to the caller.

Routing table:
  /kyc/*            → KYC service          :8001
  /scoring/*        → Credit Scoring       :8002
  /loans/*          → Loan Origination     :8003
  /repayment/*      → Repayment Tracking   :8004
  /disbursement/*   → Disbursement         :8005
  /notifications/*  → Notifications        :8006
  /collections/*    → Collections          :8007

The gateway strips the prefix and forwards the remainder of the path,
preserving query parameters, headers (minus hop-by-hop), and body.

It injects two headers on every upstream request:
  X-Tenant-ID   — from the verified JWT payload
  X-Request-ID  — UUID generated per request for distributed tracing
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class RouteEntry:
    prefix: str        # URL prefix matched (e.g. "/kyc")
    upstream_url: str  # base URL of the target service


def build_routing_table(settings) -> list[RouteEntry]:
    """Build the routing table from settings. Order matters — first match wins."""
    return [
        RouteEntry(prefix="/kyc",           upstream_url=settings.kyc_url),
        RouteEntry(prefix="/scoring",       upstream_url=settings.credit_scoring_url),
        RouteEntry(prefix="/loans",         upstream_url=settings.loan_origination_url),
        RouteEntry(prefix="/repayment",     upstream_url=settings.repayment_url),
        RouteEntry(prefix="/disbursement",  upstream_url=settings.disbursement_url),
        RouteEntry(prefix="/notifications", upstream_url=settings.notification_url),
        RouteEntry(prefix="/collections",   upstream_url=settings.collections_url),
    ]


def resolve_upstream(path: str, routing_table: list[RouteEntry]) -> tuple[RouteEntry, str] | None:
    """
    Find the upstream entry for a given request path.

    Returns (RouteEntry, upstream_path) or None if no prefix matches.

    The upstream_path is the path with the service prefix stripped:
      /kyc/v1/verify → /v1/verify  (forwarded to KYC service)
    """
    for entry in routing_table:
        if path == entry.prefix or path.startswith(entry.prefix + "/"):
            upstream_path = path[len(entry.prefix):]
            if not upstream_path:
                upstream_path = "/"
            return entry, upstream_path
    return None


# Hop-by-hop headers that must NOT be forwarded to upstreams
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "host",  # rewritten by httpx
})


def build_upstream_headers(
    incoming_headers: dict[str, str],
    *,
    tenant_id: str,
    request_id: str,
) -> dict[str, str]:
    """
    Build the header set to send upstream.

    Strips hop-by-hop headers, injects X-Tenant-ID and X-Request-ID.
    """
    forwarded = {
        k: v
        for k, v in incoming_headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    forwarded["X-Tenant-ID"] = tenant_id
    forwarded["X-Request-ID"] = request_id
    return forwarded


def new_request_id() -> str:
    return str(uuid.uuid4())
