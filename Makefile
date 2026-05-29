# =============================================================================
# LendKit — Developer Makefile
# =============================================================================
.DEFAULT_GOAL := help
.PHONY: help up down build logs lint test migrate migrate-all seed k8s-apply k8s-delete

SERVICES     ?= kyc credit loan repayment disbursement notification collections
DB_SERVICES  ?= kyc credit loan repayment disbursement notification collections

# Colors
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
CYAN  := \033[36m

help: ## Show this help
	@echo ""
	@echo "$(BOLD)LendKit — Lending Platform Infrastructure$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------
up: ## Start all services in the background
	docker compose up -d --build

up-infra: ## Start only infrastructure (postgres, redis)
	docker compose up -d postgres redis

up-kyc: ## Start KYC service + infra
	docker compose up -d postgres redis kyc

up-scoring: ## Start Credit Scoring service + infra
	docker compose up -d postgres redis credit

up-gateway: ## Start gateway + infra only
	docker compose up -d postgres redis gateway

up-dashboard: ## Start dashboard + gateway + infra
	docker compose up -d postgres redis gateway dashboard

down: ## Stop and remove containers
	docker compose down

down-volumes: ## Stop containers and delete volumes (destructive!)
	docker compose down -v

build: ## Rebuild all service images
	docker compose build --no-cache

logs: ## Tail logs for all services
	docker compose logs -f --tail=100

logs-kyc: ## Tail KYC service logs
	docker compose logs -f kyc worker-kyc

restart: ## Restart all services
	docker compose restart

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
migrate: ## Run Alembic migrations for all services
	@for svc in $(DB_SERVICES); do \
		echo "$(GREEN)>>> Running migrations: $$svc$(RESET)"; \
		docker compose exec $$svc alembic upgrade head; \
	done

migrate-all: migrate ## Alias for migrate (run all service migrations)

migrate-kyc: ## Run KYC migrations only
	docker compose exec kyc alembic upgrade head

rollback-kyc: ## Rollback last KYC migration
	docker compose exec kyc alembic downgrade -1

seed: ## Seed development databases
	docker compose exec kyc python -m app.db.seed

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test: ## Run all tests
	@for svc in $(SERVICES); do \
		echo "$(GREEN)>>> Testing: $$svc$(RESET)"; \
		docker compose exec $$svc pytest tests/ -v --tb=short; \
	done

test-kyc: ## Run KYC tests only
	docker compose exec kyc pytest tests/ -v --tb=short --cov=app --cov-report=term-missing

test-kyc-unit: ## Run KYC unit tests (no DB)
	docker compose exec kyc pytest tests/unit/ -v --tb=short

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------
lint: ## Lint all services
	@for svc in $(SERVICES); do \
		echo "$(GREEN)>>> Linting: $$svc$(RESET)"; \
		docker compose exec $$svc ruff check app/ && \
		docker compose exec $$svc mypy app/ --ignore-missing-imports; \
	done

format: ## Auto-format all services with ruff
	@for svc in $(SERVICES); do \
		docker compose exec $$svc ruff format app/; \
	done

# ---------------------------------------------------------------------------
# Kubernetes
# ---------------------------------------------------------------------------
k8s-namespace: ## Create lendkit namespace
	kubectl apply -f infra/k8s/namespace.yaml

k8s-apply: ## Apply all K8s manifests
	kubectl apply -f infra/k8s/

k8s-apply-kyc: ## Apply KYC K8s manifests
	kubectl apply -f infra/k8s/kyc/

k8s-delete: ## Delete all K8s resources (destructive!)
	kubectl delete -f infra/k8s/

k8s-status: ## Show pod status in lendkit namespace
	kubectl get pods -n lendkit -o wide

k8s-logs-kyc: ## Stream KYC pod logs
	kubectl logs -n lendkit -l app=kyc -f --tail=100

# ---------------------------------------------------------------------------
# Helm
# ---------------------------------------------------------------------------
helm-deps: ## Update Helm chart dependencies
	helm dependency update infra/helm/lendkit

helm-lint: ## Lint the Helm chart
	helm lint infra/helm/lendkit

helm-dry-run: ## Dry-run Helm install
	helm install lendkit infra/helm/lendkit --dry-run --debug

helm-install: ## Install lendkit via Helm
	helm install lendkit infra/helm/lendkit \
		--namespace lendkit --create-namespace \
		--values infra/helm/lendkit/values.yaml

helm-upgrade: ## Upgrade existing Helm release
	helm upgrade lendkit infra/helm/lendkit \
		--namespace lendkit \
		--values infra/helm/lendkit/values.yaml

helm-uninstall: ## Uninstall Helm release
	helm uninstall lendkit --namespace lendkit

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
shell-kyc: ## Open shell in KYC container
	docker compose exec kyc bash

shell-db: ## Open psql shell
	docker compose exec postgres psql -U lendkit -d kyc

generate-secret: ## Generate a secure SECRET_KEY
	@python3 -c "import secrets; print(secrets.token_hex(32))"

check-env: ## Validate .env file exists
	@test -f .env || (echo "ERROR: .env not found. Run: cp .env.example .env" && exit 1)
	@echo "$(GREEN).env file found$(RESET)"
