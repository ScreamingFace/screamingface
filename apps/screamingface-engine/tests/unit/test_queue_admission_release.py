"""The runner observes its own finished runs before refusing a caller (OME-1108).

A caller was permanently locked out by runs that finished long ago. Observed live: an
evaluation of 7 candidates had 1 accepted and 7 refused with "the runner is at capacity" while
`url4-runq` held ZERO messages, every consumer sat at `pending=0/ack_pending=0`, and the worker
reported 0 of 4 slots busy. The App still held the 8 reservations admitted ~23 minutes earlier.

A reservation was released only by `status()` observing a terminal frame — and `status()` is
reached only from the pre-schedule 409 check and the orphan reaper, never from the WebSocket
path the SDK actually uses — or by `_prune()` at `capability_lifetime_s`, 16.3 hours. With the
reaper disabled there was no background release at all, so the cap counted history.

INVARIANT under test: the cap must count what is RUNNING, not what once ran. The runner now
re-reads the terminal frames of a caller's in-flight topics before refusing it, and only
refuses if the slots are genuinely still held.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from nats.errors import ConnectionClosedError

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from url4.streaming.interfaces import JobRunnerAtCapacity
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 3, 15, 0, 0, tzinfo=UTC)
CALLER: Mapping[str, str] = {"X-User-Email": "caller@example.com"}
OTHER: Mapping[str, str] = {"X-User-Email": "other@example.com"}


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _Queue:
    def __init__(self, *, depth: int = 0) -> None:
        self._depth = depth
        self.published: list[bytes] = []

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return self._depth

    async def oldest_age(self) -> float | None:
        return None


def _terminated(topic: str, when: datetime) -> TerminatedEvent:
    """A terminal frame stamped `when` — the time matters: `_forget_in_flight` ignores a frame
    older than a reservation, which is what stops a prior run's frame freeing a live slot."""
    return TerminatedEvent(
        id=f"term-{topic}",
        source=source_for(topic),
        time=when,
        data=TerminatedData(status="succeeded"),
    )


class _Publisher:
    """Per-topic scripted tails, counting reads so the zero-cost property is assertable."""

    def __init__(self) -> None:
        self.tails: dict[str, Any] = {}
        self.unreadable: set[str] = set()
        self.reads: list[str] = []
        self.published: list[Any] = []

    async def last_frame(self, topic: str) -> Any:
        self.reads.append(topic)
        if topic in self.unreadable:
            raise QueueReadError(f"unreadable {topic}")
        return self.tails.get(topic)

    async def stream_exists(self, topic: str) -> bool:
        return True

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


def _runner(
    queue: _Queue,
    publisher: _Publisher,
    clock: _Clock,
    *,
    cap: int = 3,
    **kwargs: Any,
) -> QueueJobRunner:
    return QueueJobRunner(
        queue=queue,
        publisher=publisher,
        control=_Control(),
        clock=clock,
        capability_lifetime_s=58_800.0,
        depth_ceiling=1000,
        caller_inflight_cap=cap,
        **kwargs,
    )


async def _fill_to_cap(runner: QueueJobRunner, cap: int, identity: Mapping[str, str]) -> list[str]:
    topics = [f"t-{i}" for i in range(cap)]
    for topic in topics:
        await runner.schedule(topic, "'hi'", 60, identity=identity)
    return topics


async def test_a_caller_whose_runs_all_finished_is_admitted_not_refused() -> None:
    """THE incident. Every run this caller holds has a terminal frame, the queue is empty and
    the pool is idle — admitting is the only honest answer."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=3)
    topics = await _fill_to_cap(runner, 3, CALLER)

    clock.advance(600)
    for topic in topics:
        publisher.tails[topic] = _terminated(topic, clock.now)

    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    assert len(queue.published) == 4, "the fourth run must reach the queue, not a 503"


async def test_a_caller_whose_runs_are_live_is_still_refused() -> None:
    """The cap must keep working: no terminal frames means the slots are genuinely held."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=3)
    await _fill_to_cap(runner, 3, CALLER)

    with pytest.raises(JobRunnerAtCapacity) as raised:
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    assert raised.value.limit == 3


async def test_only_the_finished_runs_free_their_slots() -> None:
    """A partially finished caller is admitted, and the cap still counts the live ones."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=3)
    topics = await _fill_to_cap(runner, 3, CALLER)

    clock.advance(600)
    publisher.tails[topics[0]] = _terminated(topics[0], clock.now)

    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)
    # One slot was freed and immediately taken, so the caller is at the cap again.
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-newer", "'hi'", 60, identity=CALLER)


async def test_an_unreadable_tail_never_frees_a_slot() -> None:
    """Unknown is not terminal. A broker blip must not hand out a slot that may still be held —
    the same discipline `status()` applies."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)
    topics = await _fill_to_cap(runner, 2, CALLER)
    publisher.unreadable.update(topics)

    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)


