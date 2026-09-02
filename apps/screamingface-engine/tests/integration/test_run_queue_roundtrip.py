"""The run queue against a real broker (OME-1088): publish → pull → ack.

The queue's whole contract is broker behavior — `Nats-Msg-Id` dedupe, WorkQueue retention,
EXPLICIT acks — so the unit suite (fake JetStream) can only pin the calls; this file is where
the broker itself is exercised. Skipped wherever no NATS is reachable, exactly like the
conformance parameters in `tests/unit/_fakes.py`.
"""

import asyncio
import os
import socket
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from screamingface_engine.runner_queue import RunQueue, decode_message, encode_message
from url4.streaming.protocol import CachePolicy

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")


def _nats_reachable(url: str = NATS_URL) -> bool:
    parsed = urlsplit(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


NATS_AVAILABLE = _nats_reachable()

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not NATS_AVAILABLE,
        reason=f"needs a reachable NATS at {NATS_URL} (set URL4_CLOUD_TEST_NATS_URL)",
    ),
]


def _unique_topic(prefix: str) -> str:
    # A fresh topic per run: the broker's dedupe window is time-based, so a topic published by
    # an earlier test run (or a crashed one) must not collide with this run's assertions.
    return f"{prefix}-{uuid4().hex}"


async def _wait_for_depth(queue: RunQueue, expected: int, timeout_s: float = 5.0) -> None:
    """Poll `depth` until it reaches `expected`.

    WHY poll rather than assert once: `Msg.ack()` is fire-and-forget in nats-py — it writes the
    ack to the connection and returns, so a `depth()` read microseconds later can still see the
    message the broker has not yet removed. The ack is eventually consistent; the assertion is
    that it lands, not that it lands instantly.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        if await queue.depth() == expected:
            return
        if loop.time() > deadline:
            raise AssertionError(f"queue depth never reached {expected}")
        await asyncio.sleep(0.1)


async def test_publish_pull_ack_round_trip() -> None:
    # One replica: a single-node broker refuses `replicas > 1` (the CI conformance broker is
    # single-node too). The 3-replica property is pinned by the unit suite; the behavior this
    # test exercises is replicas-independent.
    queue = RunQueue(NATS_URL, state_cache_ttl_s=0.0, replicas=1)
    try:
        await queue.ensure_stream()
        topic = _unique_topic("it-roundtrip")
        message = encode_message(
            topic,
            "'hi'!'go'",
            60,
            traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            profile="p1",
            identity={"X-User-Email": "a@b.c"},
            cache=CachePolicy(participate=True, max_age=300),
            io_concurrency=7,
        )

        await queue.publish(message)

        pulled = await queue.pull(1, timeout_s=5.0)
        assert len(pulled) == 1
        assert decode_message(pulled[0].data) == decode_message(message)
        await pulled[0].ack()

        await _wait_for_depth(queue, 0)
    finally:
        await queue.close()


async def test_duplicate_publish_yields_exactly_one_message() -> None:
    """A retried submission of one topic is ONE run: the broker's dedupe window collapses the
    second publish into the first, so the queue never holds two copies."""
    queue = RunQueue(NATS_URL, state_cache_ttl_s=0.0, replicas=1)
    try:
        await queue.ensure_stream()
        topic = _unique_topic("it-dedupe")
        message = encode_message(topic, "'hi'", 60)

        await queue.publish(message)
        await queue.publish(message)  # the retry

        assert await queue.depth() == 1

        pulled = await queue.pull(1, timeout_s=5.0)
        assert len(pulled) == 1
        await pulled[0].ack()
        await _wait_for_depth(queue, 0)
    finally:
        await queue.close()
