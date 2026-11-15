"""`JetStreamPublisher.dropped`: whether this publisher dropped a run's frames because the
subject had already ended (OME-1785, E5 P1 spec R3)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from nats.js import api

from screamingface_engine.adapters.jetstream import JetStreamPublisher
from url4.streaming.protocol import (
    LogData,
    LogEvent,
    OutboundFrame,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

pytestmark = pytest.mark.asyncio

TOPIC = "t-dropped"


def _publisher(tail: OutboundFrame | None) -> JetStreamPublisher:
    publisher = JetStreamPublisher("nats://unused:4222")

    async def _tail(topic: str) -> tuple[int, OutboundFrame | None]:
        return (0 if tail is None else 1), tail

    class _JetStream:
        async def publish_async(self, *args: Any, **kwargs: Any) -> Any:
            future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
            future.set_result(object())
            return future

    async def _jetstream() -> _JetStream:
        return _JetStream()

    publisher._tail = _tail  # type: ignore[method-assign]
    publisher._jetstream = _jetstream  # type: ignore[assignment,method-assign]
    return publisher


def _first_frame() -> LogEvent:
    return LogEvent(
        sequence="1",
        id="e1",
        source=source_for(TOPIC),
        subject=TOPIC,
        data=LogData.at("INFO", "hello"),
    )


async def test_a_run_whose_subject_had_ended_is_dropped() -> None:
    """A queued-cancel tombstone won the race against the claim: nothing may follow it."""
    tombstone = TerminatedEvent(
        id="x", source=source_for(TOPIC), subject=TOPIC, data=TerminatedData(status="stopped")
    )
    publisher = _publisher(tombstone)

    await publisher.publish(TOPIC, _first_frame())

    assert publisher.dropped(TOPIC)


async def test_a_run_on_a_fresh_subject_is_not_dropped() -> None:
    publisher = _publisher(None)

    await publisher.publish(TOPIC, _first_frame())

    assert not publisher.dropped(TOPIC)


async def test_a_topic_this_publisher_never_saw_is_not_dropped() -> None:
    assert not JetStreamPublisher("nats://unused:4222").dropped(TOPIC)


def _terminal(sequence: str) -> TerminatedEvent:
    return TerminatedEvent(
        sequence=sequence,
        id="t",
        source=source_for(TOPIC),
        subject=TOPIC,
        data=TerminatedData(status="succeeded"),
    )


async def _publish_run(*, terminal_duplicate: bool) -> JetStreamPublisher:
    publisher = _publisher(None)

    class _JetStream:
        async def publish_async(self, *args: Any, **kwargs: Any) -> Any:
            body = args[1]
            duplicate = terminal_duplicate and b"ai.url4.terminated" in body
            future: asyncio.Future[api.PubAck] = asyncio.get_running_loop().create_future()
            future.set_result(api.PubAck(stream="s", seq=2, duplicate=duplicate))
            return future

    async def _jetstream() -> _JetStream:
        return _JetStream()

    publisher._jetstream = _jetstream  # type: ignore[assignment,method-assign]
    await publisher.publish(TOPIC, _first_frame())
    await publisher.publish(TOPIC, _terminal("2"))
    await publisher.flush()
    return publisher


async def test_a_terminal_another_writer_beat_mid_run_is_dropped() -> None:
    """WHY: a queued cancel wrote `stopped` at sequence 2 first; the broker answers this run's
    terminal, sent under the same id, with a duplicate ack and stores nothing."""
    assert (await _publish_run(terminal_duplicate=True)).dropped(TOPIC)


async def test_a_terminal_that_landed_is_not_dropped() -> None:
    assert not (await _publish_run(terminal_duplicate=False)).dropped(TOPIC)
