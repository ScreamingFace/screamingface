"""Local in-process runs export their span tree, exactly as a Job does (e2e workbench unit 6a).

`runner.main._run_process` wraps a Job's publisher in `SpanRelay(publisher, span_sink(env), ...)`.
`InProcessJobRunner` used to hand `lifecycle.run` the bare stream, so a local run exported
nothing even with `OTEL_EXPORTER_OTLP_ENDPOINT` set. These tests pin the three properties the
wrap must keep:

* configured -> the `url4.run` root and its `gen_ai.*` children reach the sink, under the run's
  own trace id, and the sink is closed exactly once per run (on every outcome);
* not configured (the default) -> no sink, and the published frames are BYTE-IDENTICAL to an
  unwrapped `lifecycle.run`;
* a sink that raises never changes the run's outcome (OME-1130 ledger D4).
"""

from __future__ import annotations

import asyncio
import secrets
import threading
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

import pytest

import url4.streaming.lifecycle as lifecycle
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.client_provenance import ProvenanceExecutor
from screamingface_engine.run_evidence import TerminalWatch
from screamingface_engine.subjects import RUN_ROOT_NODE
from screamingface_engine.tracing.relay import ROOT_SPAN_NAME, SpanSink
from screamingface_engine.tracing.span_tree import Span
from url4.streaming.interfaces import (
    Completed,
    ExecStep,
    Executor,
    SpanRef,
    TraceContext,
    Traced,
)
from url4.streaming.protocol import OutboundFrame, ResultData, StartedEvent, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData, SpanData
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

pytestmark = pytest.mark.asyncio

TOPIC = "t-local-otel"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
HANDED = f"00-{TRACE}-00f067aa0ba902b7-01"
ENDPOINT_ENV = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318"}
MODEL = "openrouter/test-model"


def _at(seconds: int) -> datetime:
    return datetime(2026, 10, 22, 12, 0, seconds, tzinfo=UTC)


class _ModelCallExecutor(Executor):
    """One finished model-call span, then a result — the smallest run with a `gen_ai` child."""

    def __init__(self, *, block: bool = False) -> None:
        self._block = block

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        yield Traced(
            payload=SpanData(
                name="chat",
                operation="chat",
                request_model=MODEL,
                input_tokens=3,
                output_tokens=5,
                start=_at(1),
                end=_at(2),
            ),
            span=SpanRef(span_id="a" * 16, parent_span_id=None),
        )
        if self._block:
            await asyncio.Event().wait()
        yield Completed(
            result=ResultData(body="ok"),
            subtree_cost=CostUsageData(
                scope="self",
                provider="test",
                model=MODEL,
                pricing_version="v0",
                usage=TokenUsage(input_tokens=3, output_tokens=5),
                cost=CostBreakdown(total_usd=Decimal("0")),
            ),
        )


class _FakeSink:
    """The `SpanSink` port, recorded. Records the thread `close` ran on, too."""

    def __init__(self, *, explode_emit: bool = False, explode_close: bool = False) -> None:
        self.spans: list[Span] = []
        self.closed = 0
        self.close_thread: int | None = None
        self._explode_emit = explode_emit
        self._explode_close = explode_close

    def emit(self, span: Span) -> None:
        if self._explode_emit:
            raise RuntimeError("the collector is on fire")
        self.spans.append(span)

    def close(self) -> None:
        self.closed += 1
        self.close_thread = threading.get_ident()
        if self._explode_close:
            raise RuntimeError("the collector is still on fire")


class _Loader:
    """The loader seam: records the env each run asked with and hands out a sink per run."""

    def __init__(self, *, explode_emit: bool = False, explode_close: bool = False) -> None:
        self._explode_emit = explode_emit
        self._explode_close = explode_close
        self.envs: list[Mapping[str, str]] = []
        self.sinks: list[_FakeSink] = []

    def __call__(self, env: Mapping[str, str]) -> _FakeSink:
        self.envs.append(dict(env))
        sink = _FakeSink(explode_emit=self._explode_emit, explode_close=self._explode_close)
        self.sinks.append(sink)
        return sink


async def _frames(stream: InMemoryEventStream, topic: str = TOPIC) -> list[OutboundFrame]:
    frames: list[OutboundFrame] = []
    async for event in stream.subscribe(topic, from_sequence=None):
        frames.append(event)
        if isinstance(event, TerminatedEvent):
            return frames
    raise AssertionError("stream ended without a terminal frame")


