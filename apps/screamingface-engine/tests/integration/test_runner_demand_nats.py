"""Plan test 7 — `bucket_readings()` + `claimable_demand()` against a real broker: the consumer
splits running from waiting runs, and a capped bucket's held-back runs add no demand.

Broker behavior (consumer ack state read back with `consumer_info`), so this belongs beside
the roundtrip tests: exercised against the real broker, skipped wherever none is reachable —
see `test_run_queue_roundtrip.py`.
"""

import contextlib
import os
import socket
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest
from nats.js.api import AckPolicy, ConsumerConfig

from screamingface_engine.runner_demand import RunnerDemand, claimable_demand
from screamingface_engine.runner_queue import QUEUE_CONSUMER, BucketReading, RunQueue

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


def _consumer_name(subject: str) -> str:
    # Mirrors the private `_consumer_for` in runner_queue: one durable consumer per bucket.
    return f"{QUEUE_CONSUMER}-{subject.rsplit('.', 1)[-1]}"


async def test_held_back_runs_of_a_capped_bucket_are_not_claimable() -> None:  # noqa: PLR0915
    """Bucket A has a cap of 4 and 6 runs: 4 are delivered and held un-acked (running), 2 wait
    behind the cap. Bucket C has no cap-hit and 2 waiting runs. The readings must split the
    two states per bucket, and the 2 queued runs behind A's cap must add no claimable demand.
    """
    prefix = f"it-demand-{uuid4().hex}"
    queue = RunQueue(NATS_URL, stream=prefix, subject_prefix=prefix, replicas=1)
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    try:
        await queue.ensure_stream()
        subjects = queue.bucket_subjects()
        a, c = subjects[0], subjects[2]
        for subject in (a, c):
            await js.add_consumer(
                prefix,
                config=ConsumerConfig(
                    durable_name=_consumer_name(subject),
                    filter_subject=subject,
                    ack_policy=AckPolicy.EXPLICIT,
                    max_ack_pending=4,
                ),
            )
        for i in range(6):
            await js.publish(a, b"run", headers={"Nats-Msg-Id": f"{prefix}-a-{i}"})
        for i in range(2):
            await js.publish(c, b"run", headers={"Nats-Msg-Id": f"{prefix}-c-{i}"})

        sub = await js.pull_subscribe_bind(durable=_consumer_name(a), stream=prefix)
        held = await sub.fetch(4, timeout=5)
        assert len(held) == 4  # delivered, NOT acked: these are 'running'

        readings = await queue.bucket_readings()
        assert readings[0] == BucketReading(running=4, queued=2, max_ack_pending=4)
        assert readings[2] == BucketReading(running=0, queued=2, max_ack_pending=4)
        assert readings[1] is None
        assert sum(reading is None for reading in readings) == 14
        # A's 2 queued runs sit behind its cap: no pod can claim them, so they add no demand.
        assert claimable_demand(readings) == RunnerDemand(
            demand=6, running=4, claimable=2, queued=4, unbound_buckets=14
        )
    finally:
        with contextlib.suppress(Exception):
            await js.delete_stream(prefix)
        await nc.close()
        await queue.close()
