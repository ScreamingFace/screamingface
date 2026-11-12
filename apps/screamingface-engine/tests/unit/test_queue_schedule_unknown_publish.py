"""A run-queue publish whose outcome is unknown keeps its caller's slot (OME-1859).

FEATURE: per-caller admission on the run queue (OME-1091) under first-class Runs (OME-1785).
STORY: as a caller whose start hit a broker hiccup, the run I may already have queued counts
against my in-flight cap, and my retry of that start counts once.

INVARIANT (spec `docs/spec/2026-11-10-jetstream-publish-unknown-outcome.md`): an outcome the
runner cannot know never frees a slot; only a failure that proves nothing was stored does.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import nats.errors
import nats.js.errors
import pytest

from screamingface_engine import job_env
from screamingface_engine.adapters.queue_runner import (
    _HELD_SLOT_SLACK_S,
    _WORKER_KILL_MARGINS_S,
    QueueJobRunner,
)
from screamingface_engine.ports import StoppedBeforeSchedule
from screamingface_engine.runner_queue import (
    PublishOutcomeUnknown,
    RunQueueUnavailable,
    decode_message,
    encode_message,
    topic_of_message,
)
from screamingface_engine.worker.supervisor import DEADLINE_MARGIN_S, KILL_GRACE_S
from url4.streaming.interfaces import JobRunnerAtCapacity
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
CALLER: Mapping[str, str] = {"X-User-Email": "a@example.com"}
OTHER: Mapping[str, str] = {"X-User-Email": "b@example.com"}
A_KEY = "a@example.com"
B_KEY = "b@example.com"
LEASE_S = 3600.0
SHORT_S = 60  # a short, direct-run-like deadline: its hold ends long before the lease
LONG_S = 57_600  # a hosted run's 16 h deadline: the lease bounds its hold
SHORT_HOLD_S = 2 * SHORT_S + _HELD_SLOT_SLACK_S

# Failures that prove nothing was stored. A plain timeout comes before the send:
# `RunQueue.publish` raises `PublishOutcomeUnknown` from the send alone.
DEFINITE = [
    pytest.param(nats.errors.TimeoutError(), id="timeout-before-the-send"),
    pytest.param(nats.errors.NoServersError(), id="no-servers"),
    pytest.param(nats.errors.ConnectionClosedError(), id="closed-before-send"),
    pytest.param(nats.js.errors.ServiceUnavailableError(), id="jetstream-503"),
    pytest.param(nats.js.errors.NoStreamResponseError(), id="no-stream-responder"),
]


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class _Queue:
    """The slice of `RunQueue` the runner uses. Publish call N first waits on `gate(N)` when one
    was set up, then raises what `fail_next` scripted for it, or lands."""

    def __init__(self) -> None:
        self.calls = 0
        self.published: list[bytes] = []
        self._script: dict[int, BaseException] = {}
        self._gates: dict[int, asyncio.Event] = {}

    def fail_next(self, error: BaseException) -> None:
        self._script[self.calls] = error

    def gate(self, call: int) -> asyncio.Event:
        return self._gates.setdefault(call, asyncio.Event())

    async def publishing(self, calls: int) -> None:
        for _ in range(100):
            if self.calls >= calls:
                return
            await asyncio.sleep(0)
        raise AssertionError(f"only {self.calls} of {calls} publishes started")

    async def publish(
        self, message: bytes, *, identity: Mapping[str, str] | None = None, enqueued_at: Any = None
    ) -> None:
        call = self.calls
        self.calls += 1
        if call in self._gates:
            await self._gates[call].wait()
        error = self._script.pop(call, None)
        if error is not None:
            raise error
        self.published.append(message)

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _Publisher:
    def __init__(self) -> None:
        self.tails: dict[str, Any] = {}
        self.frames: list[tuple[str, Any]] = []

    async def last_frame(self, topic: str) -> Any:
        return self.tails.get(topic)

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any, **_: Any) -> None:
        self.frames.append((topic, event))

    async def flush(self) -> None:
        pass


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


def _runner(
    queue: _Queue,
    publisher: _Publisher | None = None,
    clock: _Clock | None = None,
    **kwargs: Any,
) -> QueueJobRunner:
    settings: dict[str, Any] = {
        "capability_lifetime_s": 58_800,
        "caller_inflight_cap": 1,
        "state_cache_ttl_s": 0.0,
        "reservation_lease_s": LEASE_S,
    }
    return QueueJobRunner(
        queue=queue,
        publisher=publisher or _Publisher(),
        control=_Control(),
        clock=clock or _Clock(),
        **(settings | kwargs),
    )


def _terminated(topic: str, when: datetime) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"term-{topic}",
        source=source_for(topic),
        time=when,
        data=TerminatedData(status="succeeded"),
    )


async def _schedule(
    runner: QueueJobRunner,
    topic: str,
    identity: Mapping[str, str] = CALLER,
    deadline_s: int = SHORT_S,
) -> str:
    return await runner.schedule(topic, "'hi'", deadline_s, identity=identity)


async def _held(
    runner: QueueJobRunner,
    topic: str = "t1",
    identity: Mapping[str, str] = CALLER,
    deadline_s: int = SHORT_S,
) -> None:
    """Leave `topic` held: its publish times out after the broker may have stored it."""
    runner._queue.fail_next(PublishOutcomeUnknown())  # type: ignore[attr-defined]  # noqa: SLF001
    with pytest.raises(RunQueueUnavailable):
        await _schedule(runner, topic, identity, deadline_s)


def _cap(runner: QueueJobRunner, caller: str = A_KEY) -> int:
    """How many slots the caller's cap counts it holding, as another topic's start sees it."""
    return runner._cap_count(caller, "t-other")  # noqa: SLF001


def _holds(runner: QueueJobRunner) -> list[tuple[str, str]]:
    return sorted((hold.caller, hold.topic) for hold in runner._held)  # noqa: SLF001


# --- D1/D2: an unknown outcome holds the slot; a definite failure frees it ---------------------


async def test_an_unknown_outcome_keeps_the_callers_slot() -> None:
    queue = _Queue()
    error = PublishOutcomeUnknown()
    queue.fail_next(error)
    runner = _runner(queue)

    with pytest.raises(RunQueueUnavailable) as caught:
        await _schedule(runner, "t1")

    assert caught.value.__cause__ is error
    # No `scheduled` record: the run's status comes from stream evidence alone.
    assert await runner.status("t1") == "not_found"
    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t2")


@pytest.mark.parametrize("error", DEFINITE)
async def test_a_definite_failure_frees_the_slot(error: Exception) -> None:
    queue = _Queue()
    queue.fail_next(error)
    runner = _runner(queue)

    with pytest.raises(RunQueueUnavailable):
        await _schedule(runner, "t1")

    await _schedule(runner, "t2")
    assert [topic_of_message(m) for m in queue.published] == ["t2"]
    assert _holds(runner) == []


async def test_a_cancel_mid_publish_keeps_the_slot_and_its_retry_counts_once() -> None:
    queue = _Queue()
    queue.gate(0)
    runner = _runner(queue)
    start = asyncio.create_task(_schedule(runner, "t1"))
    await queue.publishing(1)

    start.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start
    assert await runner.status("t1") == "not_found"
    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t2")
    await _schedule(runner, "t1")
    assert _cap(runner) == 1


# --- D3: the cap counts a held start once, so a retry is counted once ----------------------


async def test_a_retry_is_admitted_past_its_own_hold_and_counted_once() -> None:
    runner = _runner(_Queue())
    await _held(runner)

    # At a cap of 1 the retry is admitted: its held first attempt is this same run.
    await _schedule(runner, "t1")

    assert await runner.status("t1") == "scheduled"
    assert _cap(runner) == 1
    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t2")


async def test_a_retry_that_fails_outright_keeps_the_first_attempts_hold() -> None:
    """The retry's definite failure releases its own reservation; the first stays held."""
    queue = _Queue()
    runner = _runner(queue)
    await _held(runner)

    queue.fail_next(nats.errors.NoServersError())
    with pytest.raises(RunQueueUnavailable):
        await _schedule(runner, "t1")

    assert _holds(runner) == [(A_KEY, "t1")]
    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t2")


