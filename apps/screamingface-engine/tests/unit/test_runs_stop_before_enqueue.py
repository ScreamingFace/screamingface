"""E5 P1 spec D12: a cancel keeps a Run's queued Candidate from running even when the App
cannot know it was queued, and concurrent cancels answer only their own failures (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, I cancel a Run and none of its Candidates
runs afterwards, even if the Engine restarted or my cancel beat the Candidate's start.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from _fakes import RecordingJobRunner
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_queue_runner_cancel import (
    CAPABILITY_LIFETIME_S,
    _FakeControl,
    _FakeMsg,
    _FakePublisher,
    _runner,
    _supervisor,
)
from test_runs_routes import ALICE, _Engine

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.ports import StoppedBeforeSchedule
from screamingface_engine.rest import runs
from screamingface_engine.runner_queue import encode_message
from screamingface_engine.runs.records import owner_key
from url4.streaming.protocol import TerminatedEvent

pytestmark = pytest.mark.asyncio

_ALICE_KEY = owner_key("alice@example.org")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


# --- the queue runner ----------------------------------------------------------------------


async def test_a_bound_stop_after_a_restart_keeps_the_queued_run_from_running() -> None:
    """WHY: a restarted App has no record of what the old one queued."""
    publisher = _FakePublisher()
    await _runner(publisher, _FakeControl(reply=False)).schedule("t", "'hi'", 60)
    restarted = _runner(publisher, _FakeControl(reply=False))

    await restarted.stop_bound("t")

    (frame,) = publisher.published
    assert isinstance(frame, TerminatedEvent) and frame.data.status == "stopped"
    msg = _FakeMsg(encode_message("t", "'hi'", 60))
    await _supervisor(publisher).supervise(msg)  # never spawns
    assert msg.acked


async def test_a_bound_stop_before_the_publish_keeps_the_run_from_running() -> None:
    publisher = _FakePublisher()
    runner = _runner(publisher, _FakeControl(reply=False))

    await runner.stop_bound("t")
    with pytest.raises(StoppedBeforeSchedule):
        await runner.schedule("t", "'hi'", 60)

    msg = _FakeMsg(encode_message("t", "'hi'", 60))
    await _supervisor(publisher).supervise(msg)  # never spawns
    assert msg.acked
    assert len(publisher.published) == 1


# --- the Runs cancel -----------------------------------------------------------------------


class _BoundStops(RecordingJobRunner):
    def __init__(self) -> None:
        super().__init__()
        self.bound: list[str] = []

    async def stop_bound(self, topic: str) -> None:
        self.bound.append(topic)


async def test_a_cancel_stops_its_candidates_as_bound_topics(registry: Registry) -> None:
    runner = _BoundStops()
    engine = _Engine(registry, runner=runner)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")

    assert (await engine.client.delete(f"/runs/{run_id}", headers=ALICE)).status_code == 202
    assert runner.bound == ["topic-a"]


class _FailsAfterTheOtherStop(RecordingJobRunner):
    """The first stop fails, but only once a concurrent cancel's stop has cleared the debt."""

    def __init__(self, store: Any, run_id: str) -> None:
        super().__init__()
        self._store = store
        self._run_id = run_id
        self.attempts = 0

    async def stop(self, topic: str) -> None:
        self.attempts += 1
        if self.attempts == 1:
            while topic in await self._store.owed_stops(_ALICE_KEY, self._run_id):
                await asyncio.sleep(0.01)
            raise QueueReadError(topic)
        await super().stop(topic)


