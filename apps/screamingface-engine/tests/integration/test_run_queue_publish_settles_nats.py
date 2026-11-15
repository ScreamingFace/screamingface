"""A lost publish acknowledgement against a real broker (OME-1859).

The broker stores a run whose acknowledgement was lost, and acknowledges the retry with the
same `Nats-Msg-Id` without storing a second copy. This drops the first acknowledgement after the
broker stored the run and checks the runner counts the run once and the stream holds it once.
Run by CI's NATS job; skipped wherever no NATS is reachable.
"""

import contextlib
import os
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import nats.errors
import pytest

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.runner_queue import PublishOutcomeUnknown, RunQueue, RunQueueUnavailable
from url4.streaming.interfaces import JobRunnerAtCapacity

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")
CALLER = {"X-User-Email": "a@example.com"}


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


class _NoTail:
    """The runner's event-stream reads: no run in this test has a frame yet."""

    async def last_frame(self, topic: str) -> Any:
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _NoControl:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError


async def _drop_first_ack(queue: RunQueue) -> list[Any]:
    """Make the queue's first publish reach the broker and lose its acknowledgement, as a
    timeout after the broker stored the message does. Returns the acknowledgements seen."""
    js = await queue._jetstream()  # noqa: SLF001
    real_publish = js.publish
    acks: list[Any] = []

    async def _ack_lost_once(*args: Any, **kwargs: Any) -> Any:
        ack = await real_publish(*args, **kwargs)
        acks.append(ack)
        if len(acks) == 1:
            raise nats.errors.TimeoutError  # the broker stored it; its answer never arrived
        return ack

    js.publish = _ack_lost_once  # type: ignore[method-assign]
    return acks


async def test_a_lost_acknowledgement_counts_the_run_once_and_stores_it_once() -> None:
    # A fresh stream per run: the assertions are the stream's exact depth.
    prefix = f"it-settle-{uuid4().hex}"
    queue = RunQueue(
        NATS_URL, subject_prefix=prefix, stream=prefix, replicas=1, state_cache_ttl_s=0.0
    )
    runner = QueueJobRunner(
        queue=queue,
        publisher=_NoTail(),
        control=_NoControl(),
        clock=lambda: datetime.now(UTC),
        capability_lifetime_s=58_800,
        caller_inflight_cap=1,
        state_cache_ttl_s=0.0,
    )
    topic = f"{prefix}-run"
    try:
        await queue.ensure_stream()
        acks = await _drop_first_ack(queue)

        with pytest.raises(RunQueueUnavailable) as caught:
            await runner.schedule(topic, "'hi'", 60, identity=CALLER)
        # The lost acknowledgement reads as an unknown outcome: the attempt is held.
        assert isinstance(caught.value.__cause__, PublishOutcomeUnknown)
        assert [hold.topic for hold in runner._held] == [topic]  # noqa: SLF001
        assert await queue.depth() == 1  # stored, though the start answered 503
        with pytest.raises(JobRunnerAtCapacity):  # and counted against the cap of 1
            await runner.schedule(f"{prefix}-other", "'hi'", 60, identity=CALLER)

        await runner.schedule(topic, "'hi'", 60, identity=CALLER)  # the Client's retry

        assert acks[1].duplicate is True
        assert await queue.depth() == 1
        assert await runner.status(topic) == "scheduled"
        # Counted once: the held first attempt adds nothing beside the landed retry.
        assert runner._cap_count(CALLER["X-User-Email"], "another-topic") == 1  # noqa: SLF001
    finally:
        # A setup failure may leave no stream; the cleanup must not hide that failure.
        with contextlib.suppress(nats.errors.Error):
            js_cleanup = await queue._jetstream()  # noqa: SLF001
            await js_cleanup.delete_stream(prefix)
        await queue.close()
