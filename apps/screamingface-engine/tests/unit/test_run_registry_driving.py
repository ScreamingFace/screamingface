"""E5 P2 spec §4.4, R4, R8 to R12: what the registry gives the Engine's driver.

FEATURE: a detached Run (OME-1837). STORY: as a researcher who starts an evaluation and walks
away, I trust the Engine to start every Candidate, and to stop the Run when I cancel it, when
nobody follows an attached one, or at a detached one's deadline.

Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    DEADLINE,
    LOST_AFTER,
    ORPHAN_GRACE,
    T0,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
    start_spec,
)

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import (
    ContextRef,
    DueRun,
    RunQuery,
    RunRecord,
    StopReason,
    owner_key,
)
from screamingface_engine.runs.registry import ClientKeyConflict, RunCanceled

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def _topic(index: int) -> str:
    return str(index) * 64


async def _read(registry: Registry, run_id: str) -> RunRecord:
    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    return record


def _states(record: RunRecord) -> list[str]:
    return [candidate.state for candidate in record.candidates]


async def _start(registry: Registry, run_id: str, *indexes: int) -> None:
    for index in indexes:
        await registry.store.bind(ALICE, run_id, index, _topic(index))
        await registry.store.mark_scheduled(_topic(index))


async def _due(registry: Registry, run_id: str) -> DueRun | None:
    due = await registry.store.due_runs(registry.clock())
    return next((run for run in due if run.run_id == run_id), None)


# --- the lease (R4) ----------------------------------------------------------------------


async def test_one_of_two_drivers_takes_a_free_lease(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec())
    until = registry.clock() + timedelta(seconds=60)

    first = await registry.store.lease_run(run.id, None, until)
    second = await registry.store.lease_run(run.id, None, until)

    assert (first, second) == (True, False)


async def test_an_expired_lease_is_taken_and_its_old_holder_cannot_renew(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec())
    held = registry.clock() + timedelta(seconds=60)
    assert await registry.store.lease_run(run.id, None, held)
    registry.clock.advance(seconds=61)

    taken = registry.clock() + timedelta(seconds=60)
    assert await registry.store.lease_run(run.id, None, taken)

    assert not await registry.store.lease_run(run.id, held, held + timedelta(seconds=60))
    assert await registry.store.lease_run(run.id, taken, taken + timedelta(seconds=60))


async def test_only_the_holder_releases_a_lease(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec())
    held = registry.clock() + timedelta(seconds=60)
    assert await registry.store.lease_run(run.id, None, held)

    await registry.store.release_run(run.id, held - timedelta(seconds=1))
    assert not await registry.store.lease_run(run.id, None, held)

    await registry.store.release_run(run.id, held)
    assert await registry.store.lease_run(run.id, None, held)


# --- due Runs ----------------------------------------------------------------------------


async def test_a_live_run_with_starts_and_a_free_lease_is_due_to_be_driven(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec())

    due = await _due(registry, run.id)
    assert due is not None and due.drive

    await registry.store.lease_run(run.id, None, registry.clock() + timedelta(seconds=60))
    leased = await _due(registry, run.id)
    assert leased is None or not leased.drive


async def test_a_run_without_starts_is_never_driven_or_orphaned(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    registry.clock.advance(seconds=ORPHAN_GRACE.total_seconds() + 1)

    assert await _due(registry, run.id) is None


async def test_a_finished_run_is_not_due(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec("alpha"))
    await _start(registry, run.id, 0)
    await registry.store.settle(_topic(0), CandidateOutcome("succeeded"))

    assert await _due(registry, run.id) is None


async def test_an_attached_run_is_due_to_stop_once_the_grace_has_passed(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec())
    assert run.deadline_at == T0 + ORPHAN_GRACE
    registry.clock.advance(seconds=ORPHAN_GRACE.total_seconds() - 1)
    early = await _due(registry, run.id)
    assert early is not None and not early.past_deadline

    registry.clock.advance(seconds=1)

    due = await _due(registry, run.id)
    assert due is not None and due.past_deadline and not due.detached


async def test_a_hold_moves_an_attached_runs_deadline_forward(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec())
    registry.clock.advance(seconds=100)
    await registry.store.hold(run.id)
    registry.clock.advance(seconds=ORPHAN_GRACE.total_seconds() - 1)

    due = await _due(registry, run.id)

    assert due is not None and not due.past_deadline
    assert (await _read(registry, run.id)).deadline_at == T0 + timedelta(seconds=100) + ORPHAN_GRACE


async def test_a_hold_never_moves_a_deadline_back(registry: Registry) -> None:
    """INVARIANT (R10): a late or slow hold never pulls the deadline in."""
    run = await registry.store.create(ALICE, start_spec())
    registry.clock.advance(seconds=100)
    await registry.store.hold(run.id)
    held = (await _read(registry, run.id)).deadline_at
    shorter = registry.restarted(survives_restart=True, orphan_grace=timedelta(seconds=10))

    await shorter.hold(run.id)

    assert (await _read(registry, run.id)).deadline_at == held


async def test_a_hold_leaves_a_detached_run_alone(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec(detach=True, deadline=timedelta(hours=2)))
    registry.clock.advance(hours=2)

    await registry.store.hold(run.id)

    assert (await _read(registry, run.id)).deadline_at == T0 + timedelta(hours=2)
    due = await _due(registry, run.id)
    assert due is not None and due.past_deadline and due.detached


async def test_a_hold_leaves_a_stopped_run_alone(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec())
    await registry.store.stop(run.id, "canceled")
    registry.clock.advance(seconds=100)

    await registry.store.hold(run.id)

    assert (await _read(registry, run.id)).deadline_at == T0 + ORPHAN_GRACE


async def test_a_hold_leaves_a_finished_run_alone(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec("alpha"))
    await _start(registry, run.id, 0)
    await registry.store.settle(_topic(0), CandidateOutcome("succeeded"))
    registry.clock.advance(seconds=100)

    await registry.store.hold(run.id)

    assert (await _read(registry, run.id)).deadline_at == T0 + ORPHAN_GRACE


async def test_a_run_without_starts_has_no_deadline_and_a_hold_gives_it_none(
    registry: Registry,
) -> None:
    """R10: a Client from before P2 follows no Run, so nothing may stop one for want of a
    follower."""
    run = await registry.store.create(ALICE, spec())

    await registry.store.hold(run.id)

    assert (await _read(registry, run.id)).deadline_at is None


async def test_with_the_orphan_rule_off_a_follower_holds_the_run_for_the_default_deadline(
    registry: Registry,
) -> None:
    """#1759 review round 5: with no hold, a Run still followed was stopped `orphaned` at 48 h.
    An unfollowed one still ends at the default deadline."""
    store = registry.restarted(survives_restart=True, orphan_grace=timedelta(0))
    run = await store.create(ALICE, start_spec())
    assert run.deadline_at == T0 + DEADLINE
    registry.clock.advance(seconds=100)

    await store.hold(run.id)

    assert (await _read(registry, run.id)).deadline_at == T0 + timedelta(seconds=100) + DEADLINE


async def test_a_detached_run_is_due_to_stop_at_its_deadline(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec(detach=True, deadline=timedelta(hours=2)))
    assert run.deadline_at == T0 + timedelta(hours=2)
    registry.clock.advance(hours=2, microseconds=-1)
    early = await _due(registry, run.id)
    assert early is not None and not early.past_deadline

    registry.clock.advance(microseconds=1)

    due = await _due(registry, run.id)
    assert due is not None and due.past_deadline


async def test_a_detached_run_without_a_deadline_gets_the_default(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec(detach=True))

    assert run.detached and run.deadline_at == T0 + DEADLINE


async def test_an_attached_run_stops_a_grace_after_its_creation_unless_held(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec())

    assert not run.detached and run.deadline_at == T0 + ORPHAN_GRACE


async def test_a_stopped_run_with_stops_still_owed_is_due_with_its_topics(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec())
    await _start(registry, run.id, 0)
    await registry.store.stop(run.id, "canceled")

    due = await _due(registry, run.id)

    assert due is not None and due.owed == (_topic(0),)
    await registry.store.stop_done(_topic(0))
    after = await _due(registry, run.id)
    assert after is None or after.owed == ()


# --- stop (R9, R12) ----------------------------------------------------------------------


async def test_a_stop_settles_unstarted_candidates_and_owes_a_stop_to_started_ones(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec("a", "b", "c"))
    await _start(registry, run.id, 0)
    await registry.store.bind(ALICE, run.id, 1, _topic(1))
    registry.clock.advance(seconds=5)

    assert await registry.store.stop(run.id, "orphaned") is True

    record = await _read(registry, run.id)
    # The bound Candidate's start may have landed, so it is owed a stop like a scheduled one.
    assert _states(record) == ["scheduled", "scheduled", "stopped"]
    assert record.candidates[1].started_at == T0.replace(second=5)
    assert record.stopped_by == "orphaned" and record.state == "running"
    assert sorted(await registry.store.owed_stops(ALICE, run.id)) == [_topic(0), _topic(1)]


async def test_the_first_stop_reason_wins(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec(detach=True))
    await _start(registry, run.id, 0)

    assert await registry.store.stop(run.id, "deadline") is True
    assert await registry.store.stop(run.id, "canceled") is False

    assert (await _read(registry, run.id)).stopped_by == "deadline"


@pytest.mark.parametrize(
    ("reason", "state"),
    [("canceled", "canceled"), ("orphaned", "interrupted"), ("deadline", "interrupted")],
)
async def test_a_stopped_run_reads_by_its_reason(
    registry: Registry, reason: StopReason, state: str
) -> None:
    run = await registry.store.create(ALICE, start_spec("a", "b"))
    await _start(registry, run.id, 0)
    await registry.store.settle(_topic(0), CandidateOutcome("succeeded"))

    await registry.store.stop(run.id, reason)

    assert (await _read(registry, run.id)).state == state


async def test_a_stop_on_a_finished_run_changes_nothing(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec("a"))
    await _start(registry, run.id, 0)
    await registry.store.settle(_topic(0), CandidateOutcome("succeeded"))
    before = await _read(registry, run.id)

    assert await registry.store.stop(run.id, "orphaned") is False

    assert await _read(registry, run.id) == before


async def test_a_deadline_stop_does_nothing_when_a_hold_moved_the_deadline_past_its_time(
    registry: Registry,
) -> None:
    """R11: a follower that came back between the tick's read and its stop keeps the Run."""
    run = await registry.store.create(ALICE, start_spec())
    registry.clock.advance(seconds=ORPHAN_GRACE.total_seconds() + 1)
    now = registry.clock()
    await registry.store.hold(run.id)

    stopped = await registry.store.stop(run.id, "orphaned", past_deadline_at=now)

    assert stopped is False
    assert (await _read(registry, run.id)).stopped_by is None


