"""`url4.run`'s parent is the span that accepted the run (OME-1218, option 1).

`lifecycle.run` adopts the handed trace id but mints its own root span id and drops the handed
parent-id, so the wire never states it. The relay is therefore TOLD what the run was handed,
and parents the synthetic root to it — within the same trace only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from screamingface_engine.tracing.relay import ROOT_SPAN_NAME, SpanRelay
from screamingface_engine.tracing.span_tree import Span
from url4.streaming.interfaces import EventPublisher
from url4.streaming.protocol import (
    OutboundFrame,
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
ROOT = "00f067aa0ba902b7"
ACCEPT = "b7ad6b7169203331"
TOPIC = "t"
T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


class Null(EventPublisher):
    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        return None


class FakeSink:
    def __init__(self) -> None:
        self.spans: list[Span] = []

    def emit(self, span: Span) -> None:
        self.spans.append(span)

    def close(self) -> None:
        return None


def _started() -> StartedEvent:
    return StartedEvent(
        id="e1",
        source=source_for(TOPIC, "root"),
        time=T0,
        subject=TOPIC,
        sequence="1",
        traceparent=f"00-{TRACE}-{ROOT}-01",
        data=StartedData(url4="x"),
    )


def _terminated() -> TerminatedEvent:
    return TerminatedEvent(
        id="e2",
        source=source_for(TOPIC, "root"),
        time=T0 + timedelta(seconds=1),
        subject=TOPIC,
        sequence="2",
        traceparent=f"00-{TRACE}-{ROOT}-01",
        data=TerminatedData(status="succeeded"),
    )


async def _run(handed: str | None) -> Span:
    sink = FakeSink()
    relay = SpanRelay(Null(), sink, traceparent=handed)
    await relay.publish(TOPIC, _started())
    await relay.publish(TOPIC, _terminated())
    (root,) = [s for s in sink.spans if s.name == ROOT_SPAN_NAME]
    return root


@pytest.mark.asyncio
async def test_the_run_root_is_a_child_of_the_span_it_was_handed() -> None:
    root = await _run(f"00-{TRACE}-{ACCEPT}-01")

    assert root.span_id == ROOT
    assert root.parent_span_id == ACCEPT


@pytest.mark.asyncio
async def test_a_handed_parent_from_another_trace_is_never_adopted() -> None:
    """A parent pointer into a different trace dangles in every backend — worse than none."""
    root = await _run(f"00-{'1' * 32}-{ACCEPT}-01")

    assert root.parent_span_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("handed", [None, "garbage", f"00-{TRACE}-{'0' * 16}-01"])
async def test_with_nothing_usable_handed_the_run_root_stays_parentless(
    handed: str | None,
) -> None:
    root = await _run(handed)

    assert root.parent_span_id is None