async def test_a_stale_frame_from_a_prior_run_does_not_free_the_live_slot() -> None:
    """A re-scheduled topic still shows its FIRST run's terminal frame. Releasing on that
    sighting would free the SECOND run's slot — `_forget_in_flight`'s guard, exercised through
    the new release path."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)

    await runner.schedule("t-reused", "'hi'", 60, identity=CALLER)
    stale = _terminated("t-reused", clock.now)
    clock.advance(60)
    publisher.tails["t-reused"] = stale
    # Re-scheduled AFTER that frame: the second run is live and the frame cannot speak for it.
    await runner.schedule("t-reused", "'hi'", 60, identity=CALLER)

    clock.advance(1)
    # The FIRST reservation is genuinely finished, so its slot is freed and this is admitted.
    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    # ...but the LIVE second reservation must have survived the same stale frame, so the
    # caller is at its cap again. If the guard were absent, both would have been released
    # and this would be admitted too.
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-newer", "'hi'", 60, identity=CALLER)


async def test_a_caller_below_its_cap_costs_no_broker_reads() -> None:
    """The zero-cost property: the sweep runs only when a refusal is imminent, so the happy
    path is exactly as cheap as before."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=8)

    await runner.schedule("t-0", "'hi'", 60, identity=CALLER)
    await runner.schedule("t-1", "'hi'", 60, identity=CALLER)

    assert publisher.reads == []


async def test_one_callers_finished_runs_do_not_free_anothers_slots() -> None:
    """The sweep is scoped to the caller being judged; it must not touch a sibling's accounting."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2)
    await _fill_to_cap(runner, 2, CALLER)
    await runner.schedule("o-0", "'hi'", 60, identity=OTHER)

    clock.advance(600)
    publisher.tails["t-0"] = _terminated("t-0", clock.now)
    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    assert "o-0" not in publisher.reads, "another caller's topics must not be swept"


async def test_a_reservation_older_than_the_lease_is_released() -> None:
    """The backstop: when the broker cannot be read at all, a slot must still not outlive its
    run by the 16.3h capability lifetime."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reservation_lease_s=300.0)
    topics = await _fill_to_cap(runner, 2, CALLER)
    publisher.unreadable.update(topics)

    clock.advance(301)
    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    assert len(queue.published) == 3


async def test_a_reservation_within_the_lease_still_holds_its_slot() -> None:
    """The lease is a backstop, not a timer that quietly lifts the cap."""
    queue, publisher, clock = _Queue(), _Publisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reservation_lease_s=300.0)
    topics = await _fill_to_cap(runner, 2, CALLER)
    publisher.unreadable.update(topics)

    clock.advance(100)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)


# --- reclaimed streams: absence is evidence, not unknown --------------------------------------
#
# THE DEFECT in the release path above. `run_and_reclaim` deletes each run's stream in a
# `finally`, `DEFAULT_STREAM_GRACE_S` (60s) after the run ends — deliberate, because a leaked
# per-run stream holds a full `max_bytes` reservation until the store fills and every new run
# fails with JetStream 10047. Once the stream is gone the terminal frame is gone with it, so
# `_read_tail` can NEVER answer `TerminatedEvent` for a run that finished more than ~60s ago:
# the terminal-frame release is unreachable for exactly the runs that matter, leaving only the
# 1h lease. Confirmed on a live kind cluster — identical 8 runs, same caller, idle pool, the
# only variable being whether the 9th submission landed inside the 60s grace window:
#
#   [immediate]      ADMITTED  <- streams still exist, the terminal-frame release fires
#   [after-deletion] REFUSED   <- "the runner is at capacity", queue_depth 0.0, pool idle
#
# A missing stream is NOT unknown: `delete_stream` runs strictly AFTER the run is over, so
# absence is positive evidence of reclamation. The gate is the reservation's AGE — a topic
# admitted a moment ago may have no stream YET.


class _ReclaimingPublisher(_Publisher):
    """`_Publisher` with a SCRIPTABLE stream existence, which the base fake hardcodes to True.

    `absent` is a stream the broker does not have — either RECLAIMED (`run_and_reclaim` deleted
    it a grace period after the run ended) or NOT CREATED YET. Note it does NOT go through
    `unreadable`: the real `JetStreamPublisher.last_frame` maps a missing stream to None, because
    `get_last_msg` raises `NotFoundError`, which IS an `APIError`, and that branch returns None
    while `QueueReadError` is reserved for transport failures.
    """

    def __init__(self) -> None:
        super().__init__()
        self.absent: set[str] = set()
        self.exists_unreadable: set[str] = set()
        self.exists_checks: list[str] = []

    def reclaim(self, topic: str) -> None:
        """What `run_and_reclaim` leaves behind: the terminal frame is gone WITH the stream, so
        the tail reads None and the stream no longer exists."""
        self.tails.pop(topic, None)
        self.absent.add(topic)

    async def stream_exists(self, topic: str) -> bool:
        self.exists_checks.append(topic)
        if topic in self.exists_unreadable:
            # The real adapter does NOT translate this: `_stream_exists` returns False only for
            # `NotFoundError` and lets every other failure propagate, so a blip surfaces raw.
            raise ConnectionClosedError()
        return topic not in self.absent