async def test_a_deadline_stop_stops_a_run_past_its_deadline(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec())
    registry.clock.advance(seconds=ORPHAN_GRACE.total_seconds())

    stopped = await registry.store.stop(run.id, "orphaned", past_deadline_at=registry.clock())

    assert stopped is True


async def test_a_stopped_run_takes_no_new_start(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec("a", "b"))
    await _start(registry, run.id, 0)
    await registry.store.stop(run.id, "deadline")

    with pytest.raises(RunCanceled):
        await registry.store.bind(ALICE, run.id, 1, _topic(1))


async def test_cancel_records_its_reason(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec())

    canceled = await registry.store.cancel(ALICE, run.id)

    assert canceled is not None
    assert (canceled.stopped_by, canceled.state) == ("canceled", "canceled")


async def test_cancel_answers_the_summary_without_starts_or_records(registry: Registry) -> None:
    """Review round 3: the cancel route reads only states and the flag, so a Run's starts (up to
    MiBs) and records are not loaded for it (spec §4.4: only `get` loads them)."""
    run = await registry.store.create(ALICE, start_spec())

    canceled = await registry.store.cancel(ALICE, run.id)

    assert canceled is not None
    assert all(c.start is None and c.record is None for c in canceled.candidates)


async def test_settle_startless_stops_only_pending_candidates_without_a_start(
    registry: Registry,
) -> None:
    old = await registry.store.create(ALICE, spec("alpha", "beta", client_key="p1"))
    await registry.store.bind(ALICE, old.id, 0, _topic(0))
    await registry.store.mark_scheduled(_topic(0))
    fresh = await registry.store.create(ALICE, start_spec("gamma", client_key="p2"))
    registry.clock.advance(seconds=P1_PENDING_GRACE_S + 1)

    assert await registry.store.settle_startless() == 1

    assert _states(await _read(registry, old.id)) == ["scheduled", "stopped"]
    assert _states(await _read(registry, fresh.id)) == ["pending"]