async def test_attempts_of_one_start_hold_one_slot_however_many_time_out() -> None:
    """Three timed-out attempts of one start are at most one run, so they take one slot."""
    runner = _runner(_Queue(), caller_inflight_cap=3)
    for _ in range(3):
        await _held(runner)

    await _schedule(runner, "t2")
    await _schedule(runner, "t3")

    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t4")


async def test_concurrent_attempts_of_one_topic_are_bounded_by_the_cap() -> None:
    """Live attempts count one each, so duplicate starts in flight cannot pass the cap."""
    queue = _Queue()
    gates = [queue.gate(0), queue.gate(1)]
    runner = _runner(queue, caller_inflight_cap=2)
    attempts = [asyncio.create_task(_schedule(runner, "t1")) for _ in gates]
    await queue.publishing(2)

    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t1")

    for gate in gates:
        gate.set()
    await asyncio.gather(*attempts)


async def test_a_landed_retrys_reservation_counts_from_the_retry() -> None:
    """The retry lands 55 min after the held attempt; its own reservation counts the run, so
    the lease does not free the slot five minutes later."""
    clock = _Clock()
    runner = _runner(_Queue(), clock=clock)
    await _held(runner, deadline_s=LONG_S)

    clock.now = T0 + timedelta(minutes=55)
    await _schedule(runner, "t1", deadline_s=LONG_S)
    clock.now = T0 + timedelta(minutes=61)

    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t2")
    assert _cap(runner) == 1


