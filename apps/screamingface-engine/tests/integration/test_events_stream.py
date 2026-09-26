"""Shared events stream (uniform executor, PRD 01) against a real JetStream.

Every run's frames live on subject `url4-cloud.<topic>` of ONE stream. The frame sequence the
client sees is the PRODUCER sequence, gap-free per topic (erd.md §5, I-EV1..I-EV4).
"""

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest

from screamingface_engine.adapters.jetstream import JetStreamConsumer, JetStreamPublisher
from screamingface_engine.testing.mock_runner import publish_mock_run
from url4.streaming.protocol import OutboundFrame, TerminatedData, TerminatedEvent
from url4.streaming.protocol.envelope import source_for

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")


def _nats_reachable(url: str = NATS_URL) -> bool:
    parsed = urlsplit(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _nats_reachable(),
        reason=f"needs a reachable NATS at {NATS_URL} (set URL4_CLOUD_TEST_NATS_URL)",
    ),
]

EXPR = "(gpt,claude)!'hi'"
MOCK_FRAME_COUNT = 11


def _topic(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


async def _take(consumer: JetStreamConsumer, topic: str, n: int, **kw: object) -> list[OutboundFrame]:
    frames: list[OutboundFrame] = []

    async def _read() -> None:
        stream: AsyncIterator[OutboundFrame] = consumer.subscribe(topic, **kw)  # type: ignore[arg-type]
        async for frame in stream:
            frames.append(frame)
            if len(frames) == n:
                return

    await asyncio.wait_for(_read(), timeout=10.0)
    return frames


def _seqs(frames: list[OutboundFrame]) -> list[int]:
    return [int(f.sequence or 0) for f in frames]


async def test_frame_sequence_on_wire_equals_producer_sequence_for_fresh_run() -> None:
    """EVT-C1 (CHAR): for a run with one writer on a fresh topic, the sequence a subscriber
    sees is 1..n, the same numbers the url4 producer stamped."""
    topic = _topic("evt-c1")
    publisher = JetStreamPublisher(NATS_URL)
    consumer = JetStreamConsumer(NATS_URL)
    try:
        await publish_mock_run(publisher, topic, EXPR)
        await publisher.flush()
        frames = await _take(consumer, topic, MOCK_FRAME_COUNT)
        assert _seqs(frames) == list(range(1, MOCK_FRAME_COUNT + 1))
        assert isinstance(frames[-1], TerminatedEvent)
    finally:
        await publisher.close()
        await consumer.close()