#: P1's pending grace (removed in P2): how long a released Client may take to start a Candidate
#: it registered, in admission, before its start lands.
P1_PENDING_GRACE_S = 1800


async def test_settle_startless_leaves_a_p1_run_its_client_is_still_starting(
    registry: Registry,
) -> None:
    """Review round 3: while a deploy rolls, an older App registers a released Client's Run and
    binds its starts one by one, each up to 900 s in admission. Until the Run has been idle for
    P1's pending grace, its pending Candidates are left for those starts."""
    old = await registry.store.create(ALICE, spec("alpha", "beta", client_key="p1"))
    registry.clock.advance(seconds=P1_PENDING_GRACE_S - 1)

    assert await registry.store.settle_startless() == 0

    assert _states(await _read(registry, old.id)) == ["pending", "pending"]


async def test_a_p1_candidate_settled_scheduled_keeps_its_bind_time_for_reconcile(
    registry: Registry,
) -> None:
    """#1759 review round 5: a new clock held a P1 start that never landed live for another
    48 h, in its owner's count of what is in flight."""
    from screamingface_engine.runs.models import Candidate

    old = await registry.store.create(ALICE, spec("alpha", client_key="p1"))
    # What a P1 App's bind writes: the topic, and the time it was bound.
    await Candidate.filter(run_id=old.id, index=0).update(topic=_topic(0), bound_at=T0)
    registry.clock.advance(seconds=P1_PENDING_GRACE_S + 1)
    await registry.store.settle_startless()

    registry.clock.advance(seconds=LOST_AFTER.total_seconds() - P1_PENDING_GRACE_S)
    await registry.store.reconcile()

    assert _states(await _read(registry, old.id)) == ["lost"]