async def test_a_stop_another_cancel_completed_is_not_a_503(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    runner = _FailsAfterTheOtherStop(registry.store, run_id)
    engine.app.state.job_runner = runner

    first, second = await asyncio.wait_for(
        asyncio.gather(
            engine.client.delete(f"/runs/{run_id}", headers=ALICE),
            engine.client.delete(f"/runs/{run_id}", headers=ALICE),
        ),
        timeout=10,
    )

    assert runner.attempts == 2
    assert 503 not in (first.status_code, second.status_code)


async def test_a_run_stopped_before_its_schedule_queues_nothing_and_holds_no_slot() -> None:
    """WHY: a slot reserved after the tombstone is newer than it, so nothing would release it."""
    publisher = _FakePublisher()
    runner = _runner(publisher, _FakeControl(reply=False))

    await runner.stop_bound("t")
    with pytest.raises(StoppedBeforeSchedule):
        await runner.schedule("t", "'hi'", 60, identity={"X-User-Email": "alice@example.org"})

    assert runner._queue.published == []  # type: ignore[attr-defined]
    assert all("t" not in topics for topics in runner._in_flight_by_caller.values())


class _RecheckFails:
    """A registry whose owed-stop read fails once the stops have been tried."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._reads = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def owed_stops(self, owner: Any, run_id: str) -> list[str]:
        self._reads += 1
        if self._reads > 1:
            raise RuntimeError("the database went away")
        return await self._store.owed_stops(owner, run_id)


class _StopFails(RecordingJobRunner):
    async def stop(self, topic: str) -> None:
        raise QueueReadError(topic)


async def test_a_failed_recheck_still_answers_the_stops_private_503(registry: Registry) -> None:
    engine = _Engine(registry, runner=_StopFails())
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    engine.app.state.run_registry = _RecheckFails(registry.store)

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 503
    assert resp.headers["Cache-Control"] == "private, no-store"


class _StopCancelled(RecordingJobRunner):
    async def stop(self, topic: str) -> None:
        raise asyncio.CancelledError


class _OwedOnce:
    def __init__(self) -> None:
        self._reads = 0

    async def owed_stops(self, owner: Any, run_id: str) -> list[str]:
        self._reads += 1
        return ["topic-a"] if self._reads == 1 else []

    async def stop_done(self, topic: str) -> None:
        pass


async def test_a_cancelled_stop_is_never_swallowed() -> None:
    state = SimpleNamespace(job_runner=_StopCancelled(), stream=None)
    request: Any = SimpleNamespace(app=SimpleNamespace(state=state))

    with pytest.raises(asyncio.CancelledError):
        await runs._stop_owed(request, cast(Any, _OwedOnce()), _ALICE_KEY, "run")


class _UnreadableOnSecondRead(_FakePublisher):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    async def last_frame(self, topic: str) -> Any:
        self.reads += 1
        if self.reads > 1:
            raise QueueReadError("stream tail unreadable")
        return None


async def test_an_unreadable_second_read_is_not_a_successful_stop() -> None:
    """WHY: a stop that returned would let the cancel clear its debt with no tombstone."""
    publisher = _UnreadableOnSecondRead()
    runner = _runner(publisher, _FakeControl(reply=False))

    with pytest.raises(QueueReadError):
        await runner.stop_bound("t")

    assert publisher.published == []


_ALICE_IDENTITY = {"X-User-Email": "alice@example.org"}


async def _stop_while_paused(runner: Any, paused: asyncio.Event, resume: asyncio.Event) -> None:
    schedule = asyncio.create_task(runner.schedule("t", "'hi'", 60, identity=_ALICE_IDENTITY))
    await asyncio.wait_for(paused.wait(), timeout=5)
    await runner.stop_bound("t")
    resume.set()
    with pytest.raises(StoppedBeforeSchedule):
        await asyncio.wait_for(schedule, timeout=5)


async def test_a_stop_during_admission_queues_nothing_and_holds_no_slot() -> None:
    runner = _runner(_FakePublisher(), _FakeControl(reply=False))
    paused, resume = asyncio.Event(), asyncio.Event()
    admit = runner._admit_or_raise

    async def _paused_admit(*args: Any) -> Any:
        reservation = await admit(*args)
        paused.set()
        await resume.wait()
        return reservation

    runner._admit_or_raise = _paused_admit  # type: ignore[method-assign]
    await _stop_while_paused(runner, paused, resume)

    assert runner._queue.published == []  # type: ignore[attr-defined]
    assert runner._in_flight_by_caller == {}


async def test_a_stop_during_the_publish_holds_no_slot() -> None:
    runner = _runner(_FakePublisher(), _FakeControl(reply=False))
    paused, resume = asyncio.Event(), asyncio.Event()
    queue: Any = runner._queue
    publish = queue.publish

    async def _paused_publish(message: bytes, **kwargs: Any) -> None:
        paused.set()
        await resume.wait()
        await publish(message, **kwargs)

    queue.publish = _paused_publish
    await _stop_while_paused(runner, paused, resume)

    assert runner._in_flight_by_caller == {}


async def test_one_stop_releases_every_racing_schedule_of_its_topic() -> None:
    """WHY: a client retry can race its own first attempt, each with its own reservation."""
    runner = _runner(_FakePublisher(), _FakeControl(reply=False))
    admitted, resume = asyncio.Event(), asyncio.Event()
    admit = runner._admit_or_raise
    waiting = 0

    async def _paused_admit(*args: Any) -> Any:
        nonlocal waiting
        reservation = await admit(*args)
        waiting += 1
        if waiting == 2:
            admitted.set()
        await resume.wait()
        return reservation

    runner._admit_or_raise = _paused_admit  # type: ignore[method-assign]
    schedules = [
        asyncio.create_task(runner.schedule("t", "'hi'", 60, identity=_ALICE_IDENTITY))
        for _ in range(2)
    ]
    await asyncio.wait_for(admitted.wait(), timeout=5)
    await runner.stop_bound("t")
    resume.set()
    results = await asyncio.wait_for(asyncio.gather(*schedules, return_exceptions=True), timeout=5)
    assert all(isinstance(result, StoppedBeforeSchedule) for result in results)

    assert runner._queue.published == []  # type: ignore[attr-defined]
    assert runner._in_flight_by_caller == {}


async def test_a_schedule_paused_past_the_marker_lifetime_still_queues_nothing() -> None:
    """WHY: pruning by age alone would drop the marker while this schedule still needs it."""
    runner = _runner(_FakePublisher(), _FakeControl(reply=False))
    paused, resume = asyncio.Event(), asyncio.Event()
    admit = runner._admit_or_raise

    async def _paused_admit(identity: Any, topic: str) -> Any:
        reservation = await admit(identity, topic)
        if topic == "t":
            paused.set()
            await resume.wait()
        return reservation

    runner._admit_or_raise = _paused_admit  # type: ignore[method-assign]
    schedule = asyncio.create_task(runner.schedule("t", "'hi'", 60, identity=_ALICE_IDENTITY))
    await asyncio.wait_for(paused.wait(), timeout=5)
    await runner.stop_bound("t")
    runner._clock.now += timedelta(seconds=CAPABILITY_LIFETIME_S + 1)  # type: ignore[attr-defined]
    await runner.schedule("other", "'hi'", 60)  # its admission prunes
    resume.set()
    with pytest.raises(StoppedBeforeSchedule):
        await asyncio.wait_for(schedule, timeout=5)

    assert len(runner._queue.published) == 1  # type: ignore[attr-defined]  # only "other"
    assert all("t" not in topics for topics in runner._in_flight_by_caller.values())


class _RecordsDeadlineStart(RecordingJobRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started: list[tuple[datetime | None, datetime]] = []

    async def schedule(self, *args: Any, enqueued_at: datetime | None = None, **kw: Any) -> str:
        self.started.append((enqueued_at, datetime.now(UTC)))
        return await super().schedule(*args, **kw)


async def test_a_bound_runs_deadline_counts_from_its_bind(registry: Registry) -> None:
    """WHY: a cancel's tombstone is written only after the bind, so a deadline counted from the
    later publish could outlast it."""
    runner = _RecordsDeadlineStart()
    engine = _Engine(registry, runner=runner)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    before_bind = datetime.now(UTC)

    assert (await engine.start("topic-a", run_id)).status_code == 202

    ((enqueued_at, scheduled_at),) = runner.started
    assert enqueued_at is not None and before_bind <= enqueued_at <= scheduled_at


async def test_a_local_bound_stop_before_the_schedule_starts_no_task() -> None:
    """WHY: in local mode the task spawned after the cancel would run until the start's
    confirmation stopped it, possibly after calling a provider."""
    built: list[Mapping[str, str]] = []

    def factory(env: Mapping[str, str]) -> Any:
        built.append(env)
        raise AssertionError("a stopped topic must not build an executor")

    runner = InProcessJobRunner(InMemoryEventStream(), factory)

    await runner.stop_bound("t")
    with pytest.raises(StoppedBeforeSchedule):
        await runner.schedule("t", "'hi'", 60)

    assert not await runner.exists("t")
    assert built == []


async def test_a_queue_at_capacity_still_answers_a_stopped_topic_as_stopped() -> None:
    """WHY: a capacity refusal tells the client to retry a start that was canceled."""
    runner = _runner(_FakePublisher(), _FakeControl(reply=False))
    runner._caller_inflight_cap = 0

    await runner.stop_bound("t")
    with pytest.raises(StoppedBeforeSchedule):
        await runner.schedule("t", "'hi'", 60, identity=_ALICE_IDENTITY)

    assert runner._queue.published == []  # type: ignore[attr-defined]


async def test_a_full_local_runner_still_answers_a_stopped_topic_as_stopped() -> None:
    runner = InProcessJobRunner(InMemoryEventStream(), lambda env: None, max_concurrent_runs=0)  # type: ignore[arg-type,return-value]

    await runner.stop_bound("t")
    with pytest.raises(StoppedBeforeSchedule):
        await runner.schedule("t", "'hi'", 60)

    assert not await runner.exists("t")


class _BindsThenLosesTheAck:
    """A registry whose bind commits but whose acknowledgement is lost."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def bind(self, *args: Any) -> None:
        await self._store.bind(*args)
        raise ConnectionError("commit acknowledgement lost")


async def test_a_bind_with_an_unknown_outcome_keeps_its_bind_moment(registry: Registry) -> None:
    """WHY: the bind may have committed, so a cancel can tombstone the topic all the same."""
    runner = _RecordsDeadlineStart()
    engine = _Engine(registry, runner=runner)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    engine.app.state.run_registry = _BindsThenLosesTheAck(registry.store)
    before_bind = datetime.now(UTC)

    assert (await engine.start("topic-a", run_id)).status_code == 202

    ((enqueued_at, _),) = runner.started
    assert enqueued_at is not None and enqueued_at >= before_bind


class _StoppedTopic(RecordingJobRunner):
    """A runner whose topic a bound stop already reached: its schedule starts nothing."""

    async def schedule(self, topic: str, *args: Any, **kwargs: Any) -> str:
        raise StoppedBeforeSchedule(topic)


async def test_a_start_stopped_before_its_schedule_answers_canceled_even_unbound(
    registry: Registry, caplog: pytest.LogCaptureFixture
) -> None:
    """WHY: with the bind's outcome unknown no confirmation follows, so the runner's signal is
    the only thing that keeps the start from answering 202 for a run that never started."""
    engine = _Engine(registry, runner=_StoppedTopic())
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    engine.app.state.run_registry = _BindsThenLosesTheAck(registry.store)

    with caplog.at_level("INFO"):
        resp = await engine.start("topic-a", run_id)

    assert resp.status_code == 409
    assert resp.json()["code"] == "run_canceled"
    assert resp.headers["Cache-Control"] == "private, no-store"
    assert "run scheduled" not in caplog.text


async def test_local_stop_markers_are_bounded_by_the_task_history() -> None:
    runner = InProcessJobRunner(InMemoryEventStream(), lambda env: None, max_history=2)  # type: ignore[arg-type,return-value]

    for topic in ("a", "b", "c"):
        await runner.stop_bound(topic)

    assert list(runner._stopped_before_schedule) == ["b", "c"]
