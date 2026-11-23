"""E5 P2 spec R4 and R9 to R11: the driver's lease and its tick.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, a Run I detach runs to its deadline
with nobody following, and an attached Run I abandon stops on its own, while a Run I follow is
never stopped by an App restart or a database blip.

Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from run_driver_support import SETTINGS, DriverRunner, drivers
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
    start_spec,
)

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import (
    P1_PENDING_GRACE,
    RunRecord,
    StopReason,
    owner_key,
)

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
GRACE = SETTINGS.orphan_grace_s


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def _record(registry: Registry, run_id: str) -> RunRecord:
    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    return record


# --- the lease (R4) ---------------------------------------------------------------------------


async def test_two_drivers_never_drive_one_run(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a", "b"))
    first, second = DriverRunner(), DriverRunner()

    assert await drivers(registry.store, first, registry.clock).drive_once(run.id)
    assert not await drivers(registry.store, second, registry.clock).drive_once(run.id)

    assert len(first.starts) == 2
    assert second.starts == []


async def test_an_expired_lease_is_taken_over_and_its_old_driver_stops(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    old = drivers(registry.store, DriverRunner(), registry.clock)
    new = drivers(registry.store, DriverRunner(), registry.clock)
    assert await old.drive_once(run.id)

    registry.clock.advance(seconds=SETTINGS.lease_s + 1)

    assert await new.drive_once(run.id)
    assert not await old.drive_once(run.id)


async def test_a_driver_gives_its_leases_up_when_it_closes(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    old = drivers(registry.store, DriverRunner(), registry.clock)
    assert await old.drive_once(run.id)

    await old.aclose()

    assert await drivers(registry.store, DriverRunner(), registry.clock).drive_once(run.id)


async def test_a_run_whose_candidates_all_ended_needs_no_driver(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.drive_once(run.id)
    await registry.store.settle(runner.starts[0]["topic"], CandidateOutcome("succeeded"))

    assert not await driver.drive_once(run.id)
    assert await driver.tick() == []


async def test_the_tick_hands_out_the_runs_to_drive(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))

    assert await drivers(registry.store, DriverRunner(), registry.clock).tick() == [run.id]


# --- stops (R9, R11) --------------------------------------------------------------------------


async def test_a_detached_run_stops_at_its_deadline_and_its_starts_are_stopped(
    registry: Registry,
) -> None:
    run, _ = await registry.store.register(
        ALICE, start_spec("a", "b", detach=True, deadline=timedelta(hours=1))
    )
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.drive_once(run.id)
    registry.clock.advance(hours=1)

    await driver.tick()

    record = await _record(registry, run.id)
    assert record.stopped_by == "deadline"
    assert sorted(runner.stopped) == sorted(start["topic"] for start in runner.starts)


async def test_a_detached_run_runs_with_nobody_following(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a", detach=True))
    driver = drivers(registry.store, DriverRunner(), registry.clock)
    await driver.tick()
    registry.clock.advance(hours=12)

    await driver.tick()

    assert (await _record(registry, run.id)).stopped_by is None


async def test_a_stop_that_fails_is_made_again_on_the_next_tick(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.drive_once(run.id)
    await registry.store.stop(run.id, "canceled")
    runner.failing_stops = 1

    await driver.tick()
    assert runner.stopped == []
    await driver.tick()

    assert runner.stopped == [runner.starts[0]["topic"]]
    assert await registry.store.owed_stops(ALICE, run.id) == []


async def test_a_stop_a_worker_took_stays_owed_until_its_frame_lands(registry: Registry) -> None:
    """#1759 review: the worker that took the stop may die before its stopped frame, and a copy
    of the message would then run again elsewhere. So the stop stays owed, and the next tick
    makes it again, until the frame is on the stream."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.drive_once(run.id)
    topic = runner.starts[0]["topic"]
    await registry.store.stop(run.id, "canceled")
    runner.unlanded.add(topic)

    await driver.tick()
    assert await registry.store.owed_stops(ALICE, run.id) == [topic]

    runner.unlanded.clear()
    await driver.tick()

    assert runner.stopped == [topic, topic]
    assert await registry.store.owed_stops(ALICE, run.id) == []


