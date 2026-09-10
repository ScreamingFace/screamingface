"""The publisher proxy that ships a run's spans to a sink (OME-1130).

MOUNT: the run's own publisher, wrapped. The ticket said "the control-plane relay, never the
runner" — but there is no control-plane subscription that sees all runs (`stream_for(topic)`
creates ONE JetStream stream per run), so that mount point does not exist. The owner resolved
the fork in favour of a publisher proxy, which sees every frame of every run by construction,
attached client or not.

THE INVARIANT THIS FILE EXISTS FOR: **the relay may never fail or alter a run.** It sits on the
one path every frame of every run travels. A sink that raises, a mapper that trips, a collector
that is down — none of them may turn a working run into a failed one. Half the tests below are
that single property approached from different directions.

No OTel here: the sink is a PORT, and these tests hand in a fake. That is the whole point of
the port/adapter split (ledger D8) — the semantics are testable without the transport.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from screamingface_engine.tracing.relay import SpanRelay
from screamingface_engine.tracing.span_tree import Span
from url4.streaming.interfaces import EventPublisher
from url4.streaming.protocol import (
    OutboundFrame,
    SpanData,
    SpanEvent,
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
ROOT = "00f067aa0ba902b7"
TOPIC = "t"
T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class Recorder(EventPublisher):
    """The inner publisher — remembers what reached the transport, in order."""

    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []
        self.streams: list[str] = []
        self.flushes = 0
        self.closes = 0

    async def ensure_stream(self, topic: str) -> None:
        self.streams.append(topic)

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.frames.append(event)

    async def flush(self) -> None:
        self.flushes += 1

    async def close(self) -> None:
        self.closes += 1


class FakeSink:
    """The `SpanSink` port, recorded. `closed` counts rather than flags — the relay must
    close exactly once, and a double `shutdown()` on the real OTel processor is not a no-op."""

    def __init__(self, *, explode: bool = False) -> None:
        self.spans: list[Span] = []
        self.closed = 0
        self._explode = explode

    def emit(self, span: Span) -> None:
        if self._explode:
            raise RuntimeError("the collector is on fire")
        self.spans.append(span)

    def close(self) -> None:
        self.closed += 1
        if self._explode:
            raise RuntimeError("the collector is still on fire")


def _envelope(traceparent: str, tracestate: str | None = None, *, time: datetime | None = None):
    return {
        "id": "evt",
        "source": source_for(TOPIC, "root"),
        "subject": TOPIC,
        "sequence": "1",
        "time": time if time is not None else at(0),
        "traceparent": traceparent,
        "tracestate": tracestate,
    }


def started(*, time: datetime | None = None) -> StartedEvent:
    """A run-level frame: `_trace_fields` publishes it under the ROOT traceparent, which is
    how the relay learns an identity no `SpanEvent` ever carries."""
    return StartedEvent(**_envelope(f"00-{TRACE}-{ROOT}-01", time=time), data=StartedData(url4="x"))


def terminated(status: str = "succeeded", *, time: datetime | None = None) -> TerminatedEvent:
    return TerminatedEvent(
        **_envelope(f"00-{TRACE}-{ROOT}-01", time=time),
        data=TerminatedData(status=status),  # type: ignore[arg-type]
    )


def span(
    span_id: str = "a" * 16,
    *,
    parent: str | None = None,
    traceparent: str | None = None,
    end: datetime | None = None,
) -> SpanEvent:
    return SpanEvent(
        **_envelope(
            traceparent if traceparent is not None else f"00-{TRACE}-{span_id}-01",
            f"url4.parent={parent}" if parent else None,
        ),
        data=SpanData(
            name="gpt",
            operation="chat",
            start=at(1),
            end=end if end is not None else at(2),
            status="ok",
        ),
    )


async def drive(relay: SpanRelay, *frames: OutboundFrame) -> None:
    await relay.ensure_stream(TOPIC)
    for frame in frames:
        await relay.publish(TOPIC, frame)


# --- transparency: the relay must be invisible to the run -------------------------------------


@pytest.mark.asyncio
async def test_every_frame_reaches_the_inner_publisher_unchanged() -> None:
    """The property that makes it safe to mount this on the run's ONLY publisher."""
    inner, sink = Recorder(), FakeSink()
    frames = (started(), span(), terminated())

    await drive(SpanRelay(inner, sink), *frames)

    assert inner.frames == list(frames)
    assert inner.streams == [TOPIC]