async def test_the_room_leaves_out_a_p1_runs_candidates(registry: Registry) -> None:
    """#1759 review round 5: a P1 Run's Candidate may never have reached a runner, so it holds
    back none of its owner's new Runs."""
    old = await registry.store.create(ALICE, spec("alpha", "beta", client_key="p1"))
    for index in (0, 1):
        await registry.store.bind(ALICE, old.id, index, _topic(index))
        await registry.store.mark_scheduled(_topic(index))
    new = await registry.store.create(ALICE, start_spec("a", "b", client_key="p2"))

    plan = await registry.store.pending_starts(new.id, inflight=2)

    assert plan is not None and [p.index for p in plan.pending] == [0, 1]


# --- clocks and state (R8, R12) ----------------------------------------------------------


async def test_a_run_keeps_each_candidates_start_and_its_owners_email(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec("a", "b"))

    plan = await registry.store.pending_starts(run.id)

    assert plan is not None
    assert plan.owner == ALICE and plan.owner_email == "alice@example.org"
    assert plan.client_version == "1.2.3" and plan.in_flight == 0 and not plan.stopped
    assert [(p.index, p.start.name, p.start.url4, p.topic) for p in plan.pending] == [
        (0, "a", "openai/gpt-5?q=Hi", None),
        (1, "b", "openai/gpt-5?q=Hi", None),
    ]
    assert [c.start for c in (await _read(registry, run.id)).candidates] == [
        p.start for p in plan.pending
    ]


async def test_pending_starts_count_what_is_in_flight_and_keep_a_bound_topic(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec("a", "b", "c"))
    await _start(registry, run.id, 0)
    await registry.store.bind(ALICE, run.id, 1, _topic(1), trace_id="f" * 32)

    plan = await registry.store.pending_starts(run.id)

    assert plan is not None and plan.in_flight == 1
    assert [(p.index, p.topic, p.trace_id) for p in plan.pending] == [
        (1, _topic(1), "f" * 32),
        (2, None, None),
    ]


