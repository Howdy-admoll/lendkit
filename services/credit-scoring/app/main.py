"""
LendKit — Credit Scoring Service

Rule-based credit scoring engine that consumes KYC events and provides
loan decisioning signals for the loan origination service.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.api.routes.scores import customer_router
from app.api.routes.scores import router as scores_router
from app.core.config import settings
from app.db.session import close_engine
from app.workers.kyc_consumer import KYCEventConsumer

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
    "lendkit_credit_scoring_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_DURATION = Histogram(
    "lendkit_credit_scoring_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
)

# ---------------------------------------------------------------------------
# KYC consumer background task
# ---------------------------------------------------------------------------

_kyc_consumer: KYCEventConsumer | None = None
_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _kyc_consumer, _consumer_task

    log.info(
        "credit_scoring.starting",
        env=settings.app_env,
        port=settings.service_port,
    )

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
        log.info("otel.tracing_enabled")

    # Start the KYC event consumer in the background
    _kyc_consumer = KYCEventConsumer()
    _consumer_task = asyncio.create_task(_kyc_consumer.run(), name="kyc-event-consumer")
    log.info("kyc_consumer.task_started")

    yield

    # Graceful shutdown
    log.info("credit_scoring.shutting_down")
    if _kyc_consumer:
        _kyc_consumer.stop()
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await asyncio.wait_for(_consumer_task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            pass
    await close_engine()


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LendKit Credit Scoring Service",
    description="""
## Credit Scoring Microservice

Part of the **LendKit** open-source lending platform infrastructure.

### Scoring Engine
A transparent, rule-based weighted scoring system that evaluates four signal categories:

| Signal Bucket         | Weight |
|-----------------------|--------|
| KYC Outcome           | 35 pts |
| Identity Verification | 25 pts |
| Income & Employment   | 25 pts |
| Repayment History     | 15 pts |

Raw points are mapped onto a **300–850 FICO-like scale**.

### Tiers
| Score Range | Tier      | Decision                   |
|-------------|-----------|----------------------------|
| 750–850     | Excellent | Best rates, highest limits |
| 650–749     | Good      | Competitive rates          |
| 550–649     | Fair      | Standard rates             |
| 450–549     | Poor      | Entry-level products       |
| < 450       | Very Poor | Decline                    |

### Event-Driven Scoring
The service automatically computes a score when a KYC verification is approved,
by consuming events from the `lendkit:kyc:events` Redis Stream.

### Authentication
All endpoints require a `Bearer` JWT in the `Authorization` header.
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

app.include_router(scores_router, prefix="/api/v1")
app.include_router(customer_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["System"], summary="Health check")
async def health() -> dict:
    consumer_running = _consumer_task is not None and not _consumer_task.done()
    return {
        "status": "healthy",
        "service": "credit-scoring",
        "version": "0.1.0",
        "environment": settings.app_env,
        "kyc_consumer": "running" if consumer_running else "stopped",
    }


@app.get("/metrics", tags=["System"], include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": "lendkit-credit-scoring", "docs": "/docs"}