async def _await_task(runner: InProcessJobRunner, topic: str = TOPIC) -> None:
    """Let the run's task (including its relay teardown) finish."""
    for _ in range(500):
        if await runner.status(topic) != "running":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish")


def _runner(
    stream: InMemoryEventStream,
    loader: _Loader | None,
    *,
    executor: Executor | None = None,
    base_env: Mapping[str, str] | None = None,
) -> InProcessJobRunner:
    def factory(_env: Mapping[str, str]) -> Executor:
        return executor if executor is not None else _ModelCallExecutor()

    if loader is None:
        return InProcessJobRunner(stream, factory, base_env=base_env)
    return InProcessJobRunner(stream, factory, base_env=base_env, span_sink=loader)


# --- configured: the run's span tree is exported ---------------------------------------------


async def test_a_local_run_exports_its_root_and_gen_ai_children_under_its_trace_id() -> None:
    stream = InMemoryEventStream()
    loader = _Loader()
    runner = _runner(stream, loader, base_env=ENDPOINT_ENV)

    await runner.schedule(TOPIC, "x", 30, traceparent=HANDED)
    terminal = (await _frames(stream))[-1]
    await _await_task(runner)

    assert isinstance(terminal, TerminatedEvent)
    assert terminal.data.status == "succeeded"
    assert len(loader.sinks) == 1
    sink = loader.sinks[0]
    root = sink.spans[-1]
    assert root.name == ROOT_SPAN_NAME
    # The handed span is the accept span; `url4.run` hangs under it (OME-1218).
    assert root.parent_span_id == "00f067aa0ba902b7"
    children = sink.spans[:-1]
    assert [c.attributes.get("gen_ai.request.model") for c in children] == [MODEL]
    assert children[0].parent_span_id == root.span_id
    assert {s.trace_id for s in sink.spans} == {TRACE}
    assert sink.closed == 1


async def test_the_loader_is_asked_with_the_run_environment() -> None:
    stream = InMemoryEventStream()
    loader = _Loader()
    runner = _runner(stream, loader, base_env=ENDPOINT_ENV)

    await runner.schedule(TOPIC, "x", 30)
    await _frames(stream)
    await _await_task(runner)

    assert (
        loader.envs[0]["OTEL_EXPORTER_OTLP_ENDPOINT"] == ENDPOINT_ENV["OTEL_EXPORTER_OTLP_ENDPOINT"]
    )


async def test_the_sink_flush_runs_off_the_event_loop_thread() -> None:
    """`OtlpSpanSink.close` joins a flush thread for up to its bound. Local mode runs every run
    on ONE loop, so a blocking close there would stall every other run in flight."""
    stream = InMemoryEventStream()
    loader = _Loader()
    runner = _runner(stream, loader, base_env=ENDPOINT_ENV)

    await runner.schedule(TOPIC, "x", 30)
    await _frames(stream)
    await _await_task(runner)

    assert loader.sinks[0].close_thread is not None
    assert loader.sinks[0].close_thread != threading.get_ident()


async def test_a_stopped_run_still_closes_its_sink_and_emits_a_stopped_root() -> None:
    stream = InMemoryEventStream()
    loader = _Loader()
    runner = _runner(stream, loader, executor=_ModelCallExecutor(block=True), base_env=ENDPOINT_ENV)

    await runner.schedule(TOPIC, "x", 30)
    async for event in stream.subscribe(TOPIC, from_sequence=None):
        if isinstance(event, StartedEvent):
            break
    await asyncio.sleep(0.05)  # let the model-call span publish before the stop
    await runner.stop(TOPIC)
    await _await_task(runner)

    sink = loader.sinks[0]
    assert sink.closed == 1
    assert sink.spans[-1].name == ROOT_SPAN_NAME
    assert sink.spans[-1].status == "stopped"


async def test_aclose_closes_the_sink_of_a_cancelled_run() -> None:
    stream = InMemoryEventStream()
    loader = _Loader()
    runner = _runner(stream, loader, executor=_ModelCallExecutor(block=True), base_env=ENDPOINT_ENV)

    await runner.schedule(TOPIC, "x", 30)
    async for event in stream.subscribe(TOPIC, from_sequence=None):
        if isinstance(event, StartedEvent):
            break
    await runner.aclose()

    assert loader.sinks[0].closed == 1


