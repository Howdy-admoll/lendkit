# KYC Service — Deployment & Operations Playbook

## Prerequisites

- Docker 24+ / Kubernetes 1.28+
- Helm 3.14+
- PostgreSQL 16 (or use bundled chart)
- Redis 7 (or use bundled chart)
- kubectl configured for your target cluster

---

## Local Development Quickstart

```bash
# 1. Clone and configure
git clone https://github.com/Howdy-admoll/lendkit.git
cd lendkit
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY and identity provider credentials

# 2. Start infrastructure + KYC service
make up-kyc

# 3. Run database migrations
make migrate-kyc

# 4. Verify the service
curl http://localhost:8001/health
# → {"status": "healthy", "service": "kyc", "version": "0.1.0", "environment": "development"}

# 5. Access API docs
open http://localhost:8001/docs
```

---

## Production Deployment (Kubernetes + Helm)

### Step 1 — Build and push images

```bash
docker build -t ghcr.io/your-org/lendkit-kyc:0.1.0 \
  --target production \
  services/kyc/

docker push ghcr.io/your-org/lendkit-kyc:0.1.0
```

### Step 2 — Create namespace and secrets

```bash
kubectl apply -f infra/k8s/namespace.yaml

# Create secrets (never commit these values)
kubectl create secret generic kyc-secrets \
  --namespace lendkit \
  --from-literal=SECRET_KEY=$(make generate-secret) \
  --from-literal=DB_URL="postgresql+asyncpg://lendkit:YOURPASS@postgres:5432/kyc" \
  --from-literal=REDIS_URL="redis://redis:6379/0" \
  --from-literal=IDENTITY_API_KEY="your-smile-id-key" \
  --from-literal=AWS_ACCESS_KEY_ID="your-aws-key" \
  --from-literal=AWS_SECRET_ACCESS_KEY="your-aws-secret"
```

### Step 3 — Deploy with Helm

```bash
helm dependency update infra/helm/lendkit

helm install lendkit infra/helm/lendkit \
  --namespace lendkit \
  --values infra/helm/lendkit/values.yaml \
  --set kyc.image.tag=0.1.0 \
  --set postgresql.auth.password=YOURPASS

# Watch rollout
kubectl rollout status deployment/lendkit-kyc -n lendkit
```

### Step 4 — Run migrations

```bash
# Get the kyc pod name
KYC_POD=$(kubectl get pods -n lendkit -l app=lendkit-kyc -o jsonpath='{.items[0].metadata.name}')

# Run Alembic migrations
kubectl exec -n lendkit $KYC_POD -- alembic upgrade head
```

### Step 5 — Verify deployment

```bash
# Check pod health
kubectl get pods -n lendkit -l app=lendkit-kyc

# Check logs
kubectl logs -n lendkit -l app=lendkit-kyc --tail=50

# Port-forward for local testing
kubectl port-forward -n lendkit svc/lendkit-kyc 8001:80

# Test health endpoint
curl http://localhost:8001/health
```

---

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | ✅ | — | JWT signing key (min 32 chars) |
| `DB_URL` | ✅ | — | AsyncPG connection string |
| `REDIS_URL` | ✅ | — | Redis connection string |
| `IDENTITY_PROVIDER` | | `mock` | `smile_id` \| `onfido` \| `mock` |
| `IDENTITY_API_KEY` | ✅ prod | — | Provider API key |
| `DOCUMENT_PROVIDER` | | `mock` | `aws_textract` \| `mock` |
| `BIN_API_KEY` | | — | BIN lookup API key (optional) |
| `BIN_CACHE_TTL` | | `86400` | BIN cache TTL in seconds |
| `OTEL_ENABLED` | | `false` | Enable OpenTelemetry tracing |

---

## Scaling Guidelines

The KYC service has two workload types with different scaling characteristics:

**API pods** scale on CPU. Each pod handles ~500 concurrent requests at the default 512Mi memory limit. Enable HPA (bundled in `infra/k8s/kyc/hpa.yaml`).

