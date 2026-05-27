"""OpenTelemetry event sink — emits each RequestEvent as a span via OTLP/HTTP.

Activated when OTEL_EXPORTER_OTLP_ENDPOINT is set. Span attributes mirror the
RequestEvent fields with semantic-convention-ish names so traces can be
correlated with TF gateway logs and downstream APM tools (Honeycomb, Datadog,
Grafana Tempo, etc.).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unsinkable.events import RequestEvent

log = logging.getLogger("unsinkable.otel")


class OtelEventSink:
    def __init__(self, endpoint: str, service_name: str = "unsinkable") -> None:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        # Only set as global provider if nothing else has already; otherwise
        # users with their own instrumentation can pass an existing tracer in
        # via OTEL_PYTHON_DISABLED_INSTRUMENTATIONS / their own SDK setup.
        if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
            trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer("unsinkable", "0.2.0")

    def emit(self, event: "RequestEvent") -> None:
        try:
            from opentelemetry.trace import SpanKind, Status, StatusCode
            with self._tracer.start_as_current_span(
                name=f"unsinkable.{event.kind}",
                kind=SpanKind.CLIENT,
                attributes={
                    "http.method": event.method,
                    "http.url": event.url,
                    "tfy.requested_model": event.requested_model or "",
                    "tfy.resolved_model": event.resolved_model or "",
                    "tfy.kind": event.kind,
                    "tfy.fallback_hops": ",".join(event.fallback_hops),
                    "tfy.chaos_scenario": (event.chaos or {}).get("scenario", "") if event.chaos else "",
                    "tfy.chaos_original": (event.chaos or {}).get("original", "") if event.chaos else "",
                    "llm.usage.prompt_tokens": event.prompt_tokens or 0,
                    "llm.usage.completion_tokens": event.completion_tokens or 0,
                    "http.status_code": event.status_code or 0,
                    "unsinkable.latency_ms": event.latency_ms or 0,
                },
            ) as span:
                if event.error:
                    span.set_status(Status(StatusCode.ERROR, event.error))
                elif event.status_code and event.status_code >= 400:
                    span.set_status(Status(StatusCode.ERROR, f"HTTP {event.status_code}"))
        except Exception as e:  # noqa: BLE001
            log.debug("otel emit failed: %s", e)
