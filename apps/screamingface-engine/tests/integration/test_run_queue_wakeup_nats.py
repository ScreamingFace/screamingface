"""The run queue's wake-up (OME-1091 F6): a publish (or a `release_held`) nudges an idle
pull instead of leaving it to wait out a blind rotation.

Broker behavior (a core-NATS pub/sub outside the JetStream stream), so this belongs beside
the roundtrip tests: exercised against the real broker, skipped wherever none is reachable —
see `test_run_queue_roundtrip.py`.
"""

import asyncio
import os
import socket
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from screamingface_engine.runner_queue import PULL_FAST_PASS_S, RunQueue, encode_message

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


def _unique_prefix(name: str) -> str:
    # A fresh stream AND subject prefix per test: the queue is a SINGLETON stream by name,
    # and these tests care about exact pull TIMING against an otherwise-empty queue, which a
    # shared default stream (carrying whatever other tests or runs left behind) cannot give.
    return f"it-wake-{name}-{uuid4().hex}"


async def test_a_message_published_into_an_idle_pull_is_claimed_at_once() -> None:
    """The wake-up's whole point: a pull started against an EMPTY queue, already past its
    fast pass and sitting in the wake wait, claims a message the moment it is published —
    not on its next blind rotation, and not by re-sweeping every bucket either (the
    targeted pass, OME-1091 F6's design review follow-up): the claim latency this test
    bounds is tight enough (< 0.3s) that a full 16-bucket rotation would not fit it.

    No `PULL_FAST_PASS_S` monkeypatch: this runs against the REAL 1.0s fast pass, so the
    sleep below must clear it with room to spare, or the publish could land while the
    fast pass (not the wake wait) is still running and this test would tell the two
    apart by accident rather than by construction.
    """
    prefix = _unique_prefix("claim")
    worker = RunQueue(NATS_URL, subject_prefix=prefix, stream=prefix, replicas=1)
    app = RunQueue(NATS_URL, subject_prefix=prefix, stream=prefix, replicas=1)
    try:
        await worker.ensure_stream()
        pull_task = asyncio.create_task(worker.pull(1, timeout_s=5.0))
        await asyncio.sleep(PULL_FAST_PASS_S + 0.2)  # past the fast pass, into the wake wait

        message = encode_message("it-wake-claim", "'hi'", 60)
        publish_started = time.monotonic()
        await app.publish(message)

        pulled = await pull_task
        claim_latency = time.monotonic() - publish_started

        assert len(pulled) == 1
        assert claim_latency < 0.3, f"claimed in {claim_latency:.3f}s, not < 0.3s"
    finally:
        await worker.close()
        await app.close()


async def test_without_a_wake_the_pull_still_ends_at_its_timeout() -> None:
    """No publish ever arrives: the pull must still return empty-handed at its timeout —
    the wake wait's `asyncio.wait_for` deadline, not an indefinite block on a wake that
    never comes."""
    prefix = _unique_prefix("silent")
    queue = RunQueue(NATS_URL, subject_prefix=prefix, stream=prefix, replicas=1)
    try:
        await queue.ensure_stream()
        started = time.monotonic()
        pulled = await queue.pull(1, timeout_s=1.0)
        elapsed = time.monotonic() - started

        assert pulled == []
        assert 0.9 <= elapsed <= 1.5, f"took {elapsed:.3f}s"
    finally:
        await queue.close()