async def test_a_caller_whose_finished_runs_were_reclaimed_is_admitted() -> None:
    """THE incident, after the streams were reclaimed. No terminal frame survives, so only the
    stream's ABSENCE can say the runs are over — and it must."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=3)
    topics = await _fill_to_cap(runner, 3, CALLER)

    clock.advance(600)
    for topic in topics:
        publisher.reclaim(topic)

    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    assert len(queue.published) == 4, "a reclaimed run must not hold its slot for the whole lease"


async def test_a_freshly_admitted_topic_with_no_stream_yet_keeps_its_slot() -> None:
    """The startup race. Between admission and the stream's creation the tail reads None and the
    stream is absent — identical to a reclaimed run. Releasing there would let a caller exceed
    its cap, so absence only counts once the reservation is older than the reclaim threshold."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reclaim_evidence_after_s=90.0)
    topics = await _fill_to_cap(runner, 2, CALLER)
    publisher.absent.update(topics)

    clock.advance(5)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)


async def test_absence_frees_the_slot_only_past_the_reclaim_threshold() -> None:
    """The same absent streams, either side of the threshold: held below it, released above."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reclaim_evidence_after_s=90.0)
    topics = await _fill_to_cap(runner, 2, CALLER)
    publisher.absent.update(topics)

    clock.advance(89)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    clock.advance(2)
    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)
    assert len(queue.published) == 3


async def test_an_unreadable_stream_check_never_frees_a_slot() -> None:
    """The invariant, extended to the second broker call the absence check adds: `stream_exists`
    failing is UNKNOWN, and unknown must never hand out a slot that may still be held."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reclaim_evidence_after_s=90.0)
    topics = await _fill_to_cap(runner, 2, CALLER)
    publisher.exists_unreadable.update(topics)

    clock.advance(600)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)


async def test_an_empty_but_present_stream_keeps_its_slot() -> None:
    """A queued run that has not published yet: the tail is None but the stream EXISTS. Only
    absence is evidence — an empty stream says the run has not started, not that it ended."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reclaim_evidence_after_s=90.0)
    await _fill_to_cap(runner, 2, CALLER)

    clock.advance(600)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)


async def test_absence_does_not_free_a_re_scheduled_topics_live_slot() -> None:
    """The stale-sighting guard, on the absence path. A topic re-scheduled after its first run
    was reclaimed still reads "absent" — that absence belongs to the FIRST run, and must not
    release the SECOND run's reservation, whose stream simply does not exist yet."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reclaim_evidence_after_s=90.0)

    await runner.schedule("t-reused", "'hi'", 60, identity=CALLER)
    clock.advance(600)
    publisher.reclaim("t-reused")
    # Re-scheduled now: the second run is live, and its own stream is still absent.
    await runner.schedule("t-reused", "'hi'", 60, identity=CALLER)

    clock.advance(1)
    # The FIRST reservation is older than the threshold, so its slot is freed and this fits.
    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    # ...but the LIVE second reservation is younger than the threshold and must have survived.
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-newer", "'hi'", 60, identity=CALLER)


async def test_a_young_reservation_costs_no_stream_check() -> None:
    """The cost discipline: the extra round trip happens only when a reservation is old enough
    for absence to mean anything, so the common refusal is as cheap as before."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reclaim_evidence_after_s=90.0)
    await _fill_to_cap(runner, 2, CALLER)

    clock.advance(5)
    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    assert publisher.exists_checks == [], "a young reservation needs no absence check"


async def test_a_terminal_frame_still_costs_no_stream_check() -> None:
    """The terminal-frame release stays the primary path: when the frame is there, the absence
    check is not reached at all."""
    queue, publisher, clock = _Queue(), _ReclaimingPublisher(), _Clock()
    runner = _runner(queue, publisher, clock, cap=2, reclaim_evidence_after_s=90.0)
    topics = await _fill_to_cap(runner, 2, CALLER)

    clock.advance(600)
    for topic in topics:
        publisher.tails[topic] = _terminated(topic, clock.now)

    await runner.schedule("t-new", "'hi'", 60, identity=CALLER)

    assert publisher.exists_checks == []