**Celery workers** scale on queue depth. Install KEDA for queue-aware autoscaling (see commented config in `hpa.yaml`). Without KEDA, scale manually by adjusting `worker.replicaCount` in values.

---

## Runbooks

### RUN-01: KYC service is returning 503

```bash
# Check pod status
kubectl get pods -n lendkit -l app=lendkit-kyc

# Check recent events
kubectl describe deployment lendkit-kyc -n lendkit | tail -20

# Check DB connectivity from the pod
KYC_POD=$(kubectl get pods -n lendkit -l app=lendkit-kyc -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n lendkit $KYC_POD -- python -c "
import asyncio, asyncpg, os
async def check():
    conn = await asyncpg.connect(os.environ['DB_URL'].replace('+asyncpg',''))
    print('DB OK:', await conn.fetchval('SELECT 1'))
asyncio.run(check())
"
```

### RUN-02: Identity provider returning failures

```bash
# Check worker logs for provider errors
kubectl logs -n lendkit -l app=lendkit-kyc-worker --tail=100 | grep -i "error\|provider"

# Switch to mock provider temporarily (zero-downtime)
kubectl set env deployment/lendkit-kyc -n lendkit IDENTITY_PROVIDER=mock
kubectl rollout status deployment/lendkit-kyc -n lendkit

# Restore when provider is back
kubectl set env deployment/lendkit-kyc -n lendkit IDENTITY_PROVIDER=smile_id
```

### RUN-03: KYC queue backing up (worker lag)

```bash
# Check queue depth
redis-cli -h $REDIS_HOST xlen lendkit:kyc:events

# Scale up workers
kubectl scale deployment lendkit-kyc-worker --replicas=5 -n lendkit

# Monitor queue drain
watch redis-cli -h $REDIS_HOST xlen lendkit:kyc:events
```

### RUN-04: Rollback to previous version

```bash
# Via Helm
helm rollback lendkit -n lendkit

# Via kubectl
kubectl rollout undo deployment/lendkit-kyc -n lendkit
kubectl rollout undo deployment/lendkit-kyc-worker -n lendkit

# Verify
kubectl rollout status deployment/lendkit-kyc -n lendkit
```

### RUN-05: Expire stale KYC records manually

```bash
KYC_POD=$(kubectl get pods -n lendkit -l app=lendkit-kyc -o jsonpath='{.items[0].metadata.name}')

# Trigger the expiry task manually
kubectl exec -n lendkit $KYC_POD -- \
  celery -A app.workers.kyc_tasks call kyc.expire_stale_kyc
```

---

## Monitoring

Key metrics exposed at `/metrics` (Prometheus format):

| Metric | Alert Threshold | Description |
|---|---|---|
| `lendkit_kyc_requests_total{status_code="5xx"}` | > 1% of requests | Error rate |
| `lendkit_kyc_request_duration_seconds{p99}` | > 2s | Latency p99 |
| `celery_tasks_total{state="failure"}` | > 5/min | Worker failures |
| `pg_stat_activity_count` | > 90% pool | DB connection saturation |

Import the bundled Grafana dashboard from `infra/grafana/kyc-dashboard.json` (TODO).

---

## Security Checklist

Before going to production:

- [ ] Rotate `SECRET_KEY` — use `make generate-secret`
- [ ] Store all secrets in Kubernetes Secrets or a secrets manager (Vault, AWS SSM)
- [ ] Disable Swagger UI (`/docs`, `/redoc`) — set `APP_ENV=production`
- [ ] Enable OTEL tracing and connect to Jaeger/Tempo
- [ ] Configure network policies to restrict pod-to-pod traffic
- [ ] Enable pod disruption budgets (PDB) for zero-downtime maintenance
- [ ] Review HMAC verification in webhook handler
- [ ] Encrypt PostgreSQL at rest (enable `pg_encrypt` or use managed RDS)
- [ ] Enable Redis AUTH or TLS for Redis connections
- [ ] Run `docker scout cves` on the built image before deploy