@pytest.mark.asyncio
async def test_flush_is_forwarded() -> None:
    inner, sink = Recorder(), FakeSink()

    await SpanRelay(inner, sink).flush()

    assert inner.flushes == 1


@pytest.mark.asyncio
async def test_the_wire_ports_close_is_forwarded_and_is_not_the_sinks() -> None:
    """`EventPublisher.close` is a non-abstract ASYNC no-op, so a sync override type-checks in
    Python and only fails at the `await` — at teardown, on the path that runs when something
    has already gone wrong. Pyright caught that here; this keeps it caught.

    The two are separate methods on purpose: this one closes the TRANSPORT, `shutdown()`
    closes the sink. A proxy that stopped forwarding this would leak the inner connection.
    """
    inner, sink = Recorder(), FakeSink()
    relay = SpanRelay(inner, sink)

    await relay.close()

    assert inner.closes == 1
    assert sink.closed == 0, "closing the wire must not shut down the exporter"


@pytest.mark.asyncio
async def test_a_sink_that_raises_does_not_fail_the_run() -> None:
    """INVARIANT (ledger D4). A collector outage must degrade telemetry, never the run.

    This is the single most important test in the file: the relay sits on the path every
    frame travels, so an exception escaping here converts a downed collector into a fleet of
    failed runs.
    """
    inner, sink = Recorder(), FakeSink(explode=True)

    await drive(SpanRelay(inner, sink), started(), span(), terminated())

    assert [type(f) for f in inner.frames] == [StartedEvent, SpanEvent, TerminatedEvent]


@pytest.mark.asyncio
async def test_a_sink_that_raises_on_close_does_not_fail_the_run() -> None:
    relay = SpanRelay(Recorder(), FakeSink(explode=True))

    relay.shutdown()  # must not raise


# --- what reaches the sink --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_span_frame_becomes_a_span() -> None:
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(), span("b" * 16), terminated())

    emitted = [s for s in sink.spans if s.span_id == "b" * 16]
    assert len(emitted) == 1
    assert emitted[0].trace_id == TRACE


@pytest.mark.asyncio
async def test_run_level_frames_are_not_mistaken_for_spans() -> None:
    """`Started`/`Terminated` ride the ROOT traceparent. Mapping them as node spans would
    emit a duplicate of the root under the root's own id."""
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(), terminated())

    assert [s.span_id for s in sink.spans] == [ROOT], "only the synthetic root should appear"


@pytest.mark.asyncio
async def test_an_undecodable_traceparent_is_counted_not_invented() -> None:
    inner, sink = Recorder(), FakeSink()
    relay = SpanRelay(inner, sink)

    await drive(relay, started(), span(traceparent="not-a-traceparent"), terminated())

    assert [s.span_id for s in sink.spans] == [ROOT]
    assert relay.undecodable == 1


@pytest.mark.asyncio
async def test_an_unfinished_span_is_counted_not_given_a_fabricated_end() -> None:
    """Ledger D11: OTLP cannot say "still running". `end=None` encodes as epoch 0 and renders
    as a 56-year span; `end == start` states a 0 ms duration that is a lie. Absent is better."""
    inner, sink = Recorder(), FakeSink()
    relay = SpanRelay(inner, sink)

    frame = span().model_copy(update={"data": span().data.model_copy(update={"end": None})})
    await drive(relay, started(), frame, terminated())

    assert [s.span_id for s in sink.spans] == [ROOT]
    assert relay.unfinished == 1


# --- the synthetic root (ledger D7) ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_run_gets_a_root_span_carrying_the_wire_s_own_root_id() -> None:
    """Not fabrication: `lifecycle._trace_fields` publishes run-level frames under
    `format_traceparent(trace_id, root_span_id)`, so the `Started` envelope STATES this id.
    Every `url4.parent=` and every Phase 1 gateway `traceparent` already references it."""
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(time=at(0)), span(), terminated(time=at(30)))

    root = next(s for s in sink.spans if s.span_id == ROOT)
    assert root.trace_id == TRACE
    assert root.parent_span_id is None
    assert (root.start_time, root.end_time) == (at(0), at(30))


