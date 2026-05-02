"""
LendKit — KYC / BIN Verification Service

Entry point for the FastAPI application.
"""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.api.routes import bin as bin_router
from app.api.routes import kyc as kyc_router
from app.core.config import settings
from app.db.session import close_engine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
        if not settings.is_development
        else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    "lendkit_kyc_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_DURATION = Histogram(
    "lendkit_kyc_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("KYC service starting", env=settings.app_env, port=settings.service_port)

    if settings.otel_enabled:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource(attributes={SERVICE_NAME: settings.otel_service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
        trace.set_tracer_provider(provider)
        log.info("OpenTelemetry tracing enabled")

    yield

    log.info("KYC service shutting down")
    await close_engine()


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LendKit KYC Service",
    description="""
## KYC / BIN Verification Microservice

Part of the **LendKit** open-source lending platform infrastructure.

### Features
- **BIN Lookup** — 3-tier cached lookup (Redis → DB → external API)
- **KYC Initiation** — Supports basic, standard, and enhanced verification levels
- **Document Verification** — Multipart upload with OCR extraction
- **Provider Abstraction** — Pluggable identity providers (Smile ID, Onfido, mock)
- **Async Processing** — Celery workers for long-running verification tasks
- **Domain Events** — Redis Streams / Kafka event publishing

### Authentication
All endpoints require a `Bearer` JWT in the `Authorization` header.
Obtain tokens from your auth service using the shared `SECRET_KEY`.
    """,
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    endpoint = request.url.path
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status_code=response.status_code,
    ).inc()
    REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(duration)

    response.headers["X-Request-Duration"] = f"{duration:.4f}s"
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(kyc_router.router, prefix="/api/v1")
app.include_router(bin_router.router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["System"], summary="Health check")
async def health() -> dict:
    return {
        "status": "healthy",
        "service": "kyc",
        "version": "0.1.0",
        "environment": settings.app_env,
    }


@app.get("/metrics", tags=["System"], include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": "lendkit-kyc", "docs": "/docs"}
