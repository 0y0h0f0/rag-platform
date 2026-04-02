from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

from app.core.config import settings

logger = logging.getLogger(__name__)

_tracer = None


def init_tracing() -> None:
    """Initialize OpenTelemetry tracing if enabled."""
    global _tracer

    if not settings.otel_enabled:
        logger.info("OpenTelemetry tracing disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": settings.otel_service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(settings.otel_service_name)
        logger.info("OpenTelemetry tracing initialized, exporting to %s", settings.otel_exporter_endpoint)
    except ImportError:
        logger.warning("OpenTelemetry packages not installed, tracing disabled")
    except Exception:
        logger.warning("Failed to initialize OpenTelemetry tracing", exc_info=True)


def instrument_fastapi(app: Any) -> None:
    """Add OpenTelemetry FastAPI instrumentation middleware."""
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI OpenTelemetry instrumentation enabled")
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed")
    except Exception:
        logger.warning("Failed to instrument FastAPI", exc_info=True)


def get_tracer():
    """Get the global tracer. Returns a no-op tracer if OTel is disabled."""
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        return trace.get_tracer(settings.otel_service_name)
    except ImportError:
        return _NoOpTracer()


@contextmanager
def trace_span(name: str, attributes: dict | None = None) -> Generator:
    """Context manager for creating a trace span. No-op when tracing is disabled."""
    tracer = get_tracer()
    if isinstance(tracer, _NoOpTracer):
        yield _NoOpSpan()
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


def inject_trace_context() -> dict:
    """Extract current trace context for propagation (e.g., into Celery task headers)."""
    if not settings.otel_enabled:
        return {}
    try:
        from opentelemetry import context
        from opentelemetry.propagators import textmap
        from opentelemetry.propagate import inject

        carrier: dict[str, str] = {}
        inject(carrier)
        return carrier
    except ImportError:
        return {}


def extract_trace_context(carrier: dict) -> Any:
    """Restore trace context from a carrier dict (e.g., Celery task headers)."""
    if not settings.otel_enabled or not carrier:
        return None
    try:
        from opentelemetry.propagate import extract
        return extract(carrier)
    except ImportError:
        return None


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        yield _NoOpSpan()


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, *args, **kwargs) -> None:
        pass
