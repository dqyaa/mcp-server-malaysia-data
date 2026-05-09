"""Observability setup: structured logging, OpenTelemetry tracing, Prometheus metrics.

Three pillars (the SRE textbook canon):
- Logs: structured JSON via structlog, with correlation IDs for request tracing.
- Traces: OpenTelemetry spans from MCP tool call → HTTP request → cache layer.
- Metrics: Prometheus counters/histograms for SLO tracking.

Why this matters in interviews: every senior AI engineer JD in 2026 lists
"production observability" as a requirement. Most candidates mumble through
this question. Having structlog + OTel + Prometheus wired in a public repo
is concrete proof you've done it.

Tradeoffs (be ready to discuss):
- structlog vs stdlib logging: structlog handles structured fields natively;
  stdlib requires `extra=` everywhere or a custom Formatter.
- OTel vs vendor APM (Datadog, New Relic): OTel is vendor-neutral; the same
  spans flow to any backend that speaks OTLP. Costs more setup, less lock-in.
- Prometheus vs OTel metrics: OTel metrics is the future, but Prometheus
  scraping is still the most universal pattern for self-hosted setups.
  We expose both: OTel pushes traces, Prometheus pulls metrics.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from malaysia_data_mcp.infrastructure.settings import Settings

# =====================================================================
# Prometheus metrics — module-level singletons (one registry per process)
# =====================================================================

_registry = CollectorRegistry()

tool_calls_total = Counter(
    "malaysia_data_tool_calls_total",
    "Total MCP tool invocations.",
    labelnames=("tool", "outcome"),  # outcome: success | error | rate_limited | circuit_open
    registry=_registry,
)

tool_call_duration = Histogram(
    "malaysia_data_tool_call_duration_seconds",
    "Tool call end-to-end latency.",
    labelnames=("tool",),
    # Buckets tuned for sub-second tool calls with occasional slow upstreams.
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
    registry=_registry,
)

upstream_requests_total = Counter(
    "malaysia_data_upstream_requests_total",
    "Outbound HTTP requests to upstream APIs.",
    labelnames=("upstream", "status"),  # status: 2xx | 4xx | 5xx | timeout | network
    registry=_registry,
)

upstream_request_duration = Histogram(
    "malaysia_data_upstream_request_duration_seconds",
    "Upstream HTTP request latency.",
    labelnames=("upstream",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
    registry=_registry,
)

cache_operations_total = Counter(
    "malaysia_data_cache_operations_total",
    "Cache operations.",
    labelnames=("layer", "outcome"),  # layer: l1|l2; outcome: hit|miss|set|evict
    registry=_registry,
)

circuit_state = Gauge(
    "malaysia_data_circuit_state",
    "Circuit breaker state per upstream (0=closed, 1=half_open, 2=open).",
    labelnames=("upstream",),
    registry=_registry,
)


def get_metrics_registry() -> CollectorRegistry:
    """For tests and the /metrics endpoint."""
    return _registry


# =====================================================================
# Structured logging
# =====================================================================


def configure_logging(settings: Settings) -> None:
    """Wire structlog as the single logger across the app.

    Call once at startup. Idempotent.
    """
    log_level = getattr(logging, settings.log_level)

    # Stdlib logging is the underlying transport — structlog wraps it.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,  # picks up correlation_id
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a logger bound to the given module name."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]


@contextmanager
def correlation_id(value: str | None = None) -> Iterator[str]:
    """Bind a correlation ID for the duration of a request/tool-call.

    Usage:
        with correlation_id() as cid:
            logger.info("tool_called", tool="get_opr")
            # cid appears in every log line emitted in this block.
    """
    cid = value or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(correlation_id=cid)
    try:
        yield cid
    finally:
        structlog.contextvars.unbind_contextvars("correlation_id")


# =====================================================================
# OpenTelemetry tracing
# =====================================================================


_tracer: Tracer | None = None


def configure_tracing(settings: Settings) -> Tracer:
    """Wire OpenTelemetry tracer + auto-instrument httpx.

    Returns a tracer for manual span creation. If OTel is disabled, returns a
    no-op tracer (every span call is a cheap no-op).
    """
    global _tracer

    if not settings.otel_enabled:
        _tracer = trace.get_tracer(settings.service_name)
        return _tracer

    resource = Resource.create({SERVICE_NAME: settings.service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{settings.otel_endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # Auto-instrument httpx so every outbound call gets a span.
    HTTPXClientInstrumentor().instrument()

    _tracer = trace.get_tracer(settings.service_name)
    return _tracer


def get_tracer() -> Tracer:
    """Return the configured tracer or a no-op default."""
    if _tracer is None:
        return trace.get_tracer("malaysia-data-mcp")
    return _tracer
