"""`OtlpSpanSink.close()` against the REAL `BatchSpanProcessor` (OME-1213).

WHY a second file, and why no stub processor here: in opentelemetry-sdk 1.44 the real
`BatchSpanProcessor.force_flush` ignores its `timeout_millis` and returns True whatever the
exporter answered (upstream opentelemetry-python#4568). A stub that returns False on request
proves our branch reacts to an answer the real processor never gives, so every test below goes
through the real processor, and failure is driven by the EXPORTER, which is where the SDK
actually learns about it. None of them needs a race: a refusing exporter fails at once, and a
hung one blocks on an event the test releases.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from screamingface_engine.tracing import otlp
from screamingface_engine.tracing.otlp import (
    FLUSH_TIMEOUT_MS,
    CountingSpanExporter,
    OtlpSpanSink,
    sink_from_env,
)
from screamingface_engine.tracing.span_tree import Span

LOGGER = "screamingface_engine.tracing.otlp"
ENDPOINT = "http://signoz-otel-collector.signoz.svc.cluster.local:4318/v1/traces"
T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


def a_span(n: int = 0) -> Span:
    return Span(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        span_id=f"{n + 1:016x}",
        parent_span_id=None,
        name="gpt",
        operation="chat",
        start_time=T0,
        end_time=T0 + timedelta(seconds=1),
        status="ok",
        attributes={},
    )


def warnings_of(caplog: pytest.LogCaptureFixture) -> list[str]:
    """This module's resolved WARNING messages — never `repr()` (see `test_otlp_sink.py`)."""
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelname == "WARNING"]


class RefusingExporter(SpanExporter):
    """A collector that answers every batch with a failure: a 401, a 404, a dead port."""

    def __init__(self, *, raises: bool = False) -> None:
        self._raises = raises

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._raises:
            raise ConnectionError("collector host does not resolve")
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass


class HangingExporter(SpanExporter):
    """A collector that accepts the connection and never answers, until the test says so."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.shut_down = threading.Event()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.entered.set()
        self.release.wait()
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self.shut_down.set()


@pytest.fixture
def hanging() -> Iterator[HangingExporter]:
    exporter = HangingExporter()
    yield exporter
    # WHY in teardown: the abandoned flush thread is a daemon blocked in `export`. Releasing it
    # lets it finish and shut the processor down, instead of lingering into the next test.
    exporter.release.set()


def a_sink(
    exporter: SpanExporter, *, flush_timeout_ms: int = FLUSH_TIMEOUT_MS
) -> tuple[OtlpSpanSink, CountingSpanExporter]:
    counting = CountingSpanExporter(exporter)
    sink = OtlpSpanSink(
        BatchSpanProcessor(counting),
        endpoint=ENDPOINT,
        delivery=counting,
        flush_timeout_ms=flush_timeout_ms,
    )
    return sink, counting


@pytest.mark.parametrize("raises", [False, True], ids=["answers-failure", "raises"])
def test_a_collector_that_refuses_the_spans_is_reported(
    caplog: pytest.LogCaptureFixture, raises: bool
) -> None:
    """The case the stub-based tests could not see. The real processor's `force_flush` returns
    True here, so only the exporter's own verdict says that three spans went nowhere."""
    sink, counting = a_sink(RefusingExporter(raises=raises))
    for n in range(3):
        sink.emit(a_span(n))

    with caplog.at_level("WARNING", logger=LOGGER):
        sink.close()

    assert counting.undelivered == 3
    warnings = warnings_of(caplog)
    assert len(warnings) == 1, "a refusing collector must warn exactly once per run"
    assert ENDPOINT in warnings[0]
    assert "3 span" in warnings[0], "the warning says how much was lost, not just that it was"


