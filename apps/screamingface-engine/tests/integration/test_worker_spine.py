"""The worker spine against a real broker (OME-1089): submit → claim → spawn → frames →
terminal.

The queue's whole contract is broker behavior, and the worker's claim/ack path is broker
behavior too, so this file is where the real NATS broker is exercised end to end: a run is
published to the queue, a real worker claims it, spawns a real child (a fake
``screamingface-engine`` on PATH that publishes its own frames through the real
``JetStreamPublisher``), and the run's stream ends in the child's terminal frame with the
message acked. Skipped wherever no NATS is reachable, like the other real-broker tests.
"""

import asyncio
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from screamingface_engine.adapters.jetstream import JetStreamConsumer, JetStreamPublisher
from screamingface_engine.runner_queue import RunQueue, encode_message
from screamingface_engine.worker.loop import Worker
from url4.streaming.protocol import StartedEvent, TerminatedEvent

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
    # A fresh topic per run: the broker's dedupe window is time-based, so a topic published
    # by an earlier test run must not collide with this run's assertions.
    return f"{prefix}-{uuid4().hex}"


# The child the worker forks: a fake `screamingface-engine` that publishes its own frames
# through the REAL `JetStreamPublisher` and exits 0 — the same shape as the real run
# entrypoint, without needing a gateway. Runs with the venv python (the shebang is written
# by the test), so the engine package is importable.
_FAKE_RUNNER = """\
import asyncio
import os
import uuid
from datetime import UTC, datetime

from screamingface_engine.adapters.jetstream import JetStreamPublisher
from url4.streaming.protocol import (
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
    source_for,
)


async def _main() -> None:
    topic = os.environ["URL4_CLOUD_TOPIC"]
    publisher = JetStreamPublisher(
        os.environ.get("URL4_CLOUD_NATS_URL", "nats://localhost:4222")
    )
    await publisher.ensure_stream(topic)
    await publisher.publish(
        topic,
        StartedEvent(
            id=uuid.uuid4().hex,
            source=source_for(topic),
            subject=topic,
            time=datetime.now(UTC),
            data=StartedData(url4="'hi'"),
        ),
    )
    await publisher.publish(
        topic,
        TerminatedEvent(
            id=uuid.uuid4().hex,
            source=source_for(topic),
            subject=topic,
            time=datetime.now(UTC),
            data=TerminatedData(status="succeeded"),
        ),
    )
    await publisher.flush()
    await publisher.close()


asyncio.run(_main())
"""


async def _read_until_terminal(consumer: JetStreamConsumer, topic: str) -> list[object]:
    frames: list[object] = []
    async for frame in consumer.subscribe(topic):
        frames.append(frame)
        if isinstance(frame, TerminatedEvent):
            return frames
    return frames


async def _wait_for_depth(queue: RunQueue, expected: int, timeout_s: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        if await queue.depth() == expected:
            return
        if loop.time() > deadline:
            raise AssertionError(f"queue depth never reached {expected}")
        await asyncio.sleep(0.1)


def _install_fake_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a fake `screamingface-engine` on PATH that publishes its own frames through the
    real `JetStreamPublisher` and exits 0 — the child the worker forks."""
    fake = tmp_path / "screamingface-engine"
    fake.write_text(f"#!{sys.executable}\n{_FAKE_RUNNER}")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("URL4_CLOUD_NATS_URL", NATS_URL)


async def test_submit_claim_spawn_frames_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run published to the queue is claimed by a real worker, forked as a child, and the
    run's stream ends in the child's own terminal frame with the message acked."""
    _install_fake_runner(tmp_path, monkeypatch)

    queue = RunQueue(NATS_URL, state_cache_ttl_s=0.0, replicas=1)
    await queue.ensure_stream()
    topic = _unique_topic("it-worker")
    await queue.publish(encode_message(topic, "'hi'", 60))

    publisher = JetStreamPublisher(NATS_URL)
    worker = Worker(
        queue=queue,
        publisher=publisher,
        slots=1,
        drain_grace_s=1.0,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        pull_timeout_s=0.5,
    )
    consumer = JetStreamConsumer(NATS_URL)
    try:
        async with asyncio.TaskGroup() as tg:
            claim = tg.create_task(worker._claim_loop(tg))
            frames = await asyncio.wait_for(_read_until_terminal(consumer, topic), timeout=15.0)
            claim.cancel()

        # The TaskGroup has exited, so the supervisor has acked the message: the queue is
        # empty again.
        await _wait_for_depth(queue, 0)
    finally:
        await consumer.close()
        await publisher.close()
        await queue.close()

    # The child's own frames, in order: Started, then its terminal frame. The worker added
    # nothing — a clean exit with the child's terminal frame on the stream.
    assert isinstance(frames[0], StartedEvent)
    assert isinstance(frames[-1], TerminatedEvent)
    assert frames[-1].data.status == "succeeded"
    assert len(frames) == 2
