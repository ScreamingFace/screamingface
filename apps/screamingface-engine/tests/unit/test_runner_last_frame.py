"""E5 P2 spec §4.4 and R7: the job runner reads a topic's newest frame.

FEATURE: a detached Run (OME-1837). The driver settles a Candidate whose run ended but whose
outcome never arrived from that frame.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from url4.streaming.interfaces import Executor
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio

TOPIC = "t-last"


def _terminated(status: Any = "succeeded") -> TerminatedEvent:
    return TerminatedEvent(
        id="e1",
        source=source_for(TOPIC),
        subject=TOPIC,
        time=datetime(2026, 11, 12, tzinfo=UTC),
        data=TerminatedData(status=status),
    )


async def test_the_in_memory_stream_reads_the_newest_frame() -> None:
    stream = InMemoryEventStream()
    assert await stream.last_frame(TOPIC) is None

    await stream.publish(TOPIC, _terminated("failed"))

    frame = await stream.last_frame(TOPIC)
    assert isinstance(frame, TerminatedEvent)
    assert frame.data.status == "failed"


async def test_the_in_process_runner_reads_its_stream() -> None:
    stream = InMemoryEventStream()

    def factory(env: Mapping[str, str]) -> Executor:
        raise AssertionError("no run is started")

    runner = InProcessJobRunner(stream, factory)
    await stream.publish(TOPIC, _terminated())

    assert isinstance(await runner.last_frame(TOPIC), TerminatedEvent)


class _Publisher:
    def __init__(self, frame: Any) -> None:
        self.frame = frame

    async def last_frame(self, topic: str) -> Any:
        return self.frame

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: Any) -> None:
        return None

    async def flush(self) -> None:
        return None


class _Queue:
    async def publish(
        self, message: bytes, *, identity: Any = None, enqueued_at: Any = None
    ) -> None:
        return None

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


async def test_the_queue_runner_reads_the_events_stream() -> None:
    frame = _terminated()
    runner = QueueJobRunner(
        queue=_Queue(),
        publisher=_Publisher(frame),
        control=_Control(),
        clock=lambda: datetime(2026, 11, 12, tzinfo=UTC),
        capability_lifetime_s=60,
        depth_ceiling=10,
        caller_inflight_cap=8,
    )

    assert await runner.last_frame(TOPIC) is frame
