"""OTel sink — verify spans get the right attributes when emitted."""

import pytest

pytest.importorskip("opentelemetry.sdk.trace.export")

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from unsinkable.events import RequestEvent
from unsinkable.otel_sink import OtelEventSink


def _make_sink_with_memory_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "unsinkable-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    # Construct the sink with a dummy endpoint; the provider above wins because
    # the sink only sets itself as global if no provider exists.
    sink = OtelEventSink(endpoint="http://unused.example/v1/traces")
    # Force-override the sink's internal tracer to use our test provider
    sink._tracer = provider.get_tracer("unsinkable-test")
    return sink, exporter


def test_otel_sink_emits_span_with_attributes():
    sink, exporter = _make_sink_with_memory_exporter()
    sink.emit(RequestEvent(
        method="POST",
        url="https://gw/v1/chat/completions",
        requested_model="resilient-chat/resilient-chat",
        resolved_model="claude-sonnet-4-6",
        status_code=200,
        latency_ms=2733.5,
        kind="llm",
        chaos={"scenario": "openai", "original": "resilient-chat/resilient-chat",
               "chaos": "chaos-openai-down/chaos-openai-down"},
        prompt_tokens=42,
        completion_tokens=18,
    ))
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "unsinkable.llm"
    attrs = dict(s.attributes)
    assert attrs["tfy.requested_model"] == "resilient-chat/resilient-chat"
    assert attrs["tfy.resolved_model"] == "claude-sonnet-4-6"
    assert attrs["http.status_code"] == 200
    assert attrs["tfy.chaos_scenario"] == "openai"
    assert attrs["llm.usage.prompt_tokens"] == 42
    assert attrs["llm.usage.completion_tokens"] == 18


def test_otel_sink_marks_error_status_for_http_500():
    from opentelemetry.trace import StatusCode

    sink, exporter = _make_sink_with_memory_exporter()
    sink.emit(RequestEvent(
        method="POST", url="https://gw/v1/chat/completions",
        status_code=500, latency_ms=400.0, kind="llm",
    ))
    spans = exporter.get_finished_spans()
    assert spans[0].status.status_code == StatusCode.ERROR


def test_otel_sink_marks_error_status_for_exception():
    from opentelemetry.trace import StatusCode

    sink, exporter = _make_sink_with_memory_exporter()
    sink.emit(RequestEvent(
        method="POST", url="https://gw/v1/chat/completions",
        error="ConnectError: name resolution failed",
        latency_ms=10.0, kind="llm",
    ))
    spans = exporter.get_finished_spans()
    assert spans[0].status.status_code == StatusCode.ERROR