async def test_a_hold_beside_a_landed_attempt_adds_nothing() -> None:
    """The retry lands while the first publish hangs; the first's late timeout is held, but the
    landed attempt alone counts the topic."""
    queue = _Queue()
    queue.fail_next(PublishOutcomeUnknown())
    first_gate, retry_gate = queue.gate(0), queue.gate(1)
    runner = _runner(queue, caller_inflight_cap=8)
    first = asyncio.create_task(_schedule(runner, "t1"))
    retry = asyncio.create_task(_schedule(runner, "t1"))
    await queue.publishing(2)

    retry_gate.set()
    await retry
    first_gate.set()
    with pytest.raises(RunQueueUnavailable):
        await first

    assert _holds(runner) == [(A_KEY, "t1")]
    assert _cap(runner) == 1


async def test_a_retry_admitted_as_its_hold_runs_out_is_still_counted() -> None:
    """The first hold runs out while the retry publishes; the retry's own reservation counts."""
    queue = _Queue()
    clock = _Clock()
    runner = _runner(queue, clock=clock, caller_inflight_cap=8)
    await _held(runner)
    retry_gate = queue.gate(1)
    clock.now = T0 + timedelta(seconds=SHORT_HOLD_S - 1)
    retry = asyncio.create_task(_schedule(runner, "t1"))
    await queue.publishing(2)

    clock.now = T0 + timedelta(seconds=SHORT_HOLD_S + 1)
    await _schedule(runner, "t9", identity=OTHER)  # its admission prunes the expired hold
    retry_gate.set()
    await retry

    assert _holds(runner) == []
    assert _cap(runner) == 1


async def test_each_callers_hold_of_one_topic_is_its_own() -> None:
    """Each caller holds its own attempt of a shared topic; another caller's landing keeps it."""
    runner = _runner(_Queue())
    await _held(runner, identity=CALLER)
    await _held(runner, identity=OTHER)

    await _schedule(runner, "t1", identity=OTHER)  # B's retry lands

    assert _holds(runner) == [(A_KEY, "t1"), (B_KEY, "t1")]
    assert (_cap(runner), _cap(runner, B_KEY)) == (1, 1)


async def test_a_retry_that_meets_a_stop_marker_leaves_the_first_attempts_hold() -> None:
    """A stop's marker precedes its tombstone, which can fail: the retry's reservation is
    released, the first attempt stays held."""
    runner = _runner(_Queue(), caller_inflight_cap=8)
    await _held(runner)
    admit = runner._admit_or_raise  # noqa: SLF001

    async def _stop_lands_during_admission(*args: Any) -> Any:
        admitted = await admit(*args)
        runner._stopped_before_schedule["t1"] = T0  # noqa: SLF001
        return admitted

    runner._admit_or_raise = _stop_lands_during_admission  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(StoppedBeforeSchedule):
        await _schedule(runner, "t1")

    assert _holds(runner) == [(A_KEY, "t1")]
    assert _cap(runner) == 1


# --- D4: what frees a held slot ---------------------------------------------------------------


async def test_the_runs_terminal_frame_frees_a_held_slot() -> None:
    publisher = _Publisher()
    clock = _Clock()
    runner = _runner(_Queue(), publisher, clock)
    await _held(runner)

    # The stored run executed and ended.
    clock.now = T0 + timedelta(minutes=1)
    publisher.tails["t1"] = _terminated("t1", clock.now)

    await _schedule(runner, "t2")
    assert _cap(runner) == 1  # t2 alone


async def test_a_stops_tombstone_frees_the_held_slot_once_observed() -> None:
    """A Run cancel's tombstone is the run's terminal frame: observed at the cap, it frees the
    hold, and the retry meets the marker."""
    publisher = _Publisher()
    runner = _runner(_Queue(), publisher)
    await _held(runner)

    await runner.stop_bound("t1")

    assert [(topic, frame.data.status) for topic, frame in publisher.frames] == [("t1", "stopped")]
    publisher.tails["t1"] = publisher.frames[0][1]
    await _schedule(runner, "t2")
    assert _cap(runner) == 1  # t2 alone
    with pytest.raises(StoppedBeforeSchedule):
        await _schedule(runner, "t1")


