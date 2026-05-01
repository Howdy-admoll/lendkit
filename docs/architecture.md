# LendKit — System Architecture

## Overview

LendKit is an open-source infrastructure toolkit for deploying production-grade lending platforms. It provides four independently deployable microservices that handle the complete loan lifecycle — from identity verification to repayment tracking.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          API Gateway / Ingress                       │
│                    (nginx-ingress / Kong / AWS ALB)                  │
└────────┬────────────┬───────────────┬──────────────────┬────────────┘
         │            │               │                  │
    ┌────▼───┐  ┌─────▼──────┐  ┌────▼──────┐  ┌───────▼──────┐
    │  KYC   │  │  Credit    │  │  Loan     │  │  Repayment   │
    │ :8001  │  │ Scoring    │  │Origination│  │   :8004      │
    │        │  │  :8002     │  │  :8003    │  │              │
    └────┬───┘  └─────┬──────┘  └────┬──────┘  └───────┬──────┘
         │            │               │                  │
    ┌────▼────────────▼───────────────▼──────────────────▼────────┐
    │                    Redis Streams / Kafka                      │
    │         (lendkit:kyc:events, lendkit:loan:events, ...)       │
    └───────────────────────────────────────────────────────────────┘
         │            │               │                  │
    ┌────▼───┐  ┌─────▼──────┐  ┌────▼──────┐  ┌───────▼──────┐
    │ kyc DB │  │ credit DB  │  │ loans DB  │  │repayment DB  │
    │(psql)  │  │  (psql)    │  │  (psql)   │  │  (psql)      │
    └────────┘  └────────────┘  └───────────┘  └──────────────┘
```

## Services

### 1. KYC / BIN Verification Service (`:8001`)

The identity verification backbone of the platform. Handles all regulatory compliance requirements before a loan can be issued.

**BIN Lookup** uses a three-tier cache: Redis (hot, 24h TTL) → PostgreSQL (warm) → external API (cold). This keeps external API costs minimal while ensuring near-instant response times for repeat lookups.

**KYC Verification** is provider-agnostic. The `IdentityProvider` interface has implementations for Smile Identity (Africa-focused), Onfido (global), and a deterministic mock for development. Adding a new provider means implementing three methods: `initiate()`, `get_status()`, `handle_webhook()`.

**Async by default.** Identity checks and document extraction are queued via Celery workers so HTTP responses are immediate — the client polls for status changes or receives webhook callbacks.

**Verification levels** let lenders choose the appropriate depth:
- `basic`: Phone + BVN/NIN lookup only
- `standard`: + Government ID document scan
- `enhanced`: + Liveness check + document authenticity scoring

### 2. Credit Scoring Engine (`:8002`)

A pluggable credit decisioning engine that outputs a normalized credit score (300–850) and an `approve | review | decline` decision.

The intended architecture layers three approaches:
- **Hard rules** (implemented first): income floor, blacklist check, employment type constraints
- **Fuzzy logic** (good first issue): membership functions for DTI ratio, employment tenure, repayment history
- **ML overlay** (optional): scikit-learn / XGBoost model loaded from a model registry

The RiskSense/fuzzy logic architecture fits naturally here — fuzzy sets allow nuanced scoring of borderline applicants rather than hard cutoffs.

### 3. Loan Origination Service (`:8003`)

Orchestrates the loan state machine from application to active disbursement. It is intentionally thin — it coordinates the KYC and Credit Scoring services rather than duplicating their logic.

State machine: `draft → kyc_pending → kyc_approved → scoring → underwriting → approved → offer_sent → offer_accepted → disbursing → active`

The disbursement layer is provider-abstracted (Paystack, Flutterwave, Stripe). Mock provider is available for development.

### 4. Repayment & Default Detection Service (`:8004`)

Accepts payment webhooks from providers, allocates payments across penalties → interest → principal, and runs scheduled default detection.

**Payment allocation order** follows standard lending convention: outstanding penalties first, then accrued interest, then principal reduction. This is enforced at the application layer, not the DB layer.

**Default classification**: current → at_risk (approaching due date) → delinquent (1–90 DPD) → default (90+ DPD) → written_off.

Celery beat runs the delinquency scanner hourly. Configurable grace period (default: 3 days) and penalty rate (default: 2% daily) per tenant.

## Data Model

Each service owns its database — no cross-service joins. Services communicate via:
1. **Synchronous HTTP** (within a request, e.g., loan-origination → kyc for status check)
2. **Domain events** via Redis Streams / Kafka (async, e.g., `kyc.approved` triggers credit scoring)

## Event Bus

Events published to Redis Streams (or Kafka topics in production):

| Stream / Topic               | Published By      | Consumed By              |
|------------------------------|-------------------|--------------------------|
| `lendkit:kyc:events`         | KYC service       | Loan origination, Risk   |
| `lendkit:loan:events`        | Loan origination  | Repayment, Notifications |
| `lendkit:repayment:events`   | Repayment service | Risk, Collections        |
| `lendkit:scoring:events`     | Credit scoring    | Loan origination         |

## Security

All service-to-service calls use short-lived JWTs signed with the shared `SECRET_KEY`. In production, replace with mTLS (cert-manager + Istio service mesh) or a dedicated auth service.

Provider webhooks are authenticated via HMAC-SHA256 signature verification — never by IP allowlist alone.

## Deployment Topology

```
Production (Kubernetes):
  - Each service: 2–10 pods (HPA on CPU + memory)
  - Workers: 2–10 pods (KEDA on Redis queue depth)
  - PostgreSQL: Bitnami chart, single primary + read replica
  - Redis: Bitnami chart, standalone (upgrade to Sentinel/Cluster for HA)

Development (Docker Compose):
  - All services on a single host
  - Shared postgres instance, 4 databases
  - Flower UI for Celery monitoring at :5555
```

## Good First Issues

The following areas are explicitly left for community contribution:

- `FuzzyScorer` in credit-scoring (skfuzzy integration)
- `OnfidoProvider` in KYC identity service
- `AmortizationSchedule.generate()` in repayment service
- `PaystackDisbursementService` in loan-origination
- Database migrations (Alembic) for all services
- Prometheus dashboards (Grafana JSON)
- Multi-currency support (amount handling in non-NGN currencies)
