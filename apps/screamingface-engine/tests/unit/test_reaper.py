"""The orphan-run reaper's policy: arm on audience-empty, disarm on return, stop on expiry.

FEATURE: tie a run's lifetime to its audience (OME-890).

Every test drives an injected clock and calls `sweep()` directly. Nothing here sleeps: a reaper
verified against real time would be both slow and flaky, and the grace window it enforces is
measured in minutes.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.reaper import RunReaper

GRACE = 120.0


class _FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeAudience:
    """Which topics have a subscriber, as the real ConnectionRegistry would answer."""

    def __init__(self, present: set[str] | None = None) -> None:
        self.present = present if present is not None else set()

    async def has_subscriber(self, topic: str) -> bool:
        return topic in self.present


class _FakeRunner:
    """Records stop calls; `live` is the set of topics `exists` answers True for."""

    def __init__(
        self,
        live: set[str] | None = None,
        fail_on: set[str] | None = None,
        fail_exists_on: set[str] | None = None,
    ) -> None:
        self.live = live if live is not None else set()
        self.fail_on = fail_on if fail_on is not None else set()
        self.fail_exists_on = fail_exists_on if fail_exists_on is not None else set()
        self.stopped: list[str] = []

    async def exists(self, topic: str) -> bool:
        if topic in self.fail_exists_on:
            raise QueueReadError("stream tail unreadable")
        return topic in self.live

    async def stop(self, topic: str) -> None:
        if topic in self.fail_on:
            raise RuntimeError("runner unavailable")
        self.stopped.append(topic)
        self.live.discard(topic)


def _reaper(
    clock: _FakeClock,
    audience: _FakeAudience,
    runner: _FakeRunner,
    grace_s: float = GRACE,
) -> RunReaper:
    return RunReaper(runner, audience, grace_s=grace_s, clock=clock, tick_s=10.0)


@pytest.mark.asyncio
async def test_an_armed_run_is_stopped_once_the_window_closes() -> None:
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live={"t"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    clock.advance(GRACE)

    assert await reaper.sweep() == ("t",)
    assert runner.stopped == ["t"]
    assert reaper.armed_count == 0
    assert reaper.reaped_total == 1


@pytest.mark.asyncio
async def test_nothing_happens_before_the_window_closes() -> None:
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live={"t"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    clock.advance(GRACE - 0.01)

    assert await reaper.sweep() == ()
    assert runner.stopped == []
    assert reaper.armed_count == 1


@pytest.mark.asyncio
async def test_a_subscriber_returning_inside_the_window_saves_the_run() -> None:
    # STORY: as a researcher whose wifi blipped, my reconnected notebook keeps its evaluation.
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live={"t"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    clock.advance(GRACE / 2)
    reaper.audience_arrived("t")
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert runner.stopped == []
    assert reaper.armed_count == 0


@pytest.mark.asyncio
async def test_a_subscriber_present_at_expiry_is_re_checked_and_the_run_survives() -> None:
    # INVARIANT: claim-then-verify. Even with a STALE arm — a disarm that never arrived — the
    # sweep asks the registry again before stopping anything, because reaping a watched run is
    # far worse than reaping late.
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live={"t"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    audience.present.add("t")  # the arm is stale; the registry disagrees
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert runner.stopped == []
    assert reaper.armed_count == 0


@pytest.mark.asyncio
async def test_a_finished_run_is_not_stopped() -> None:
    # INVARIANT: no second terminal frame. `exists` is False once the run is terminal, and on
    # the k8s runner a stop would DELETE the finished Job before the TTL that is its
    # single-use replay guard.
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live=set())
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert runner.stopped == []


@pytest.mark.asyncio
async def test_a_topic_that_never_started_a_run_is_dropped_quietly() -> None:
    # WHY this case exists: a client may attach and disconnect without ever issuing `GET /?q=`.
    # The arm is unconditional, so it must expire harmlessly rather than raise.
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live=set())
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("attached-then-left-without-starting")
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert reaper.armed_count == 0


@pytest.mark.asyncio
async def test_flapping_leaves_exactly_one_arm_and_the_last_one_wins() -> None:
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live={"t"})
    reaper = _reaper(clock, audience, runner)

    for _ in range(5):
        reaper.audience_left("t")
        clock.advance(1.0)
        reaper.audience_arrived("t")
    reaper.audience_left("t")

    assert reaper.armed_count == 1

    clock.advance(GRACE - 0.01)
    assert await reaper.sweep() == ()  # measured from the LAST leave, not the first

    clock.advance(0.01)
    assert await reaper.sweep() == ("t",)


@pytest.mark.asyncio
async def test_a_second_sweep_does_not_stop_the_run_again() -> None:
    clock, audience, runner = _FakeClock(), _FakeAudience(), _FakeRunner(live={"t"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    clock.advance(GRACE)
    await reaper.sweep()
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert runner.stopped == ["t"]
    assert reaper.reaped_total == 1


@pytest.mark.asyncio
async def test_a_failed_stop_is_retried_rather_than_abandoned() -> None:
    # INVARIANT: giving up would hand the run back to the 16h ceiling — the exact spend this
    # module exists to stop. A transient runner error must re-arm.
    clock, audience = _FakeClock(), _FakeAudience()
    runner = _FakeRunner(live={"t"}, fail_on={"t"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert reaper.armed_count == 1  # re-armed, not dropped
    assert reaper.reaped_total == 0

    runner.fail_on.clear()
    clock.advance(reaper.tick_s)

    assert await reaper.sweep() == ("t",)
    assert runner.stopped == ["t"]


@pytest.mark.asyncio
async def test_an_audience_loss_stop_reaches_a_queued_run() -> None:
    """The Job path stopped a queued run by deleting a Job that might never have started;
    the queue runner must stop a QUEUED run the same way. `exists()` is True for a
    scheduled (queued) run, so the reaper's stop() lands and writes the tombstone."""
    clock = _FakeClock()
    publisher = _FakePublisher()
    runner = QueueJobRunner(
        queue=_FakeQueue(),
        publisher=publisher,
        control=_FakeControl(),
        clock=_QueueClock(),
        capability_lifetime_s=100.0,
    )
    await runner.schedule("t", "'hi'", 60)
    reaper = RunReaper(runner, _FakeAudience(), grace_s=GRACE, clock=clock, tick_s=10.0)

    reaper.audience_left("t")
    clock.advance(GRACE)

    assert await reaper.sweep() == ("t",)
    assert reaper.reaped_total == 1
    assert len(publisher.published) == 1
    assert publisher.published[0].data.status == "stopped"


