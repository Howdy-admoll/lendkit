<div align="center">

# LendKit

**Open-source lending platform infrastructure**

[![CI](https://github.com/Howdy-admoll/lendkit/actions/workflows/ci.yml/badge.svg)](https://github.com/Howdy-admoll/lendkit/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://hub.docker.com)
[![Kubernetes](https://img.shields.io/badge/kubernetes-helm-326CE5.svg)](https://helm.sh)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Production-grade microservices covering the full loan lifecycle — from identity verification and credit decisioning through disbursement, repayment, collections, and a unified API Gateway.

[Quickstart](#quickstart) · [Architecture](#architecture) · [Services](#services) · [Roadmap](#roadmap) · [Contributing](#contributing)

</div>

---

## What is LendKit?

LendKit is a collection of independently deployable microservices that cover the full loan lifecycle — from identity verification to default detection and collections. It is designed to be:

- **Self-hostable** — deploy on any Kubernetes cluster or with Docker Compose in minutes
- **Provider-agnostic** — swap identity providers, payment gateways, and cloud services without touching your business logic
- **Production-ready** — async by default, structured logging, Prometheus metrics, multi-stage Docker builds, zero-downtime deploys
- **Africa-first, globally applicable** — built with BVN, NIN, NUBAN, and Naira/Kobo in mind; easily extended for other markets
- **Auditable by design** — crisp rule-based credit scoring (not fuzzy logic) so every decision can be explained to a customer or regulator in plain language

---

## Services

| Service | Port | Status | Tests | Description |
|---|---|---|---|---|
| **API Gateway** | `:8000` | ✅ Production-ready | ✓ 55 passing | JWT auth, rate limiting, reverse proxy to all services |
| **KYC** | `:8001` | ✅ Production-ready | ✓ Full suite | Identity verification, BVN/NIN, document OCR, liveness |
| **Credit Scoring** | `:8002` | ✅ Production-ready | ✓ 43 passing | 10-rule scoring engine, tier classification, PEP screening |
| **Loan Origination** | `:8003` | ✅ Production-ready | ✓ 25 passing | Underwriting, DTI guard, 9-state loan lifecycle, offer management |
| **Repayment Tracking** | `:8004` | ✅ Production-ready | ✓ 66 passing | Amortization schedule, payment allocation, delinquency & default detection |
| **Disbursement** | `:8005` | ✅ Production-ready | ✓ 62 passing | Paystack payout, idempotent state machine, HMAC-SHA512 webhooks |
| **Notifications** | `:8006` | ✅ Production-ready | ✓ 80 passing | Termii SMS + SendGrid email, 6 event types, opt-out support |
| **Collections** | `:8007` | ✅ Production-ready | ✓ 77 passing | Escalation ladder, agent queue, promise-to-pay, legal referral, write-off |
| **Dashboard** | `:3000` | ✅ Production-ready | — | React + Vite admin UI — portfolio overview, loan pipeline, collections queue, borrower profiles |

---

## Quickstart

**Requirements:** Docker 24+, `make`

```bash
# 1. Clone
git clone https://github.com/Howdy-admoll/lendkit.git
cd lendkit

# 2. Configure
cp .env.example .env
# Set at minimum: SECRET_KEY (run `make generate-secret` to generate one)

# 3. Start all services
make up

# 4. Run migrations
make migrate-all

# 5. Verify each service
curl http://localhost:8001/health   # KYC
curl http://localhost:8002/health   # Credit Scoring
curl http://localhost:8003/health   # Loan Origination
curl http://localhost:8004/health   # Repayment

# 6. Open API docs (any service)
open http://localhost:8003/docs
```

Start individual services:
```bash
make up-kyc        # KYC + postgres + redis only
make up-scoring    # Credit Scoring only
make logs          # tail all logs
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        API Gateway / Ingress                        │
└──────┬──────────────┬─────────────────┬─────────────────┬───────────┘
       │              │                 │                 │
  ┌────▼───┐  ┌───────▼──────┐  ┌───────▼─────┐  ┌────────▼────┐
  │  KYC   │  │    Credit    │  │    Loan     │  │  Repayment  │
  │ :8001  │  │   Scoring    │  │ Origination │  │   :8004     │
  │        │  │    :8002     │  │    :8003    │  │             │
  └────┬───┘  └───────┬──────┘  └──────┬──────┘  └──────┬──────┘
       └──────────────┴────────────────┴────────────────┘
                                │
                     Redis Streams (domain events)
                     kyc.events · loan.events · repayment.events
```

Each service owns its own PostgreSQL database — no shared schema. Services communicate via HTTP for synchronous calls (origination → scoring) and Redis Streams for async domain events (e.g. `loan.disbursed` triggers repayment service to create the loan account).

---

## Loan Lifecycle

A complete end-to-end flow through all four services:

```
Customer applies
      │
      ▼
KYC Service (:8001)
  BVN/NIN lookup → document verification → liveness check
  Emits: kyc.verified
      │
      ▼
Credit Scoring (:8002)
  Scores 10 rules → weighted aggregate → tier assignment
  Tiers: excellent (≥750) · good (≥650) · fair (≥550) · poor/very_poor → declined
  Emits: score.computed
      │
      ▼
Loan Origination (:8003)
  Underwriting: tier check → amount cap → tenure cap → DTI guard (40% limit)
  9-state machine: DRAFT → UNDERWRITING → APPROVED → OFFER_SENT →
    OFFER_ACCEPTED → DISBURSING → ACTIVE | REJECTED | CANCELLED
  Emits: loan.offer_accepted
      │
      ▼
Repayment Tracking (:8004)
  Generates amortization schedule (reducing-balance, ceil-rounded)
  Applies payments: penalty → interest → principal
  Delinquency: 0 DPD=CURRENT · 1-7=AT_RISK · 8-89=DELINQUENT · 90+=DEFAULT
  Hourly sweep updates DPD, accrues daily penalty (0.1%/day)
```

---

## Credit Scoring — How It Works

LendKit uses **crisp rule-based scoring** — not fuzzy logic. Each rule maps a metric to a fixed point value via hard brackets. This was a deliberate design choice: crisp rules are auditable, testable, and straightforward to explain to regulators and customers in dispute resolution.

| Rule | Max Points | What It Measures |
|---|---|---|
| On-time repayment rate | 8 | % of historical payments made on time |
| Outstanding debt ratio | 7 | Current debt relative to income |
| Credit utilisation | 6 | % of available credit in use |
| Income stability | 6 | Employment type and tenure |
| Loan tenure fit | 5 | Alignment of requested tenure with income cycle |
| Account age | 5 | Length of credit history |
| Inquiry frequency | 4 | Recent hard credit checks |
| Derogatory marks | 4 | Defaults, write-offs on record |
| Loan diversity | 4 | Mix of credit product types |
| **PEP flag** | **−20 penalty** | Politically Exposed Person screening |

Final score → tier → APR and loan limits applied in origination.

---

## Underwriting Engine

The underwriting engine runs four sequential checks, capping or adjusting the proposal rather than binary-rejecting where possible:

1. **Tier eligibility** — `poor` and `very_poor` tiers are declined outright
2. **Amount cap** — approved amount is capped at the tier maximum
3. **Tenure cap** — capped at tier maximum months
4. **DTI guard** — if monthly repayment would exceed 40% of stated income, the loan amount is back-calculated to the maximum the borrower can actually afford rather than declining outright

| Tier | Max Loan | Max Tenure | APR |
|---|---|---|---|
| Excellent (≥750) | ₦5,000,000 | 36 months | 18% |
| Good (≥650) | ₦2,000,000 | 24 months | 24% |
| Fair (≥550) | ₦500,000 | 12 months | 36% |

---

## Repayment & Default Detection

**Amortization schedule** — generated at disbursement using the standard reducing-balance formula (`P × r × (1+r)^n / ((1+r)^n − 1)`), always rounded up (lender-safe). Month-end date clamping handles Jan 31 → Feb 28/29 correctly. The final installment absorbs any accumulated rounding drift so the schedule zeroes out exactly.

**Payment allocation** — each payment is split in strict priority order:
1. Accrued penalties (highest priority — lender recoup)
2. Accrued interest
3. Outstanding principal

**Delinquency classification** — CBN-aligned thresholds, configurable per tenant:

| DPD | Status | Action |
|---|---|---|
| 0 | CURRENT | None |
| 1–7 | AT_RISK | Grace period — no penalty clock |
| 8–89 | DELINQUENT | 0.1%/day penalty, collections engaged |
| 90+ | DEFAULT | Recovery escalation |
| 360+ | WRITTEN_OFF | Balance write-off candidate |

An hourly background sweep (`delinquency_worker`) updates DPD across all active loan accounts and accrues daily penalties.

---

## KYC Service — Deep Dive

**BIN Lookup (3-tier cache)**
```
Request → Redis (hot, 24h TTL) → PostgreSQL (warm) → External API (cold)
```
Keeps external API costs near zero for repeat BINs.

**KYC Verification Levels**
- `basic` — BVN/NIN phone lookup
- `standard` — + government ID document scan
- `enhanced` — + liveness check + document authenticity scoring

**Pluggable providers**
```python
# Switch provider in .env — no code changes needed
IDENTITY_PROVIDER=smile_id   # Smile Identity (default for Africa)
IDENTITY_PROVIDER=onfido     # Onfido (global)
IDENTITY_PROVIDER=mock       # Deterministic mock for dev/CI
```

**Async by default** — identity checks and document OCR are queued via Celery. HTTP responses are immediate; status is polled or delivered via webhook.

---

## Configuration

Copy `.env.example` to `.env`. Key variables:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ | JWT signing key — generate with `make generate-secret` |
| `IDENTITY_PROVIDER` | | `smile_id` / `onfido` / `mock` (default: `mock`) |
| `IDENTITY_API_KEY` | Prod | Your identity provider API key |
| `DOCUMENT_PROVIDER` | | `aws_textract` / `mock` (default: `mock`) |
| `EVENT_BACKEND` | | `redis` / `kafka` (default: `redis`) |
| `PAYSTACK_SECRET` | Prod | Paystack webhook secret (repayment service) |
| `FLUTTERWAVE_SECRET` | Prod | Flutterwave webhook secret (repayment service) |

See `.env.example` for the complete reference.

---

## Running Tests

Each service's engine tests are pure Python — no database or HTTP calls needed:

```bash
# Individual services
cd services/credit-scoring  && pytest tests/ -v   # 43 tests
cd services/loan-origination && pytest tests/ -v  # 25 tests
cd services/repayment        && pytest tests/ -v  # 66 tests

# Or push and let CI run everything
git push   # GitHub Actions runs all suites, Docker builds, and security scan
```

---

## Deployment

### Docker Compose (local / staging)
```bash
make up           # full stack
make down         # stop
make down-volumes # stop + delete all data
```

### Kubernetes (production)
```bash
kubectl apply -f infra/k8s/

# Or use Helm
helm install lendkit infra/helm/lendkit \
  --namespace lendkit --create-namespace \
  --values infra/helm/lendkit/values.yaml
```

---

## Roadmap

### ✅ Phase 1 — Core Lending Pipeline (complete)
- [x] KYC service — identity verification, BVN/NIN, document OCR, liveness
- [x] Credit scoring — 10-rule crisp engine, PEP screening, tier classification (43 tests)
- [x] Loan origination — underwriting engine, DTI guard, 9-state lifecycle, offer management (25 tests)
- [x] Repayment tracking — amortization schedule, payment allocation, delinquency & default detection (66 tests)
- [x] CI pipeline — lint, unit tests per service, Docker build, Trivy security scan, GHCR publish

### ✅ Phase 2 — Money Movement & Communications (complete)
- [x] Disbursement service — Paystack payout, idempotent state machine, HMAC-SHA512 webhooks, retry with backoff (62 tests)
- [x] Notification service — Termii SMS + SendGrid email, 6 event types, opt-out preferences, idempotent delivery (80 tests)
- [x] Collections service — DPD escalation ladder, agent assignment queue, promise-to-pay tracking, legal referral, write-off (77 tests)

### 🔜 Phase 3 — Platform & Operations
- [x] API Gateway — JWT auth (HS256), per-IP + per-tenant rate limiting, reverse proxy, request tracing (55 tests)
- [x] Docker Compose — single `docker compose up --build` starts all 8 services + Postgres 16 + Redis 7
- [x] Integration tests — full loan lifecycle test suite (KYC → score → originate → disburse → repay → collect)
- [x] Admin dashboard — React + Vite SPA (portfolio overview, loan pipeline, collections queue, borrower profiles) served via nginx on :3000
- [ ] Reporting & analytics — portfolio health, NPL ratios, disbursement volumes, cohort analysis
- [ ] Tenant management — per-tenant APR, DPD thresholds, grace period, feature flags
- [ ] Webhook relay — signed outbound webhooks to tenant systems with retry backoff

### 📋 Phase 4 — Infrastructure
- [ ] Complete Kubernetes manifests — HPA, resource limits, secrets management, ingress
- [ ] Observability stack — Prometheus metrics, Grafana dashboards, Loki log aggregation
- [ ] Helm chart — single `helm install` for the full LendKit stack
- [ ] CD pipeline — GitHub Actions → GHCR → k8s rolling deploy with smoke tests and auto-rollback
- [ ] Multi-currency support (USD, KES, GHS, ZAR)

---

## Contributing

We welcome contributions of all sizes. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, PR guidelines, and good first issues.

Key areas actively looking for contributors:
- `PaystackDisbursementService` — upcoming disbursement service (Python + REST)
- `OnfidoProvider` — KYC integration (Python + REST)
- Grafana dashboard JSON for loan and repayment metrics
- Helm chart authoring
- Multi-currency support (USD, KES, GHS, ZAR)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

<div align="center">
Built with care for the fintech infrastructure community.
</div>
