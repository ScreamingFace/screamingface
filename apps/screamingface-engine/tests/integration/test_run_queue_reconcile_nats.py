"""Raising a live consumer's `max_ack_pending` keeps in-flight runs pending (OME-1314).

FEATURE: a runner rollout with a new `runnerPool.maxAckPending` applies to the existing queue
consumer in place (spec 2026-11-10-per-user-parallel-runs D2/F1). Runs a worker already holds
stay pending and are not redelivered; the new cap admits more runs at once.

The unit file pins the calls; this file pins the broker. Skipped wherever no NATS is reachable;
the CI `conformance` job runs it against `nats:2.10` and fails on a skip.
"""

import contextlib
import os
import socket
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest
from nats.js.errors import NotFoundError

from screamingface_engine.runner_queue import RunQueue, _consumer_for, _work_queue_consumer_config

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


async def test_raising_the_cap_keeps_running_runs_and_admits_more() -> None:  # noqa: PLR0915
    name = f"it-reconcile-{uuid4().hex[:12]}"
    subject = f"{name}.00"
    old = RunQueue(
        NATS_URL,
        stream=name,
        subject_prefix=name,
        bucket_count=1,
        replicas=1,
        max_ack_pending=4,
    )
    new: RunQueue | None = None
    # The test plays the WORKER with its own connection.
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    try:
        await old.ensure_stream()
        sub = await js.pull_subscribe(
            subject,
            durable=_consumer_for(subject),
            stream=name,
            config=_work_queue_consumer_config(ack_wait_s=60.0, max_deliver=3, max_ack_pending=4),
        )
        for _ in range(6):
            await js.publish(subject, b"run", headers={"Nats-Msg-Id": uuid4().hex})

        running = await sub.fetch(4, timeout=5.0)
        assert len(running) == 4  # held, not acked

        new = RunQueue(
            NATS_URL,
            stream=name,
            subject_prefix=name,
            bucket_count=1,
            replicas=1,
            max_ack_pending=24,
        )
        assert await new.reconcile_consumers() == 1

        info = await js.consumer_info(name, _consumer_for(subject))
        assert info.config.max_ack_pending == 24
        assert info.num_ack_pending == 4
        assert (info.num_redelivered or 0) == 0
        assert info.config.ack_wait == 60.0
        assert info.config.max_deliver == 3

        more = await sub.fetch(2, timeout=5.0)
        assert len(more) == 2
        assert all(m.metadata.num_delivered == 1 for m in more)

        assert await new.reconcile_consumers() == 0
    finally:
        with contextlib.suppress(NotFoundError):
            await js.delete_stream(name)
        await nc.close()
        await old.close()
        if new is not None:
            await new.close()