async def test_a_canceled_run_reads_canceled_and_an_orphaned_one_interrupted(
    registry: Registry,
) -> None:
    canceled, _ = await registry.store.register(ALICE, start_spec("a", client_key="k1"))
    orphaned, _ = await registry.store.register(ALICE, start_spec("a", client_key="k2"))
    runner = DriverRunner()
    driver = drivers(registry.store, runner, registry.clock)
    await driver.tick()
    for run in (canceled, orphaned):
        await driver.drive_once(run.id)
    await registry.store.stop(canceled.id, "canceled")
    registry.clock.advance(seconds=GRACE + 1)
    await driver.tick()
    for start in runner.starts:
        await registry.store.settle(start["topic"], CandidateOutcome("stopped"))

    assert (await _record(registry, canceled.id)).state == "canceled"
    record = await _record(registry, orphaned.id)
    assert (record.state, record.stopped_by) == ("interrupted", "orphaned")


async def test_a_pre_p2_run_is_never_orphaned_and_its_candidates_settle(
    registry: Registry,
) -> None:
    run, _ = await registry.store.register(ALICE, spec("a"))
    driver = drivers(registry.store, DriverRunner(), registry.clock)
    await driver.tick()
    # P1's pending grace: a released Client may still be starting it until then (R11).
    registry.clock.advance(seconds=P1_PENDING_GRACE.total_seconds() + 1)

    await driver.tick()

    record = await _record(registry, run.id)
    assert record.stopped_by is None
    assert [c.state for c in record.candidates] == ["stopped"]


