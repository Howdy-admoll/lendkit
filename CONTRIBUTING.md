# Contributing to LendKit

First off — thank you for taking the time to contribute. LendKit is an open community and every contribution matters, from fixing a typo to implementing a full disbursement provider.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Good First Issues](#good-first-issues)
- [Architecture Decisions](#architecture-decisions)

---

## Code of Conduct

This project follows our [Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to uphold it.

---

## How to Contribute

### Reporting Bugs

Open a GitHub issue using the **Bug Report** template. Include:
- Steps to reproduce
- Expected vs actual behavior
- Service name and version (`GET /health`)
- Relevant logs (sanitize any secrets/PII)

### Suggesting Features

Open a GitHub issue using the **Feature Request** template. Describe the problem you're solving, not just the solution.

### Submitting Code

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/paystack-disbursement`
3. Make your changes
4. Write or update tests
5. Open a Pull Request

---

## Development Setup

```bash
# Prerequisites: Docker, Python 3.12+, make

git clone https://github.com/Howdy-admoll/lendkit.git
cd lendkit
cp .env.example .env          # configure your local env
make up-kyc                   # start KYC service + postgres + redis
make migrate-kyc              # run database migrations
make test-kyc                 # run tests
```

All services run in Docker. You rarely need to install Python packages on your host — use `make shell-kyc` to get a shell inside the container.

---

## Pull Request Process

1. **One concern per PR.** Don't bundle unrelated changes.
2. **Tests are required.** New features need tests; bug fixes need a regression test.
3. **Keep it green.** CI must pass: lint, tests, Docker build.
4. **Update docs** if you change behavior, add a config variable, or add an endpoint.
5. **PR title format:** `feat: add Paystack disbursement provider` / `fix: BIN cache TTL off-by-one` / `docs: add repayment runbook`

### Branch naming

| Prefix | Use for |
|---|---|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `refactor/` | Refactoring (no behavior change) |
| `chore/` | Build, CI, dependencies |
| `test/` | Tests only |

---

## Good First Issues

These are explicitly scoped for first-time contributors:

| Issue | Service | Skill needed |
|---|---|---|
| Implement `FuzzyScorer` with `skfuzzy` | credit-scoring | Python, fuzzy logic |
| Add `OnfidoProvider` identity integration | kyc | Python, REST APIs |
| Implement `AmortizationSchedule.generate()` | repayment | Python, financial math |
| Add `PaystackDisbursementService` | loan-origination | Python, REST APIs |
| Write Alembic migrations for all services | all | SQLAlchemy, Alembic |
| Add Grafana dashboard JSON for KYC metrics | infra | Grafana, Prometheus |
| Add multi-currency support (USD, KES, GHS) | all | Python |
| Write integration tests with a real Redis | kyc | pytest, Redis |

Look for issues tagged `good first issue` on GitHub.

---

## Architecture Decisions

Before making significant design changes, read `docs/architecture.md`.

Key invariants that should not change without a discussion issue first:
- Services must not share a database — each owns its schema
- Cross-service calls go through HTTP or the event bus — never direct DB access
- All provider integrations must implement the abstract base class (pluggable pattern)
- Sensitive data (API keys, card numbers) must never be logged — use masking helpers in `shared/utils/`

---

## Code Style

We use **ruff** for linting and formatting, and **mypy** for type checking.

```bash
make format   # auto-format
make lint     # lint + type check
```

Line length: 100. Type annotations required on all public functions.

---

## Questions?

Open a [Discussion](https://github.com/Howdy-admoll/lendkit/discussions) on GitHub. We're friendly.