async def test_a_plain_stop_of_a_held_topic_writes_nothing() -> None:
    """The runner never recorded the run as scheduled, so a plain stop writes no tombstone and
    the hold stays."""
    publisher = _Publisher()
    runner = _runner(_Queue(), publisher)
    await _held(runner)

    await runner.stop("t1")

    assert publisher.frames == []
    assert _holds(runner) == [(A_KEY, "t1")]


async def test_an_unknown_outcome_after_a_stop_marked_the_topic_is_still_held() -> None:
    """A stop's marker alone frees nothing (its tombstone can fail); the tombstone, once seen,
    does."""
    queue = _Queue()
    queue.fail_next(PublishOutcomeUnknown())
    gate = queue.gate(0)
    publisher = _Publisher()
    clock = _Clock()
    runner = _runner(queue, publisher, clock)
    start = asyncio.create_task(_schedule(runner, "t1"))
    await queue.publishing(1)

    await runner.stop_bound("t1")
    gate.set()

    with pytest.raises(RunQueueUnavailable):
        await start
    assert _holds(runner) == [(A_KEY, "t1")]
    clock.now = T0 + timedelta(seconds=1)
    publisher.tails["t1"] = publisher.frames[0][1]
    await _schedule(runner, "t2")
    assert _cap(runner) == 1  # t2 alone


async def test_a_held_slot_ends_once_the_run_can_no_longer_exist() -> None:
    """A short run's hold ends at twice its deadline plus the slack, not at the lease."""
    clock = _Clock()
    runner = _runner(_Queue(), clock=clock)
    await _held(runner, deadline_s=SHORT_S)

    clock.now = T0 + timedelta(seconds=SHORT_HOLD_S - 1)
    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t2")
    clock.now = T0 + timedelta(seconds=SHORT_HOLD_S)
    await _schedule(runner, "t2")

    assert _holds(runner) == []
    assert _cap(runner) == 1


async def test_two_holds_of_one_topic_each_end_on_their_own() -> None:
    """Two callers' holds of one topic each end at their own `until`."""
    clock = _Clock()
    runner = _runner(_Queue(), clock=clock)
    await _held(runner, identity=CALLER, deadline_s=SHORT_S)
    await _held(runner, identity=OTHER, deadline_s=LONG_S)

    clock.now = T0 + timedelta(seconds=SHORT_HOLD_S)
    await _schedule(runner, "t2")

    assert _holds(runner) == [(B_KEY, "t1")]


async def test_a_stale_hold_after_observation_does_not_hide_a_live_attempt() -> None:
    """Observation at the cap can drop a held token whose run ended. A hold counts only while
    its token is present, or a live attempt would read as held and a second pass the cap."""
    queue = _Queue()
    publisher = _Publisher()
    clock = _Clock()
    runner = _runner(queue, publisher, clock)
    await _held(runner)
    clock.now = T0 + timedelta(minutes=1)
    publisher.tails["t1"] = _terminated("t1", clock.now)  # the held attempt's run ended
    clock.now = T0 + timedelta(minutes=2)
    live_gate = queue.gate(1)
    live = asyncio.create_task(_schedule(runner, "t1"))
    await queue.publishing(2)

    clock.now = T0 + timedelta(minutes=3)
    with pytest.raises(JobRunnerAtCapacity):
        await _schedule(runner, "t1")

    live_gate.set()
    await live


async def test_the_copied_worker_margins_match_the_workers() -> None:
    """The slack's margins are copied from the worker, which the runner may not import."""
    assert DEADLINE_MARGIN_S + KILL_GRACE_S == _WORKER_KILL_MARGINS_S


@pytest.mark.parametrize("shape", ["expression", "direct"])
async def test_the_slack_covers_the_grace_a_queued_run_carries(shape: job_env.RunShape) -> None:
    """The run queue writes each message's stream grace, and the slack is sized from it."""
    env = decode_message(encode_message("t1", "'hi'", SHORT_S, shape=shape))

    assert float(env[job_env.STREAM_GRACE_S]) <= job_env.DEFAULT_STREAM_GRACE_S


async def test_the_lease_bounds_a_long_runs_hold() -> None:
    """A 16 h run's hold would outlast the lease; the lease frees it."""
    clock = _Clock()
    runner = _runner(_Queue(), clock=clock)
    await _held(runner, deadline_s=LONG_S)

    clock.now = T0 + timedelta(seconds=LEASE_S + 1)
    await _schedule(runner, "t2")

    assert _holds(runner) == []
