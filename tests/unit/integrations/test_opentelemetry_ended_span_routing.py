import logging

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from litellm.integrations.opentelemetry import OpenTelemetry


def _routing_kwargs():
    return {
        "model": "safe-placeholder",
        "standard_logging_object": {
            "id": "bounded-test",
            "call_type": "acompletion",
            "metadata": {"routing_decision": {"router_model_name": "bounded-test"}},
        },
    }


def test_routing_attributes_skip_ended_span_writes(caplog):
    provider = TracerProvider()
    otel = OpenTelemetry(tracer_provider=provider)
    span = provider.get_tracer(__name__).start_span("finished-request")
    span.end()

    with caplog.at_level(logging.WARNING, logger="opentelemetry.sdk.trace"):
        otel.set_attributes(
            span,
            _routing_kwargs(),
            {"model": "safe-placeholder", "choices": [], "usage": {}},
        )

    assert not any(
        "Setting attribute on ended span." in record.getMessage()
        for record in caplog.records
    )


def test_routing_attributes_preserve_values_on_recording_span():
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel = OpenTelemetry(tracer_provider=provider)

    with provider.get_tracer(__name__).start_as_current_span("active-request") as span:
        otel.set_attributes(
            span,
            _routing_kwargs(),
            {"model": "safe-placeholder", "choices": [], "usage": {}},
        )

    (finished,) = exporter.get_finished_spans()
    assert finished.attributes["litellm.routing.router_model_name"] == "bounded-test"
