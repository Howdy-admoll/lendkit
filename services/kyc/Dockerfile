# =============================================================================
# LendKit — KYC Service Dockerfile
# Multi-stage: development (hot-reload) + production (optimized)
# =============================================================================

# --------------- Base stage ------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

# --------------- Development stage (hot-reload) ----------------------------
FROM base AS development

COPY . .
EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload", "--log-level", "debug"]

# --------------- Production stage ------------------------------------------
FROM base AS production

COPY . .

# Non-root user for production
RUN addgroup --system lendkit && adduser --system --group lendkit
RUN chown -R lendkit:lendkit /app
USER lendkit

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--workers", "4", "--log-level", "info", \
     "--access-log", "--proxy-headers"]
