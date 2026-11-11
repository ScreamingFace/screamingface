"""The queue depth against a real broker: unclaimed runs, not held messages
(docs/spec/2026-11-10-queue-depth-unclaimed.md).

FEATURE: an honest queue depth for admission, `Retry-After` and `/metrics`.

The whole measurement is broker behavior — what `num_pending` excludes, what
`delivered.stream_seq` points at, whether `next_by_subj` finds the first WAITING message, and
where a NAK'd message is counted — so the unit suite's fake can only pin the calls. This file
pins the broker. Skipped wherever no NATS is reachable; the CI `conformance` job runs it
against `nats:2.10` and fails on a skip.

Layout: three buckets on a stream of this test's own (so nothing another test left in
`url4-runq` can leak in). Bucket A (`.00`) and C (`.02`) have a durable consumer bound the way
a worker binds it (`max_ack_pending=4`); bucket B (`.01`) has none — the cold-start case.
"""

import asyncio
import contextlib
import os
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.errors import NotFoundError

from screamingface_engine.runner_queue import (
    BucketReading,
    RunQueue,
    _consumer_for,
    _work_queue_consumer_config,
)

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


@contextlib.asynccontextmanager
async def _stack() -> AsyncIterator[tuple[RunQueue, JetStreamContext, str]]:
    name = f"it-unclaimed-{uuid4().hex[:12]}"
    # TTL 0: every read in these tests must see the broker as it is NOW.
    queue = RunQueue(
        NATS_URL,
        stream=name,
        subject_prefix=name,
        bucket_count=3,
        replicas=1,
        state_cache_ttl_s=0.0,
    )
    # The test plays the WORKER with its own connection: the queue under test must only
    # ever read.
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    try:
        await queue.ensure_stream()
        yield queue, js, name
    finally:
        try:
            await js.delete_stream(name)
        except NotFoundError:
            pass
        await nc.close()
        await queue.close()


async def _bind(js: JetStreamContext, subject: str) -> JetStreamContext.PullSubscription:
    """Bind a bucket consumer exactly as a worker does (`RunQueue._bound_subscription`)."""
    return await js.pull_subscribe(
        subject,
        durable=_consumer_for(subject),
        stream=subject.rsplit(".", 1)[0],
        config=_work_queue_consumer_config(ack_wait_s=60.0, max_deliver=2, max_ack_pending=4),
    )


async def _publish(js: JetStreamContext, subject: str, count: int) -> list[datetime]:
    """Publish `count` messages and return each one's broker timestamp, in order."""
    stamps: list[datetime] = []
    for _ in range(count):
        ack = await js.publish(subject, b"run", headers={"Nats-Msg-Id": uuid4().hex})
        msg = await js.get_msg(subject.rsplit(".", 1)[0], seq=ack.seq)
        assert msg.time is not None
        stamps.append(msg.time)
        # Distinct timestamps, so "the 5th message" and "the 1st" are told apart.
        await asyncio.sleep(0.05)
    return stamps


async def test_running_runs_are_held_but_not_unclaimed() -> None:
    """6 runs to A, 2 to C; a worker takes 4 of A's and runs them. The stream holds 8, the
    backlog is 4 (A's 2 + C's 2), and the oldest WAITING run is A's 5th message."""
    async with _stack() as (queue, js, name):
        a, b, c = (f"{name}.{i:02x}" for i in range(3))
        sub_a = await _bind(js, a)
        await _bind(js, c)
        stamps_a = await _publish(js, a, 6)
        await _publish(js, c, 2)
        # A worker takes 4 of A's runs (its `max_ack_pending`) and does not ack: they RUN.
        running = await sub_a.fetch(4, timeout=5.0)
        assert len(running) == 4

        assert await queue.held() == 8
        assert await queue.depth() == 4
        assert await queue.bucket_readings() == [
            BucketReading(running=4, queued=2, max_ack_pending=4),
            None,  # B: no consumer bound yet
            BucketReading(running=0, queued=2, max_ack_pending=4),
        ]
        # The 1st message is running and must not count, however old it is.
        age = await queue.oldest_age()
        assert age is not None
        assert age == pytest.approx((datetime.now(UTC) - stamps_a[4]).total_seconds(), abs=0.5)
        assert age < (datetime.now(UTC) - stamps_a[0]).total_seconds() - 0.1

        # Cold start (spec D2): a run in a bucket no worker has bound yet still waits.
        await _publish(js, b, 1)
        assert await queue.depth() == 5
        assert await queue.held() == 9

        await _nak_keeps_running_and_ack_removes(queue, running)


async def _nak_keeps_running_and_ack_removes(queue: RunQueue, running: list[Msg]) -> None:
    # Spec D4: a NAK'd run stays counted as RUNNING (the broker keeps it ack-pending until it
    # is redelivered) — it neither joins the backlog nor becomes its head.
    await running[0].nak()
    await asyncio.sleep(0.3)
    readings = await queue.bucket_readings()
    assert readings[0] == BucketReading(running=4, queued=2, max_ack_pending=4)
    assert await queue.depth() == 5

    # An ack removes a run from the stream (WorkQueue) and from "running".
    for msg in running[1:]:
        await msg.ack()
    await asyncio.sleep(0.3)
    assert await queue.held() == 6
    readings = await queue.bucket_readings()
    assert readings[0] == BucketReading(running=1, queued=2, max_ack_pending=4)


async def test_the_depth_reading_never_binds_a_consumer() -> None:
    """Spec D1: only workers bind consumers, with THEIR `max_ack_pending`. A read on an
    unbound queue must leave it unbound."""
    async with _stack() as (queue, js, name):
        await _publish(js, f"{name}.01", 2)

        assert await queue.depth() == 2
        assert await queue.oldest_age() is not None
        assert await queue.bucket_readings() == [None, None, None]

        info = await js.stream_info(name)
        assert info.state.consumer_count == 0