async def test_the_startless_pass_runs_once_per_p1_grace(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 3: only Runs a Client from before P2 registered have startless Candidates,
    so the pass that settles them does not run on every tick."""
    calls: list[bool] = []
    real = registry.store.settle_startless

    async def counted() -> int:
        calls.append(True)
        return await real()

    monkeypatch.setattr(registry.store, "settle_startless", counted)
    driver = drivers(registry.store, DriverRunner(), registry.clock)

    await driver.tick()
    registry.clock.advance(seconds=SETTINGS.tick_s)
    await driver.tick()
    assert len(calls) == 1

    registry.clock.advance(seconds=P1_PENDING_GRACE.total_seconds())
    await driver.tick()
    assert len(calls) == 2


# --- attached Runs (R10) ----------------------------------------------------------------------


async def test_an_attached_run_nobody_follows_stops_after_the_grace(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    driver = drivers(registry.store, DriverRunner(), registry.clock)
    await driver.tick()

    registry.clock.advance(seconds=GRACE - 1)
    await driver.tick()
    assert (await _record(registry, run.id)).stopped_by is None

    registry.clock.advance(seconds=2)
    await driver.tick()
    assert (await _record(registry, run.id)).stopped_by == "orphaned"


async def test_a_follower_within_the_grace_keeps_the_run(registry: Registry) -> None:
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    driver = drivers(registry.store, DriverRunner(), registry.clock)
    await driver.tick()
    registry.clock.advance(seconds=GRACE - 10)
    await registry.store.hold(run.id)

    registry.clock.advance(seconds=20)
    await driver.tick()

    assert (await _record(registry, run.id)).stopped_by is None


async def test_no_orphan_stop_within_the_grace_after_the_driver_starts(registry: Registry) -> None:
    """R10: an App restart could not record follows while it was down."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    registry.clock.advance(seconds=GRACE * 5)
    driver = drivers(registry.store, DriverRunner(), registry.clock)

    await driver.tick()
    registry.clock.advance(seconds=GRACE - 1)
    await driver.tick()
    assert (await _record(registry, run.id)).stopped_by is None

    registry.clock.advance(seconds=2)
    await driver.tick()
    assert (await _record(registry, run.id)).stopped_by == "orphaned"


async def test_an_older_apps_cancel_is_finished_at_once_after_the_driver_starts(
    registry: Registry,
) -> None:
    """#1759 review round 5: a Run an App from before P2 canceled by the flag alone (R12) is no
    deadline a follower moves, so the driver's first grace does not hold its stop back."""
    from screamingface_engine.runs.models import Run

    run, _ = await registry.store.register(ALICE, start_spec("a"))
    await Run.filter(id=run.id).update(canceled=True)
    driver = drivers(registry.store, DriverRunner(), registry.clock)

    await driver.tick()

    assert (await _record(registry, run.id)).stopped_by == "canceled"


async def test_no_orphan_stop_within_the_grace_after_a_failed_tick(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10: a registry outage longer than the grace never stops a followed Run."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    driver = drivers(registry.store, DriverRunner(), registry.clock)
    await driver.tick()
    store = registry.store
    real = store.due_runs

    async def down(now: object) -> object:
        raise ConnectionError("the database is down")

    monkeypatch.setattr(store, "due_runs", down)
    registry.clock.advance(seconds=GRACE * 3)
    assert await driver.tick() == []
    monkeypatch.setattr(store, "due_runs", real)

    await driver.tick()
    assert (await _record(registry, run.id)).stopped_by is None
    registry.clock.advance(seconds=GRACE + 1)
    await driver.tick()
    assert (await _record(registry, run.id)).stopped_by == "orphaned"


# --- a tick survives one failing step (review round 4) ---------------------------------------


async def test_a_failing_startless_pass_neither_drops_the_runs_to_drive_nor_stops_the_clock(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10: only a tick that cannot read the due Runs restarts the clock; a later step that
    fails is logged and the tick goes on."""
    run, _ = await registry.store.register(ALICE, start_spec("a"))
    driver = drivers(registry.store, DriverRunner(), registry.clock)

    async def broken() -> int:
        raise ConnectionError("one statement failed")

    monkeypatch.setattr(registry.store, "settle_startless", broken)

    assert await driver.tick() == [run.id]
    registry.clock.advance(seconds=GRACE + 1)
    await driver.tick()

    assert (await _record(registry, run.id)).stopped_by == "orphaned"


async def test_one_runs_failing_stop_does_not_hold_back_anothers(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = await registry.store.register(ALICE, start_spec("a", client_key="k1"))
    second, _ = await registry.store.register(ALICE, start_spec("a", client_key="k2"))
    driver = drivers(registry.store, DriverRunner(), registry.clock)
    await driver.tick()
    real = registry.store.stop
    failed: list[str] = []

    async def stop(
        run_id: str, reason: StopReason, *, past_deadline_at: datetime | None = None
    ) -> bool:
        if not failed:
            failed.append(run_id)
            raise ConnectionError("a deadlock aborted this one")
        return await real(run_id, reason, past_deadline_at=past_deadline_at)

    monkeypatch.setattr(registry.store, "stop", stop)
    registry.clock.advance(seconds=GRACE + 1)
    await driver.tick()

    (other,) = {first.id, second.id} - set(failed)
    assert (await _record(registry, other)).stopped_by == "orphaned"


async def test_startless_candidates_past_one_batch_all_settle_in_one_pass(
    registry: Registry,
) -> None:
    """R11: a deploy can leave thousands of P1 Candidates pending; one pass settles them all,
    a batch at a time, so their Runs stop reading `running`."""
    names = tuple(f"c{i}" for i in range(200))
    runs = [
        (await registry.store.register(ALICE, spec(*names, client_key=f"k{n}")))[0]
        for n in range(3)
    ]
    registry.clock.advance(seconds=P1_PENDING_GRACE.total_seconds() + 1)

    await drivers(registry.store, DriverRunner(), registry.clock).tick()

    for run in runs:
        assert {c.state for c in (await _record(registry, run.id)).candidates} == {"stopped"}