# --- a broken sink never fails a run ---------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs", [{"explode_emit": True}, {"explode_close": True}], ids=["emit", "close"]
)
async def test_a_sink_that_raises_does_not_fail_the_run(kwargs: dict[str, bool]) -> None:
    stream = InMemoryEventStream()
    loader = _Loader(**kwargs)
    runner = _runner(stream, loader, base_env=ENDPOINT_ENV)

    await runner.schedule(TOPIC, "x", 30)
    terminal = (await _frames(stream))[-1]
    await _await_task(runner)

    assert isinstance(terminal, TerminatedEvent)
    assert terminal.data.status == "succeeded"
    assert await runner.status(TOPIC) == "succeeded"


# --- not configured (the default): a byte-identical passthrough -------------------------------


def _deterministic_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every value `lifecycle.run` mints, so two runs can be compared byte for byte."""
    ids = count()

    class _FixedUuid:
        def __init__(self, n: int) -> None:
            self.hex = f"{n:032x}"

    class _FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return _at(30)

    monkeypatch.setattr(lifecycle, "uuid4", lambda: _FixedUuid(next(ids)))
    monkeypatch.setattr(lifecycle, "datetime", _FixedClock)
    monkeypatch.setattr(secrets, "token_hex", lambda n: "b" * (2 * n))


async def _unwrapped_frames(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    _deterministic_lifecycle(monkeypatch)
    stream = InMemoryEventStream()
    await lifecycle.run(
        TerminalWatch(stream),
        ProvenanceExecutor(_ModelCallExecutor(), None),
        TOPIC,
        "x",
        node=RUN_ROOT_NODE,
        traceparent=HANDED,
        deadline_s=30,
    )
    return [f.model_dump_json() for f in await _frames(stream)]


async def test_with_no_endpoint_no_sink_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    from screamingface_engine.tracing.loader import load_span_sink

    results: list[SpanSink | None] = []

    def spy(env: Mapping[str, str]) -> SpanSink | None:
        sink = load_span_sink(env)
        results.append(sink)
        return sink

    stream = InMemoryEventStream()
    runner = InProcessJobRunner(
        stream,
        lambda _env: _ModelCallExecutor(),
        base_env={"OTEL_EXPORTER_OTLP_ENDPOINT": "  "},
        span_sink=spy,
    )
    await runner.schedule(TOPIC, "x", 30)
    await _frames(stream)
    await _await_task(runner)

    assert results == [None]


async def test_with_no_endpoint_the_frames_are_byte_identical_to_an_unwrapped_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = await _unwrapped_frames(monkeypatch)

    _deterministic_lifecycle(monkeypatch)
    stream = InMemoryEventStream()
    runner = _runner(stream, None)  # the production default loader, with no endpoint set
    await runner.schedule(TOPIC, "x", 30, traceparent=HANDED)
    actual = [f.model_dump_json() for f in await _frames(stream)]
    await _await_task(runner)

    assert actual == expected


async def test_an_active_sink_does_not_alter_a_single_published_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = await _unwrapped_frames(monkeypatch)

    _deterministic_lifecycle(monkeypatch)
    stream = InMemoryEventStream()
    loader = _Loader()
    runner = _runner(stream, loader, base_env=ENDPOINT_ENV)
    await runner.schedule(TOPIC, "x", 30, traceparent=HANDED)
    actual = [f.model_dump_json() for f in await _frames(stream)]
    await _await_task(runner)

    assert actual == expected
    assert loader.sinks[0].spans  # and it really did export


# --- the lazy import is kept ------------------------------------------------------------------


def test_importing_the_inprocess_adapter_does_not_load_opentelemetry() -> None:
    """A clean subprocess, as in `test_span_export_wiring`: wiring the relay here must not pull
    the OTel SDK into every local App's import graph — only a configured endpoint may load it."""
    import subprocess
    import sys

    probe = (
        "import sys; import screamingface_engine.adapters.inprocess; "
        "print(len([m for m in sys.modules if m.startswith('opentelemetry')]))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert loaded.stdout.strip() == "0"