def test_close_is_bounded_even_when_the_collector_never_answers(
    caplog: pytest.LogCaptureFixture, hanging: HangingExporter
) -> None:
    """INVARIANT: `close()` returns within its bound whatever the collector does. The SDK does
    not enforce the bound itself (`timeout_millis` is unused in 1.44), so the sink must, or a
    finished run waits out the exporter's full retry budget once per queued batch."""
    sink, _ = a_sink(hanging, flush_timeout_ms=50)
    sink.emit(a_span())

    started = time.monotonic()
    with caplog.at_level("WARNING", logger=LOGGER):
        sink.close()
    elapsed = time.monotonic() - started

    assert hanging.entered.is_set(), "the flush must have reached the collector and stalled there"
    assert not hanging.release.is_set(), "close() returned only because the collector answered"
    assert elapsed < 2.0, f"close() waited {elapsed:.2f}s on a 50 ms bound"
    warnings = warnings_of(caplog)
    assert len(warnings) == 1
    assert ENDPOINT in warnings[0]
    assert "50ms" in warnings[0]


def test_the_abandoned_flush_still_shuts_the_exporter_down_once_it_returns(
    hanging: HangingExporter,
) -> None:
    """The bound abandons the flush; it does not skip `shutdown`. When the stalled export finally
    returns, the drain thread still releases the exporter (the OME-1213 `finally`)."""
    sink, _ = a_sink(hanging, flush_timeout_ms=50)
    sink.emit(a_span())
    sink.close()
    assert not hanging.shut_down.is_set(), "shutdown waits for the stalled export"

    hanging.release.set()

    assert hanging.shut_down.wait(timeout=5), "the drain thread never shut the exporter down"


def test_a_healthy_collector_behind_the_counter_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A warning that fires on success teaches operators to ignore it."""
    delivered = InMemorySpanExporter()
    sink, counting = a_sink(delivered)
    sink.emit(a_span())

    with caplog.at_level("WARNING", logger=LOGGER):
        sink.close()

    assert warnings_of(caplog) == []
    assert counting.undelivered == 0
    assert len(delivered.get_finished_spans()) == 1


class RecordingExporter(RefusingExporter):
    """Stands in for `OTLPSpanExporter` so the test sees what `sink_from_env` built it with."""

    built: list[RecordingExporter] = []

    def __init__(self, *, endpoint: str | None = None) -> None:
        super().__init__()
        self.endpoint = endpoint
        RecordingExporter.built.append(self)


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[RecordingExporter]]:
    RecordingExporter.built = []
    monkeypatch.setattr(otlp, "OTLPSpanExporter", RecordingExporter)
    yield RecordingExporter.built


@pytest.mark.parametrize(
    ("env", "posted_to"),
    [
        (
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"},
            "http://collector:4318/v1/traces",
        ),
        (
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/"},
            "http://collector:4318/v1/traces",
        ),
        (
            {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://traces:4318/custom"},
            "http://traces:4318/custom",
        ),
        (
            {
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "  ",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            },
            "http://collector:4318/v1/traces",
        ),
    ],
    ids=["generic", "generic-trailing-slash", "signal-specific", "blank-signal-falls-through"],
)
def test_the_logged_endpoint_is_the_url_the_exporter_posts_to(
    caplog: pytest.LogCaptureFixture,
    recording: list[RecordingExporter],
    env: dict[str, str],
    posted_to: str,
) -> None:
    """INVARIANT: the address in the log IS the exporter's address. OTel appends `/v1/traces`
    to the generic variable only, so printing the raw variable would name a URL nothing posts
    to — the exact misdirection naming the endpoint exists to prevent."""
    with caplog.at_level("INFO", logger=LOGGER):
        sink = sink_from_env(env)

    assert sink is not None
    sink.close()
    assert [exporter.endpoint for exporter in recording] == [posted_to]
    info = [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelname == "INFO"]
    assert f"endpoint={posted_to}" in info[0]


def test_sink_from_env_wires_the_counter_into_production(
    caplog: pytest.LogCaptureFixture, recording: list[RecordingExporter]
) -> None:
    """The counter is only worth anything if the production constructor installs it."""
    sink = sink_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"})
    assert sink is not None
    sink.emit(a_span())

    with caplog.at_level("WARNING", logger=LOGGER):
        sink.close()

    warnings = warnings_of(caplog)
    assert len(warnings) == 1
    assert "http://collector:4318/v1/traces" in warnings[0]
