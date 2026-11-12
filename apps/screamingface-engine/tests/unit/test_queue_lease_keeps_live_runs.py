"""The reservation lease never frees a queued or running run (OME-1880, #1744 review).

A caller's slot was freed one hour after admission whatever the run was doing: the lease
counted from admission, not from the last evidence. A run waits in the queue behind its
bucket's `max_ack_pending` and then runs up to its deadline (16 h), so with the cap at 24 and
`max_ack_pending` at 4, the 20 waiting runs lost their slots after an hour and the same caller
could admit 24 more, hour after hour.

INVARIANT under test: a durably queued run whose readable tail has no terminal frame keeps its
slot past the lease. The lease still frees what observation cannot speak for: an unreadable
tail, and a re-start the broker deduplicated into a run that had already ended. The capability
lifetime still bounds every slot.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.runner_queue import DEFAULT_RESERVATION_LEASE_S
from url4.streaming.interfaces import JobRunnerAtCapacity
from url4.streaming.protocol import (
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
    source_for,
)

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 12, 9, 0, 0, tzinfo=UTC)
CALLER: Mapping[str, str] = {"X-User-Email": "caller@example.com"}
LEASE_S = DEFAULT_RESERVATION_LEASE_S
CAPABILITY_LIFETIME_S = 58_800.0


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _Queue:
    def __init__(self) -> None:
        self.published: list[bytes] = []

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None, enqueued_at: Any = None
    ) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _Publisher:
    """Per-topic scripted tails; an absent topic is a readable, empty subject (a queued run)."""

    def __init__(self) -> None:
        self.tails: dict[str, Any] = {}
        self.unreadable: set[str] = set()

    async def last_frame(self, topic: str) -> Any:
        if topic in self.unreadable:
            raise QueueReadError(f"unreadable {topic}")
        return self.tails.get(topic)

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


def _runner(queue: _Queue, publisher: _Publisher, clock: _Clock, *, cap: int) -> QueueJobRunner:
    return QueueJobRunner(
        queue=queue,
        publisher=publisher,
        control=_Control(),
        clock=clock,
        capability_lifetime_s=CAPABILITY_LIFETIME_S,
        depth_ceiling=1000,
        caller_inflight_cap=cap,
    )


def _terminated(topic: str, when: datetime) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"term-{topic}",
        source=source_for(topic),
        time=when,
        data=TerminatedData(status="succeeded"),
    )


def _started(topic: str, when: datetime) -> StartedEvent:
    return StartedEvent(
        id=f"start-{topic}", source=source_for(topic), time=when, data=StartedData(url4="'hi'")
    )


async def _fill(runner: QueueJobRunner, count: int) -> list[str]:
    topics = [f"t-{i}" for i in range(count)]
    for topic in topics:
        await runner.schedule(topic, "'hi'", 57_600, identity=CALLER)
    return topics


async def test_queued_runs_older_than_the_lease_keep_the_cap() -> None:
    """The review's case: 24 admitted, nothing ended, an hour later the 25th is refused."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=24)
    await _fill(runner, 24)

    clock.advance(LEASE_S + 1)
    with pytest.raises(JobRunnerAtCapacity) as raised:
        await runner.schedule("t-25", "'hi'", 57_600, identity=CALLER)

    assert raised.value.limit == 24
    assert len(queue.published) == 24


async def test_the_cap_holds_for_hours_not_one_lease() -> None:
    """Each later hour is refused too: the cap does not grow by one cap per lease."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=3)
    await _fill(runner, 3)

    for hour in range(1, 6):
        clock.now = T0 + timedelta(hours=hour, seconds=1)
        with pytest.raises(JobRunnerAtCapacity):
            await runner.schedule(f"t-late-{hour}", "'hi'", 57_600, identity=CALLER)

    assert len(queue.published) == 3


async def test_a_running_run_older_than_the_lease_keeps_its_slot() -> None:
    """A tail whose last frame is not terminal is a running run: its slot stays."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)
    topics = await _fill(runner, 2)
    for topic in topics:
        publisher.tails[topic] = _started(topic, T0 + timedelta(minutes=5))

    clock.advance(3 * LEASE_S)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 57_600, identity=CALLER)


async def test_a_long_run_frees_its_slot_when_it_ends() -> None:
    """Past the lease, the run's own terminal frame is what frees the slot."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)
    topics = await _fill(runner, 2)

    clock.advance(3 * LEASE_S)
    publisher.tails[topics[0]] = _terminated(topics[0], clock.now)
    await runner.schedule("t-new", "'hi'", 57_600, identity=CALLER)

    assert len(queue.published) == 3


async def test_an_unreadable_tail_still_ends_at_the_lease() -> None:
    """The OME-1108 backstop is unchanged for a run the broker cannot show."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)
    topics = await _fill(runner, 2)
    publisher.unreadable.add(topics[0])

    clock.advance(LEASE_S + 1)
    await runner.schedule("t-new", "'hi'", 57_600, identity=CALLER)

    assert len(queue.published) == 3


async def test_a_restart_of_an_ended_run_still_ends_at_the_lease() -> None:
    """A re-start the broker deduplicated into an ended run sees only the older terminal
    frame. Observation cannot free it (the frame predates it), so the lease does, as before."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)
    await _fill(runner, 1)
    publisher.tails["t-0"] = _terminated("t-0", T0 + timedelta(minutes=1))
    clock.advance(120)
    await runner.schedule("t-0", "'hi'", 57_600, identity=CALLER)  # the re-start
    await runner.schedule("t-1", "'hi'", 57_600, identity=CALLER)

    clock.advance(LEASE_S - 60)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-2", "'hi'", 57_600, identity=CALLER)

    clock.advance(120)
    await runner.schedule("t-2", "'hi'", 57_600, identity=CALLER)

    assert len(queue.published) == 4


async def test_the_capability_lifetime_still_bounds_a_live_slot() -> None:
    """A run that never shows an end cannot hold its slot past the capability lifetime."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)
    await _fill(runner, 2)

    clock.advance(CAPABILITY_LIFETIME_S + 1)
    await runner.schedule("t-new", "'hi'", 57_600, identity=CALLER)

    assert len(queue.published) == 3