async def test_overdue_lists_the_runs_scheduled_candidates_bound_before_the_cutoff(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec("a", "b", "c"))
    await _start(registry, run.id, 0)
    registry.clock.advance(seconds=10)
    await _start(registry, run.id, 1)

    assert await registry.store.overdue(run.id, T0 + timedelta(seconds=5)) == [_topic(0)]


async def test_a_summary_reads_no_start_and_no_record(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec("a"))

    summary = await registry.store.summary(ALICE, run.id)
    listed = (await registry.store.list(ALICE, RunQuery())).runs[0]

    assert summary is not None
    assert summary.candidates[0].start is None and listed.candidates[0].start is None
    assert (await _read(registry, run.id)).candidates[0].start is not None


async def test_a_repeated_client_key_with_other_starts_or_deadline_is_refused(
    registry: Registry,
) -> None:
    await registry.store.create(ALICE, start_spec("a", detach=True))

    for other in (
        start_spec("a"),
        start_spec("a", detach=True, deadline=timedelta(hours=3)),
        spec("a"),
    ):
        with pytest.raises(ClientKeyConflict):
            await registry.store.create(ALICE, other)
    again = await registry.store.create(ALICE, start_spec("a", detach=True))
    assert again.detached


# --- retention (R13) ---------------------------------------------------------------------


async def test_expiring_lists_the_runs_created_before_the_cutoff(registry: Registry) -> None:
    old = await registry.store.create(ALICE, start_spec(client_key="old"))
    cutoff = registry.clock.advance(seconds=1)
    await registry.store.create(ALICE, start_spec(client_key="kept"))

    assert await registry.store.expiring(cutoff) == [old.id]


async def test_expire_deletes_only_the_runs_it_is_given(registry: Registry) -> None:
    first = await registry.store.create(ALICE, start_spec(client_key="first"))
    second = await registry.store.create(ALICE, start_spec(client_key="second"))

    assert await registry.store.expire([first.id]) == 1

    assert await registry.store.get(ALICE, first.id) is None
    assert await registry.store.get(ALICE, second.id) is not None
    assert await registry.store.expire([first.id]) == 0


async def test_the_context_reference_round_trips(registry: Registry) -> None:
    context = ContextRef(sha256="ab" * 32, size_bytes=1234)

    run = await registry.store.create(ALICE, start_spec(context=context))
    bare = await registry.store.create(ALICE, start_spec(client_key="bare"))

    assert run.context == context
    summary = await registry.store.summary(ALICE, run.id)
    assert summary is not None and summary.context == context
    assert bare.context is None


async def test_a_run_id_minted_by_the_route_is_the_runs_id(registry: Registry) -> None:
    run_id = "run_" + "c" * 32

    run = await registry.store.create(ALICE, replace(start_spec(), run_id=run_id))

    assert run.id == run_id


async def test_pending_starts_load_only_the_starts_there_is_room_for(registry: Registry) -> None:
    """WHY: a start may be most of a MiB, and the driver reads its plan every few seconds; a
    Run with no free slot must not load every waiting Candidate's start each time."""
    run = await registry.store.create(ALICE, start_spec("a", "b", "c", "d"))
    await _start(registry, run.id, 0)

    full = await registry.store.pending_starts(run.id, inflight=2)
    none = await registry.store.pending_starts(run.id, inflight=1)

    assert full is not None and none is not None
    assert [p.index for p in full.pending] == [1]
    assert (full.waiting, full.in_flight) == (3, 1)
    assert (none.pending, none.waiting) == ((), 3)


