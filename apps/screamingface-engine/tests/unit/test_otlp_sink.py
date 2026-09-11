"""The OTLP adapter: a mapped `Span` becomes a real OTel span (OME-1130).

This is the ONE module in the engine that imports `opentelemetry` (ledger D8), so it is the one
test file that does. It uses OTel's own `InMemorySpanExporter`, which means the conversion is
exercised through the REAL SDK path — the same `SpanProcessor.on_end` a live collector sits
behind — with no network.

WHY that matters more than it looks: `BatchSpanProcessor.on_end` opens with
`if not (span.context and span.context.trace_flags.sampled): return`. A span built without the
sampled flag is dropped SILENTLY, by the SDK, with no error anywhere. Exporting nothing while
every log line says the exporter is running is precisely the failure this ticket exists to
avoid, so the flag has a test of its own below.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from screamingface_engine.tracing.otlp import OtlpSpanSink, sink_from_env
from screamingface_engine.tracing.span_tree import Span

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
ROOT = "00f067aa0ba902b7"
CHILD = "a" * 16
T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def a_span(
    *,
    span_id: str = CHILD,
    parent: str | None = ROOT,
    status: str = "ok",
    end: datetime | None = None,
    attributes: dict[str, str | int | float | bool] | None = None,
) -> Span:
    return Span(
        trace_id=TRACE,
        span_id=span_id,
        parent_span_id=parent,
        name="gpt",
        operation="chat",
        start_time=at(1),
        end_time=end if end is not None else at(3),
        status=status,
        attributes=attributes or {},
    )


def exported(*spans: Span) -> list[ReadableSpan]:
    """Drive spans through the real SDK processor path and read back what a collector would."""
    exporter = InMemorySpanExporter()
    sink = OtlpSpanSink(SimpleSpanProcessor(exporter))
    for span in spans:
        sink.emit(span)
    sink.close()
    return list(exporter.get_finished_spans())


# --- identity survives the conversion ----------------------------------------------------------


def test_the_wire_s_hex_ids_become_the_otel_ids() -> None:
    (out,) = exported(a_span())

    assert out.context is not None
    assert format(out.context.trace_id, "032x") == TRACE
    assert format(out.context.span_id, "016x") == CHILD


def test_the_parent_edge_becomes_a_parent_context_in_the_same_trace() -> None:
    (out,) = exported(a_span(parent=ROOT))

    assert out.parent is not None
    assert format(out.parent.span_id, "016x") == ROOT
    assert out.parent.trace_id == out.context.trace_id if out.context else False


def test_a_span_with_no_parent_is_a_root() -> None:
    (out,) = exported(a_span(span_id=ROOT, parent=None))

    assert out.parent is None


def test_the_sampled_flag_is_set_or_the_sdk_drops_the_span_silently() -> None:
    """`url4.streaming.trace` hardcodes `_SAMPLED = "01"` — every run is nominally sampled
    (ledger D5), and the SDK's processors enforce that flag rather than trusting the caller."""
    (out,) = exported(a_span())

    assert out.context is not None
    assert out.context.trace_flags.sampled


# --- timing ---------------------------------------------------------------------------------


def test_timestamps_become_nanoseconds_since_epoch() -> None:
    (out,) = exported(a_span())

    assert out.start_time == int(at(1).timestamp() * 1_000_000_000)
    assert out.end_time == int(at(3).timestamp() * 1_000_000_000)


def test_the_duration_is_preserved_exactly() -> None:
    (out,) = exported(a_span(end=at(4)))

    assert out.end_time is not None and out.start_time is not None
    assert out.end_time - out.start_time == 3 * 1_000_000_000


# --- status ------------------------------------------------------------------------------------


def test_an_ok_span_is_ok() -> None:
    (out,) = exported(a_span(status="ok"))

    assert out.status.status_code is StatusCode.OK


def test_an_error_span_is_an_error() -> None:
    (out,) = exported(a_span(status="error"))

    assert out.status.status_code is StatusCode.ERROR


def test_a_succeeded_run_root_is_ok() -> None:
    """The ROOT carries `TerminatedData.status` vocabulary (`succeeded`), not `SpanData`'s
    (`ok`). Both reach this mapper, so both must be understood."""
    (out,) = exported(a_span(status="succeeded"))

    assert out.status.status_code is StatusCode.OK


def test_a_stopped_run_keeps_its_verbatim_reason_rather_than_being_flattened_to_error() -> None:
    """`stopped` and `failed` are both non-OK, and OTel has one non-OK code. Losing which of
    the two it was would erase the only place that distinction still survives (ledger D7)."""
    (stopped,) = exported(a_span(status="stopped"))
    (failed,) = exported(a_span(status="failed"))

    assert stopped.status.status_code is StatusCode.ERROR
    assert stopped.status.description == "stopped"
    assert failed.status.description == "failed"


# --- attributes ----------------------------------------------------------------------------


def test_gen_ai_attributes_survive_under_their_conventional_names() -> None:
    """`SpanData` already declares OTel serialization aliases (`gen_ai.request.model`, …), so
    the conventional names are the protocol's own — not a mapping invented here."""
    (out,) = exported(
        a_span(attributes={"gen_ai.request.model": "gpt-5.5", "gen_ai.usage.input_tokens": 124})
    )

    assert out.attributes is not None
    assert out.attributes["gen_ai.request.model"] == "gpt-5.5"
    assert out.attributes["gen_ai.usage.input_tokens"] == 124


def test_the_operation_is_recorded_as_the_conventional_attribute() -> None:
    (out,) = exported(a_span())

    assert out.attributes is not None
    assert out.attributes["gen_ai.operation.name"] == "chat"


def test_the_span_name_comes_from_the_wire() -> None:
    (out,) = exported(a_span())

    assert out.name == "gpt"


# --- off by default (ledger D9) ----------------------------------------------------------------


def test_no_endpoint_configured_means_no_sink() -> None:
    """Every existing run, every local run and every test must be unaffected by construction —
    not by a flag someone remembered to set."""
    assert sink_from_env({}) is None


def test_an_empty_endpoint_is_treated_as_unset() -> None:
    """A chart that renders `OTEL_EXPORTER_OTLP_ENDPOINT: ""` for an unconfigured environment
    must read as "off", not as "export to the empty string"."""
    assert sink_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "   "}) is None


def test_a_configured_endpoint_builds_a_sink() -> None:
    sink = sink_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.invalid:4318"})

    assert sink is not None
    sink.close()


def test_the_traces_specific_endpoint_also_turns_it_on() -> None:
    """OTel's env contract lets a deployment set only the signal-specific variable; reading
    just the generic one would leave such a deployment silently un-traced."""
    sink = sink_from_env(
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://collector.invalid:4318/v1/traces"}
    )

    assert sink is not None
    sink.close()
