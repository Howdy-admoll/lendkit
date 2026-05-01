<div align="center">

# LendKit

**Open-source lending platform infrastructure**

[![CI](https://github.com/your-org/lendkit/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/lendkit/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://hub.docker.com)
[![Kubernetes](https://img.shields.io/badge/kubernetes-helm-326CE5.svg)](https://helm.sh)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Production-grade playbooks for deploying credit decisioning systems, loan origination workflows, and risk management infrastructure.

[Quickstart](#quickstart) · [Architecture](#architecture) · [Services](#services) · [Roadmap](#roadmap) · [Contributing](#contributing)

</div>

---

## What is LendKit?

LendKit is a collection of independently deployable microservices that cover the full loan lifecycle — from identity verification to default detection. It is designed to be:

- **Self-hostable** — deploy on any Kubernetes cluster or with Docker Compose in minutes
- **Provider-agnostic** — swap identity providers, payment gateways, and cloud services without touching your business logic
- **Production-ready** — async by default, structured logging, Prometheus metrics, OpenTelemetry tracing, HPA, zero-downtime deploys
- **Africa-first, globally applicable** — built with BVN, NIN, NUBAN, and Naira/Kobo in mind; easily extended for other markets

---

## Services

| Service | Port | Status | Description |
|---|---|---|---|
| **KYC / BIN** | `:8001` | ✅ Implemented | Identity verification, BIN lookup, document OCR |
| **Credit Scoring** | `:8002` | 🚧 Scaffold | Fuzzy logic + rule-based credit decisioning |
| **Loan Origination** | `:8003` | 🚧 Scaffold | Application → approval → disbursement pipeline |
| **Repayment** | `:8004` | 🚧 Scaffold | Repayment tracking, delinquency, default detection |

---

## Quickstart

**Requirements:** Docker 24+, `make`

```bash
# 1. Clone
git clone https://github.com/your-org/lendkit.git
cd lendkit

# 2. Configure
cp .env.example .env
# Set at minimum: SECRET_KEY (run `make generate-secret` to generate one)

# 3. Start KYC + infrastructure
make up-kyc

# 4. Run migrations
make migrate-kyc

# 5. Verify
curl http://localhost:8001/health
# {"status": "healthy", "service": "kyc", "version": "0.1.0"}

# 6. Open API docs
open http://localhost:8001/docs
```

Start all services:
```bash
make up          # all 4 services + postgres + redis + celery workers
make logs        # tail all logs
open http://localhost:5555   # Flower (Celery monitoring)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          API Gateway / Ingress                       │
└────────┬────────────┬───────────────┬──────────────────┬────────────┘
         │            │               │                  │
    ┌────▼───┐  ┌─────▼──────┐  ┌────▼──────┐  ┌───────▼──────┐
    │  KYC   │  │  Credit    │  │  Loan     │  │  Repayment   │
    │ :8001  │  │ Scoring    │  │Origination│  │   :8004      │
    └────┬───┘  └─────┬──────┘  └────┬──────┘  └───────┬──────┘
         └────────────┴───────────────┴──────────────────┘
                              │
                   Redis Streams / Kafka
                   (domain events bus)
```

Each service owns its PostgreSQL database. Services communicate via HTTP (sync) and Redis Streams/Kafka events (async). Read the full [architecture doc](docs/architecture.md).

---

## KYC Service — Deep Dive

The most complete service. Features:

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

**Async by default**

Identity checks and document OCR are queued via Celery — HTTP responses are immediate, status is polled or delivered via webhook.

---

## Configuration

Copy `.env.example` to `.env`. Key variables:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ | JWT signing key — generate with `make generate-secret` |
| `IDENTITY_PROVIDER` | | `smile_id` / `onfido` / `mock` (default: `mock`) |
| `IDENTITY_API_KEY` | Prod | Your provider API key |
| `DOCUMENT_PROVIDER` | | `aws_textract` / `mock` (default: `mock`) |
| `BIN_API_KEY` | | BIN lookup API key (optional, works without one) |
| `EVENT_BACKEND` | | `redis` / `kafka` (default: `redis`) |

See `.env.example` for the complete reference.

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
# Apply manifests directly
kubectl apply -f infra/k8s/

# Or use Helm
helm install lendkit infra/helm/lendkit \
  --namespace lendkit --create-namespace \
  --values infra/helm/lendkit/values.yaml
```

See the [KYC Deployment Playbook](docs/playbooks/kyc-deployment.md) for a full production runbook including scaling guidelines, monitoring setup, and incident response runbooks.

---

## Roadmap

### v0.2 — Credit Scoring Engine
- [ ] `FuzzyScorer` implementation with `skfuzzy` (fuzzy logic membership functions)
- [ ] Hard policy rules engine (income floor, blacklist, DTI cutoffs)
- [ ] Bureau score integration (CRC, First Central)
- [ ] Alembic migrations for all services

### v0.3 — Loan Origination
- [ ] Paystack disbursement provider
- [ ] Flutterwave disbursement provider
- [ ] Loan offer generation and acceptance flow
- [ ] Automated underwriting rules

### v0.4 — Repayment & Collections
- [ ] Amortization schedule generation
- [ ] Direct debit mandate management
- [ ] Collections workflow triggers
- [ ] Delinquency cohort reporting

### v0.5 — Observability & Multi-tenancy
- [ ] Grafana dashboards (KYC, Loan, Repayment)
- [ ] Per-tenant configuration and rate limits
- [ ] Multi-currency support (USD, KES, GHS, ZAR)
- [ ] KEDA-based worker autoscaling

---

## Contributing

We welcome contributions of all sizes. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, PR guidelines, and a list of **good first issues** explicitly scoped for new contributors.

Key areas looking for contributors:
- `FuzzyScorer` in credit-scoring (Python + skfuzzy)
- `OnfidoProvider` in KYC (Python + REST)
- `PaystackDisbursementService` (Python + REST)
- `AmortizationSchedule.generate()` (financial math)
- Grafana dashboard JSON

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

<div align="center">
Built with care for the fintech infrastructure community.
</div>
