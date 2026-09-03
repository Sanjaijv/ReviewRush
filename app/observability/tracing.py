"""Distributed tracing (Phase 13): OpenTelemetry, instrumenting FastAPI,
Celery, and httpx so one trace follows a review from the webhook request
through every worker stage and GitHub/model call.

Off by default (`tracing_enabled=False`): it requires a reachable OTLP
collector, an external dependency this release doesn't assume every
operator has. Every function here is a no-op when disabled, so importing
this module has no effect on a deployment that hasn't opted in.
"""

import logging
from typing import TYPE_CHECKING

from app.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_configured = False


def setup_tracing(settings: Settings) -> None:
    """Configure the global OpenTelemetry TracerProvider and instrument
    Celery + httpx. Must run once, before any Celery task or httpx client is
    created, so call this at process startup (`app/main.py` for the API
    process, `app/celery_app.py` for the worker process) - never lazily.
    """
    global _configured
    if not settings.tracing_enabled or _configured:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    resource = Resource.create({SERVICE_NAME: settings.tracing_service_name})
    provider = TracerProvider(
        resource=resource, sampler=TraceIdRatioBased(settings.tracing_sample_ratio)
    )
    exporter = OTLPSpanExporter(endpoint=f"{settings.tracing_otlp_endpoint.rstrip('/')}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    CeleryInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    _configured = True
    logger.info("tracing enabled", extra={"otlp_endpoint": settings.tracing_otlp_endpoint})


def instrument_fastapi_app(app: "FastAPI", settings: Settings) -> None:
    """Instrument one FastAPI app instance for tracing. Separate from
    `setup_tracing` because it needs the app object, which only the API
    process (not the worker) has.
    """
    if not settings.tracing_enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