@pytest.mark.asyncio
async def test_a_top_level_node_is_reparented_onto_the_run_s_root() -> None:
    """The PAYOFF of synthesising the root. `_trace_fields` omits `tracestate` when the parent
    IS the root, so a top-level node arrives claiming no parent. Emitting it that way renders
    one run as N disconnected traces in the UI — the waterfall never forms."""
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(), span("b" * 16), terminated())

    node = next(s for s in sink.spans if s.span_id == "b" * 16)
    assert node.parent_span_id == ROOT


@pytest.mark.asyncio
async def test_an_explicit_parent_is_left_alone() -> None:
    """Reparenting must apply ONLY to the implicit case; overwriting a stated `url4.parent`
    would flatten every nested run into a single level."""
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(), span("c" * 16, parent="b" * 16), terminated())

    node = next(s for s in sink.spans if s.span_id == "c" * 16)
    assert node.parent_span_id == "b" * 16


@pytest.mark.asyncio
async def test_the_root_itself_is_not_reparented_onto_itself() -> None:
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(), terminated())

    assert sink.spans[-1].parent_span_id is None, "the root must not be its own parent"


@pytest.mark.asyncio
async def test_the_root_is_emitted_last_so_it_bounds_its_children() -> None:
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(), span(), terminated())

    assert sink.spans[-1].span_id == ROOT


@pytest.mark.asyncio
async def test_a_stopped_run_is_distinguishable_from_a_failed_one_on_the_root() -> None:
    """`SpanData.status` is only ok|error — `cancelled` is collapsed before publication, so a
    stopped run looks failed in the child spans. `TerminatedData.status` keeps all four, so the
    ROOT is where that distinction survives."""
    stopped, failed = FakeSink(), FakeSink()

    await drive(SpanRelay(Recorder(), stopped), started(), terminated("stopped"))
    await drive(SpanRelay(Recorder(), failed), started(), terminated("failed"))

    assert stopped.spans[-1].status != failed.spans[-1].status


@pytest.mark.asyncio
async def test_a_run_that_never_terminated_emits_no_root_rather_than_an_open_one() -> None:
    """A hard-killed run (OOM, eviction) publishes no terminal frame. Its root has no end, and
    D11's rule applies to the root exactly as to a node."""
    inner, sink = Recorder(), FakeSink()

    await drive(SpanRelay(inner, sink), started(), span())

    assert [s.span_id for s in sink.spans] == ["a" * 16]


# --- lifecycle ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_shuts_the_sink_down_exactly_once() -> None:
    """Ledger D10: the run process is short-lived, so an unflushed batch loses the tail of
    EVERY trace — including the root, which is by definition emitted last."""
    relay = SpanRelay(Recorder(), (sink := FakeSink()))

    await drive(relay, started(), span(), terminated())
    relay.shutdown()
    relay.shutdown()

    assert sink.closed == 1


@pytest.mark.asyncio
async def test_leaving_the_context_closes_the_sink_even_when_the_run_raised() -> None:
    """The composition root drives this with `with`, so a run that dies mid-flight still
    flushes. A run that RAISED is exactly the one whose trace someone will go looking for."""
    sink = FakeSink()

    with pytest.raises(RuntimeError):
        with SpanRelay(Recorder(), sink) as relay:
            await drive(relay, started(), span())
            raise RuntimeError("the run blew up")

    assert sink.closed == 1


@pytest.mark.asyncio
async def test_no_sink_means_the_relay_is_a_plain_passthrough() -> None:
    """Ledger D9: with no endpoint configured there is no sink, and the relay must cost
    nothing — this is what keeps every existing run and every test unaffected."""
    inner = Recorder()
    relay = SpanRelay(inner, None)

    await drive(relay, started(), span(), terminated())
    relay.shutdown()

    assert len(inner.frames) == 3