async def test_the_room_counts_what_the_owners_other_runs_have_in_flight(
    registry: Registry,
) -> None:
    """The runner caps a caller, not a Run: a Run waiting behind the same owner's other Run has
    no room, so it loads no start."""
    first = await registry.store.create(ALICE, start_spec("a", "b", client_key="k1"))
    second = await registry.store.create(ALICE, start_spec("a", "b", client_key="k2"))
    other = await registry.store.create(owner_key("bob@example.org"), start_spec("a"))
    for run_id, owner, index, topic in (
        (first.id, ALICE, 0, "t-first-0"),
        (first.id, ALICE, 1, "t-first-1"),
        (other.id, owner_key("bob@example.org"), 0, "t-bob-0"),
    ):
        await registry.store.bind(owner, run_id, index, topic)
        await registry.store.mark_scheduled(topic)

    blocked = await registry.store.pending_starts(second.id, inflight=2)
    one_slot = await registry.store.pending_starts(second.id, inflight=3)

    assert blocked is not None and one_slot is not None
    assert (blocked.pending, blocked.waiting, blocked.in_flight) == ((), 2, 0)
    assert [p.index for p in one_slot.pending] == [0]


# --- a cancel by an App from before P2 (R12, D12; review round 3) ----------------------------


async def _flagged_by_an_older_app(run_id: str) -> None:
    """What a P1 App's cancel writes during a rolling deploy: the flag, and no reason."""
    from screamingface_engine.runs.models import Run

    await Run.filter(id=run_id).update(canceled=True)


async def test_a_run_an_older_app_canceled_keeps_canceled_as_its_reason(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, start_spec())
    await _flagged_by_an_older_app(run.id)
    registry.clock.advance(seconds=ORPHAN_GRACE.total_seconds() + 1)

    stopped = await registry.store.stop(run.id, "orphaned", past_deadline_at=registry.clock())

    record = await _read(registry, run.id)
    assert stopped is True
    assert (record.stopped_by, record.state) == ("canceled", "canceled")
    assert {c.state for c in record.candidates} == {"stopped"}


async def test_a_run_an_older_app_canceled_is_due_to_finish_its_stop_at_once(
    registry: Registry,
) -> None:
    """Its pending Candidates are never started (the flag says stopped), so the tick settles
    them now instead of at a detached Run's deadline, days away."""
    run = await registry.store.create(ALICE, start_spec(detach=True))
    await _flagged_by_an_older_app(run.id)

    due = await _due(registry, run.id)
    stopped = await registry.store.stop(run.id, "deadline", past_deadline_at=registry.clock())

    assert due is not None and due.past_deadline
    assert stopped is True
    assert (await _read(registry, run.id)).stopped_by == "canceled"


async def test_a_hold_leaves_a_run_an_older_app_canceled_alone(registry: Registry) -> None:
    run = await registry.store.create(ALICE, start_spec())
    await _flagged_by_an_older_app(run.id)
    registry.clock.advance(seconds=100)

    await registry.store.hold(run.id)

    assert (await _read(registry, run.id)).deadline_at == T0 + ORPHAN_GRACE


async def test_due_runs_reads_the_live_runs_in_bounded_batches(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 3: one query never carries every live Run's id as a bound parameter, which
    past the database's parameter limit would fail every tick."""
    from screamingface_engine.runs import store_driver

    monkeypatch.setattr(store_driver, "_ID_BATCH", 2)
    runs = [await registry.store.create(ALICE, start_spec(client_key=f"k{i}")) for i in range(5)]

    due = await registry.store.due_runs(registry.clock())

    assert {d.run_id for d in due} == {run.id for run in runs}


async def test_a_repeated_detached_run_naming_no_deadline_matches_whatever_default_it_got(
    registry: Registry,
) -> None:
    """Review round 4: a retried `POST /runs` that names no deadline is the same request after
    an operator changes the default; it returns the Run, not `client_key_conflict`."""
    from screamingface_engine.runs.store import TortoiseRunStore

    run = await registry.store.create(ALICE, start_spec(detach=True))
    shorter = TortoiseRunStore(
        clock=registry.clock,
        lost_after=LOST_AFTER,
        outcomes_survive_restart=True,
        started_at=registry.clock(),
        orphan_grace=ORPHAN_GRACE,
        default_deadline=DEADLINE / 2,
    )

    again, created = await shorter.register(ALICE, start_spec(detach=True))

    assert (again.id, created) == (run.id, False)
    with pytest.raises(ClientKeyConflict):
        await shorter.register(ALICE, start_spec(detach=True, deadline=timedelta(hours=1)))
