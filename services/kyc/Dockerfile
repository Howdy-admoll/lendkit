# =============================================================================
# LendKit — KYC Service Dockerfile
# Multi-stage: builder (compiles deps) → development → production
# Build tools (gcc, libpq-dev) stay in the builder layer only.
# =============================================================================

# --------------- Builder stage (compile Python packages) ---------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build-time OS deps — NOT copied to production image
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install into an isolated venv so we can copy just the venv to production
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Pin pip to latest to avoid pip CVEs showing up in Trivy scans
RUN pip install "pip>=25.1.1" --upgrade

COPY pyproject.toml ./
# Copy app package so hatchling can resolve the editable install
COPY app/ ./app/

RUN pip install .

# --------------- Development stage (hot-reload, includes dev deps) -----------
FROM python:3.12-slim AS development

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv

# Re-install with dev extras for hot-reload tools
COPY pyproject.toml ./
COPY app/ ./app/
RUN pip install ".[dev]"

COPY . .
EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--reload", "--log-level", "debug"]

# --------------- Production stage (minimal, no build tools) ------------------
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app

# Runtime OS deps only — libpq5 for asyncpg, curl for health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled venv from builder — no gcc or libpq-dev here
COPY --from=builder /venv /venv

# Copy application source
COPY app/ ./app/

# Non-root user
RUN addgroup --system lendkit && adduser --system --ingroup lendkit lendkit
RUN chown -R lendkit:lendkit /app
USER lendkit

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--workers", "4", "--log-level", "info", \
     "--access-log", "--proxy-headers"]
