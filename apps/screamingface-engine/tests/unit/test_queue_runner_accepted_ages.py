"""`QueueJobRunner.accepted_ages()`: how long ago this replica durably accepted each run.

FEATURE: warn the client about an unclaimed queued run (under OME-1086). The unclaimed-run
warner reads this snapshot to find runs that have waited past its grace. It is the runner's
existing schedule-time record (`_scheduled_at`, the capability-validity input), not a new store.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import nats.errors
import pytest

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.runner_queue import RunQueueUnavailable

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)
LIFETIME_S = 100.0


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class _Queue:
    def __init__(self) -> None:
        self.fail = False

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        if self.fail:
            raise nats.errors.TimeoutError()

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _Publisher:
    async def last_frame(self, topic: str) -> Any:
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


def _runner(queue: _Queue, clock: _Clock) -> QueueJobRunner:
    return QueueJobRunner(
        queue=queue,
        publisher=_Publisher(),
        control=_Control(),
        clock=clock,
        capability_lifetime_s=LIFETIME_S,
    )


async def test_nothing_is_accepted_before_the_first_schedule() -> None:
    assert _runner(_Queue(), _Clock()).accepted_ages() == {}


async def test_the_age_follows_the_runner_clock() -> None:
    clock = _Clock()
    runner = _runner(_Queue(), clock)

    await runner.schedule("t1", "'hi'", 60)
    clock.now += timedelta(seconds=30)
    await runner.schedule("t2", "'hi'", 60)
    clock.now += timedelta(seconds=12.5)

    assert runner.accepted_ages() == {"t1": 42.5, "t2": 12.5}


async def test_a_run_that_was_never_durably_queued_is_not_accepted() -> None:
    """INVARIANT: a failed publish leaves no record — the warner must never tell a client
    "your run is queued" about a run that is not in the queue."""
    queue = _Queue()
    queue.fail = True
    runner = _runner(queue, _Clock())

    with pytest.raises(RunQueueUnavailable):
        await runner.schedule("t", "'hi'", 60)

    assert runner.accepted_ages() == {}


async def test_the_snapshot_is_a_copy_the_caller_cannot_mutate_into_the_runner() -> None:
    runner = _runner(_Queue(), _Clock())
    await runner.schedule("t", "'hi'", 60)

    runner.accepted_ages().clear()

    assert "t" in runner.accepted_ages()
