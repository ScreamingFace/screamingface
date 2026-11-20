"""E5 P1 spec §6, the registry contract: cancel (D12), state on read (R5), reconcile (R6) and
expire (R7), as E5 P2 spec R8, R9, R12 and R13 change them.

FEATURE: first-class Runs (OME-1785). Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    LOST_AFTER,
    T0,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
)

from screamingface_engine.candidate_outcomes import CandidateOutcome, OutcomeStatus
from screamingface_engine.runs.records import RunRecord, RunState, owner_key

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def _topic(index: int) -> str:
    return str(index) * 64


async def _run(registry: Registry, count: int) -> str:
    names = tuple(f"c{index}" for index in range(count))
    return (await registry.store.create(ALICE, spec(*names))).id


async def _start(registry: Registry, run_id: str, *indexes: int) -> None:
    for index in indexes:
        await registry.store.bind(ALICE, run_id, index, _topic(index))
        await registry.store.mark_scheduled(_topic(index))


async def _read(registry: Registry, run_id: str) -> RunRecord:
    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    return record


def _states(record: RunRecord) -> list[str]:
    return [candidate.state for candidate in record.candidates]


# --- cancel ------------------------------------------------------------------------------


async def test_cancel_stops_pending_candidates_and_leaves_live_ones(registry: Registry) -> None:
    run_id = await _run(registry, 3)
    await _start(registry, run_id, 0)

    canceled = await registry.store.cancel(ALICE, run_id)

    assert canceled is not None
    assert _states(canceled) == ["scheduled", "stopped", "stopped"]
    assert canceled.state == "running"
    await registry.store.settle(_topic(0), CandidateOutcome("stopped"))
    assert (await _read(registry, run_id)).state == "canceled"


async def test_a_run_of_pending_candidates_reads_canceled_at_once(registry: Registry) -> None:
    run_id = await _run(registry, 2)

    canceled = await registry.store.cancel(ALICE, run_id)

    assert canceled is not None and canceled.state == "canceled"
    assert canceled.finished_at == T0


async def test_cancel_settles_a_run_that_waited_days_for_a_slot(registry: Registry) -> None:
    """E5 P2 spec R12: a `pending` Candidate is live however long it waits, until a stop."""
    run_id = await _run(registry, 2)
    registry.clock.advance(days=3)
    assert (await _read(registry, run_id)).state == "running"

    canceled = await registry.store.cancel(ALICE, run_id)

    assert canceled is not None and canceled.state == "canceled"


async def test_cancel_is_sticky(registry: Registry) -> None:
    run_id = await _run(registry, 2)
    await _start(registry, run_id, 0)
    await registry.store.cancel(ALICE, run_id)
    await registry.store.settle(_topic(0), CandidateOutcome("succeeded"))

    again = await registry.store.cancel(ALICE, run_id)

    assert again is not None and again.state == "canceled"
    assert _states(again) == ["succeeded", "stopped"]


async def test_cancel_changes_nothing_once_every_candidate_is_terminal(registry: Registry) -> None:
    """INVARIANT (spec D12): a cancel never rewrites a run that has finished."""
    run_id = await _run(registry, 1)
    await _start(registry, run_id, 0)
    await registry.store.settle(_topic(0), CandidateOutcome("succeeded"))
    before = await _read(registry, run_id)
    registry.clock.advance(minutes=5)

    after = await registry.store.cancel(ALICE, run_id)

    assert after is not None
    assert after == before and after.state == "complete"


async def test_cancelling_an_unknown_or_foreign_run_finds_nothing(registry: Registry) -> None:
    run_id = await _run(registry, 1)

    assert await registry.store.cancel(owner_key("bob@example.org"), run_id) is None
    assert await registry.store.cancel(ALICE, "run_" + "0" * 32) is None


# --- state on read (R5) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcomes", "state"),
    [
        (("succeeded", "succeeded"), "complete"),
        (("succeeded", "failed"), "partial"),
        (("succeeded", "timed_out"), "partial"),
        (("failed", "timed_out"), "errored"),
        (("succeeded", "stopped"), "interrupted"),
    ],
)
async def test_the_state_follows_the_candidates(
    registry: Registry, outcomes: tuple[OutcomeStatus, ...], state: RunState
) -> None:
    run_id = await _run(registry, len(outcomes))
    await _start(registry, run_id, *range(len(outcomes)))

    for index, status in enumerate(outcomes):
        await registry.store.settle(_topic(index), CandidateOutcome(status))

    assert (await _read(registry, run_id)).state == state


async def test_a_pending_run_stays_running_with_no_write(registry: Registry) -> None:
    """E5 P2 spec R12: the clock alone never ends a Run; the driver starts its Candidates, or
    a stop settles them."""
    run_id = await _run(registry, 2)

    registry.clock.advance(days=3)

    assert (await _read(registry, run_id)).state == "running"
    assert (await _read(registry, run_id)).finished_at is None


async def test_a_late_bind_reads_running_again(registry: Registry) -> None:
    run_id = await _run(registry, 2)
    registry.clock.advance(hours=1)

    await _start(registry, run_id, 0)

    assert (await _read(registry, run_id)).state == "running"


async def test_finished_at_is_the_last_candidates(registry: Registry) -> None:
    run_id = await _run(registry, 2)
    await _start(registry, run_id, 0, 1)
    registry.clock.advance(minutes=1)
    await registry.store.settle(
        _topic(1), CandidateOutcome("succeeded", finished_at=registry.clock())
    )
    assert (await _read(registry, run_id)).finished_at is None
    end = registry.clock.advance(minutes=1)

    await registry.store.settle(_topic(0), CandidateOutcome("succeeded", finished_at=end))

    assert (await _read(registry, run_id)).finished_at == end


# --- reconcile (R6) ----------------------------------------------------------------------


async def test_reconcile_with_a_surviving_stream_waits_out_the_cutoff(registry: Registry) -> None:
    run_id = await _run(registry, 3)
    await _start(registry, run_id, 0)
    await registry.store.bind(ALICE, run_id, 1, _topic(1))
    registry.clock.advance(seconds=LOST_AFTER.total_seconds())

    assert await registry.store.reconcile() == 0
    registry.clock.advance(seconds=1)
    # E5 P2 spec R8: only a sent start owes an outcome; a bound `pending` one was never sent.
    assert await registry.store.reconcile() == 1

    record = await _read(registry, run_id)
    assert _states(record) == ["lost", "pending", "pending"]
    assert record.state == "running"


async def test_reconcile_never_touches_a_terminal_candidate(registry: Registry) -> None:
    run_id = await _run(registry, 2)
    await _start(registry, run_id, 0, 1)
    await registry.store.settle(_topic(0), CandidateOutcome("succeeded"))
    registry.clock.advance(seconds=LOST_AFTER.total_seconds() + 1)

    assert await registry.store.reconcile() == 1

    assert _states(await _read(registry, run_id)) == ["succeeded", "lost"]
    assert await registry.store.reconcile() == 0


async def test_reconcile_with_a_lost_stream_settles_only_pre_restart_binds(
    registry: Registry,
) -> None:
    """Spec R6: an in-memory stream died with the old process, so its outcomes never come."""
    run_id = await _run(registry, 3)
    await _start(registry, run_id, 0)
    registry.clock.advance(minutes=1)
    restarted = registry.restarted(survives_restart=False)
    registry.clock.advance(minutes=1)
    await registry.store.bind(ALICE, run_id, 1, _topic(1))

    assert await restarted.reconcile() == 1

    assert _states(await _read(registry, run_id)) == ["lost", "pending", "pending"]


async def test_reconcile_on_a_lost_stream_still_honours_the_cutoff(registry: Registry) -> None:
    run_id = await _run(registry, 1)
    restarted = registry.restarted(survives_restart=False)
    await _start(registry, run_id, 0)
    registry.clock.advance(seconds=LOST_AFTER.total_seconds() + 1)

    assert await restarted.reconcile() == 1


# --- expire (R7) -------------------------------------------------------------------------


async def test_expire_deletes_exactly_the_runs_created_before_the_cutoff(
    registry: Registry,
) -> None:
    old = await registry.store.create(ALICE, spec(client_key="old"))
    cutoff = registry.clock.advance(seconds=1)
    kept = await registry.store.create(ALICE, spec(client_key="kept"))
    registry.clock.advance(days=40)

    assert await registry.store.expire(await registry.store.expiring(cutoff)) == 1

    assert await registry.store.get(ALICE, old.id) is None
    assert await registry.store.get(ALICE, kept.id) is not None
    assert await registry.store.expire(await registry.store.expiring(cutoff)) == 0


async def test_an_expired_runs_topics_can_be_bound_again(registry: Registry) -> None:
    """WHY: its Candidates go with it, so no orphan row keeps a topic's unique slot."""
    old = await registry.store.create(ALICE, spec("alpha", client_key="old"))
    await registry.store.bind(ALICE, old.id, 0, _topic(0))
    registry.clock.advance(seconds=1)
    await registry.store.expire(await registry.store.expiring(registry.clock()))
    fresh = await registry.store.create(ALICE, spec("alpha", client_key="new"))

    await registry.store.bind(ALICE, fresh.id, 0, _topic(0))

    assert (await _read(registry, fresh.id)).candidates[0].attempt_id == _topic(0)