class _QueueClock:
    """A wall clock for the queue runner, independent of the reaper's monotonic one."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _FakeQueue:
    def __init__(self) -> None:
        self.published: list[bytes] = []

    async def publish(self, message: bytes, *, identity: Any = None) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[Any] = []
        self.ensured: list[str] = []

    async def last_frame(self, topic: str) -> Any:
        return None

    async def stream_exists(self, topic: str) -> bool:
        return True

    async def ensure_stream(self, topic: str) -> None:
        self.ensured.append(topic)

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _FakeControl:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


@pytest.mark.asyncio
async def test_only_the_due_topics_are_swept() -> None:
    clock, audience = _FakeClock(), _FakeAudience()
    runner = _FakeRunner(live={"early", "late"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("early")
    clock.advance(GRACE / 2)
    reaper.audience_left("late")
    clock.advance(GRACE / 2)

    assert await reaper.sweep() == ("early",)
    assert reaper.armed_count == 1
    assert reaper.is_armed("late") is True


def test_the_tick_is_derived_from_the_grace_window_with_a_floor() -> None:
    # WHY one knob: reap latency is `grace` to `grace + grace/8`, so the operator tunes the
    # window and gets a bounded overshoot instead of a second setting to keep consistent.
    runner, audience = _FakeRunner(), _FakeAudience()

    assert RunReaper(runner, audience, grace_s=120.0).tick_s == pytest.approx(15.0)
    assert RunReaper(runner, audience, grace_s=0.5).tick_s == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_armed_implies_no_subscriber_across_a_scripted_sequence() -> None:
    # INVARIANT (the whole safety property, stated once): a topic is armed only while its
    # audience is empty, and the deadline map never outgrows the live topic set. Scripted
    # rather than property-based because `hypothesis` is not a dependency of this stack.
    clock, audience = _FakeClock(), _FakeAudience()
    runner = _FakeRunner(live={"a", "b", "c"})
    reaper = _reaper(clock, audience, runner)
    topics = ("a", "b", "c")

    script: list[tuple[str, str | float]] = [
        ("arrive", "a"),
        ("arrive", "b"),
        ("leave", "a"),
        ("tick", 30.0),
        ("arrive", "a"),
        ("leave", "b"),
        ("leave", "c"),
        ("tick", 200.0),
        ("arrive", "c"),
        ("leave", "a"),
        ("tick", 5.0),
        ("leave", "c"),
        ("tick", 500.0),
        ("arrive", "b"),
    ]
    for action, value in script:
        if action == "arrive":
            audience.present.add(str(value))
            reaper.audience_arrived(str(value))
        elif action == "leave":
            audience.present.discard(str(value))
            reaper.audience_left(str(value))
        else:
            clock.advance(float(value))
            await reaper.sweep()
        assert reaper.armed_count <= len(topics)
        for topic in topics:
            if reaper.is_armed(topic):
                assert not await audience.has_subscriber(topic), (
                    f"{topic} is armed while its audience is present"
                )


@pytest.mark.asyncio
async def test_an_unreadable_exists_rearms_rather_than_forgetting_the_topic() -> None:
    """P2-10: `_reap` popped the deadline BEFORE the `exists` guard, and the guard was not
    wrapped — one transient read failure aborted the sweep with the topic already claimed
    (disarmed) and nothing left to re-arm it: the orphan was silently forgotten and ran
    to the 16h ceiling, the exact spend the reaper exists to prevent. A guard failure now
    re-arms like a failed stop."""
    clock, audience = _FakeClock(), _FakeAudience()
    runner = _FakeRunner(live={"t"}, fail_exists_on={"t"})
    reaper = _reaper(clock, audience, runner)

    reaper.audience_left("t")
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert reaper.armed_count == 1  # re-armed, not forgotten
    assert runner.stopped == []

    runner.fail_exists_on.clear()
    clock.advance(reaper.tick_s)

    assert await reaper.sweep() == ("t",)
    assert runner.stopped == ["t"]


@pytest.mark.asyncio
async def test_an_unknown_read_during_the_reap_rearms_the_real_runner_too() -> None:
    """V-2 — the COMPOSITION the first P2-10 fix never tested: both halves were verified
    in isolation (the reaper against a fake whose `stop` raised; `stop()` against the
    sentinel) and the combination reinstated the bug — the real `stop()` answered the
    unreadable tail with a SILENT no-op, so `_reap` fell through to `reaped_total += 1`
    and logged "orphan run reaped" for a run it never touched, with the deadline popped
    and nothing re-arming it. Unknown must reach the reaper as a FAILURE so its existing
    re-arm runs: the tail reads fine for `exists` (the run is live) and goes unreadable
    under `stop` — exactly a reconnect landing between the two reads."""
    from test_queue_runner_cancel import _FakeControl, _FakePublisher, _runner

    from url4.streaming.protocol import StartedData, StartedEvent, source_for

    class _UnreadableOnTheSecondRead(_FakePublisher):
        """`exists` reads a live Started frame; `stop`'s re-read lands mid-reconnect."""

        def __init__(self) -> None:
            super().__init__()
            self.reads = 0

        async def last_frame(self, topic: str) -> Any:
            self.reads += 1
            if self.reads >= 2:
                raise QueueReadError("stream tail unreadable")
            return StartedEvent(
                id="s", source=source_for(topic), subject=topic, data=StartedData(url4="'hi'")
            )

    clock, audience = _FakeClock(), _FakeAudience()
    runner = _runner(_UnreadableOnTheSecondRead(), _FakeControl())
    reaper = RunReaper(runner, audience, grace_s=GRACE, clock=clock, tick_s=10.0)

    reaper.audience_left("t")
    clock.advance(GRACE)

    assert await reaper.sweep() == ()
    assert reaper.armed_count == 1, "an unknown read must re-arm, not count as a reap"
    assert reaper.reaped_total == 0, "telemetry must not assert a reap that did not happen"
