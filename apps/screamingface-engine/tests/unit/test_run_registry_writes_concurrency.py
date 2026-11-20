"""E5 P1 spec §4.2, R4, D12: the registry's writes under concurrency and its edge answers.

FEATURE: first-class Runs (OME-1785). INVARIANT: every write locks its Run row first, so writes
to one Run never deadlock on Postgres, and a cancel never marks a Run that had finished.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    LOST_AFTER,
    ORPHAN_GRACE,
    T0,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
    start_spec,
)
from tortoise.backends.asyncpg.client import TransactionWrapper

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import owner_key
from screamingface_engine.runs.registry import ClientKeyConflict, RunCanceled

pytestmark = pytest.mark.asyncio
ALICE = owner_key("alice@openmined.org")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def test_a_repeated_client_key_for_another_evaluation_is_refused(
    registry: Registry,
) -> None:
    await registry.store.create(ALICE, spec("alpha"))

    with pytest.raises(ClientKeyConflict):
        await registry.store.create(ALICE, spec("alpha", "beta"))


async def test_expire_counts_the_runs_it_deleted_not_their_candidates(
    registry: Registry,
) -> None:
    await registry.store.create(ALICE, spec("alpha", "beta", "gamma"))
    registry.clock.advance(days=31)

    expiring = await registry.store.expiring(registry.clock() - timedelta(days=30))

    assert await registry.store.expire(expiring) == 1


async def test_concurrent_expiries_count_each_run_once(registry: Registry) -> None:
    await registry.store.create(ALICE, spec("alpha"))
    expiring = await registry.store.expiring(T0 + timedelta(seconds=1))

    counts = await asyncio.gather(registry.store.expire(expiring), registry.store.expire(expiring))

    assert sorted(counts) == [0, 1]


async def test_a_settled_candidate_ends_when_its_producer_saw_the_end(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, "t" * 64)
    seen = registry.clock()
    registry.clock.advance(hours=3)  # the outcome is written late, after an outage

    await registry.store.settle("t" * 64, CandidateOutcome("succeeded", finished_at=seen))

    record = await registry.store.get(ALICE, run.id)
    assert record is not None and record.candidates[0].finished_at == seen


async def test_a_cost_below_the_columns_precision_is_never_stored_as_zero(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, "t" * 64)

    await registry.store.settle("t" * 64, CandidateOutcome("succeeded", cost_usd=Decimal("5E-13")))

    record = await registry.store.get(ALICE, run.id)
    assert record is not None and record.candidates[0].cost_usd == Decimal("1E-12")


async def test_binds_and_a_cancel_of_one_run_never_deadlock(registry: Registry) -> None:
    run = await registry.store.create(ALICE, spec(*(f"c{i}" for i in range(8))))

    async def bind(index: int) -> None:
        try:
            await registry.store.bind(ALICE, run.id, index, f"{index:064d}")
        except RunCanceled:
            pass

    await asyncio.wait_for(
        asyncio.gather(*(bind(i) for i in range(8)), registry.store.cancel(ALICE, run.id)),
        timeout=30,
    )

    record = await registry.store.get(ALICE, run.id)
    assert record is not None and record.stopped_by == "canceled"
    # A bind either landed before the cancel, so its start may have landed and it stays
    # scheduled, owed a stop (R9), or was refused after it and the cancel stopped it.
    bound = sorted(f"{c.index:064d}" for c in record.candidates if c.state == "scheduled")
    assert {c.state for c in record.candidates} <= {"scheduled", "stopped"}
    assert sorted(await registry.store.owed_stops(ALICE, run.id)) == bound
    assert record.state == ("running" if bound else "canceled")


async def test_a_cancel_racing_the_last_outcome_never_cancels_a_finished_run(
    registry: Registry,
) -> None:
    run = await registry.store.create(ALICE, spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, "t" * 64)
    await registry.store.mark_scheduled("t" * 64)

    await asyncio.gather(
        registry.store.settle("t" * 64, CandidateOutcome("succeeded")),
        registry.store.cancel(ALICE, run.id),
    )

    record = await registry.store.get(ALICE, run.id)
    assert record is not None
    # Either the cancel applied while the Candidate was live, or the Run had finished first and
    # the cancel changed nothing (D12). The outcome is recorded either way.
    assert record.state in ("canceled", "complete")
    assert record.candidates[0].state == "succeeded"


# --- a hold and reconcile (OME-1992, review round 3) ---------------------------------------

_POSTGRES = [db for db in DATABASES if db.id == "postgres"]


@pytest_asyncio.fixture(params=_POSTGRES)
async def postgres_registry(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[Registry]:
    """WHY Postgres only: SQLite runs every statement of the store on one connection, which a
    transaction holds to its end, so reconcile cannot run inside a hold there at all."""
    async for opened in open_registry(request, tmp_path):
        yield opened


def _pause_before_the_deadline_update(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[asyncio.Event, asyncio.Event]:
    """Stop a hold just before its deadline UPDATE, after its lock and live check, until
    released. Returns (paused, release)."""
    paused, release = asyncio.Event(), asyncio.Event()
    execute = TransactionWrapper.execute_query

    async def pausing(
        self: TransactionWrapper, query: str, values: list[Any] | None = None
    ) -> tuple[int, list[dict[str, Any]]]:
        if query.lstrip().startswith('UPDATE "runs"') and '"deadline_at"' in query:
            paused.set()
            await release.wait()
        return await execute(self, query, values)

    monkeypatch.setattr(TransactionWrapper, "execute_query", pausing)
    return paused, release


async def _done_before_waiting(task: asyncio.Task[int], url: str) -> bool:
    """Whether ``task`` finished before any statement on the server waited for a lock."""
    conn = await asyncpg.connect(url)
    try:
        async with asyncio.timeout(10):
            while not task.done():
                if await conn.fetchval("SELECT count(*) FROM pg_locks WHERE NOT granted"):
                    return False
                await asyncio.sleep(0.01)
    finally:
        await conn.close()
    return True


async def test_reconcile_never_finishes_the_last_candidate_inside_a_hold(
    postgres_registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 3, finding 2: reconcile settles stale Candidates `lost` in one UPDATE,
    without the Run's lock that orders `hold` and `settle`. Between hold's live check and its
    deadline update it finished the Run's last Candidate, so the hold moved a finished Run's
    deadline. INVARIANT (R10): a hold moves the deadline only while a Candidate is live, so
    reconcile waits for a hold that saw one."""
    registry = postgres_registry
    run = await registry.store.create(ALICE, start_spec("alpha"))
    await registry.store.bind(ALICE, run.id, 0, "t" * 64)
    await registry.store.mark_scheduled("t" * 64)
    # Past `lost_after`: reconcile settles the Run's only Candidate `lost`.
    registry.clock.advance(seconds=LOST_AFTER.total_seconds() + 1)
    paused, release = _pause_before_the_deadline_update(monkeypatch)
    hold = asyncio.create_task(registry.store.hold(run.id))
    await asyncio.wait_for(paused.wait(), 10)

    reconcile = asyncio.create_task(registry.store.reconcile())
    finished_inside = await _done_before_waiting(reconcile, registry.url)
    inside = await registry.store.get(ALICE, run.id)
    release.set()
    await asyncio.wait_for(asyncio.gather(hold, reconcile), 10)
    after = await registry.store.get(ALICE, run.id)

    assert not finished_inside, "reconcile finished the Candidate between the check and update"
    assert inside is not None and inside.candidates[0].state == "scheduled"
    assert reconcile.result() == 1
    assert after is not None and after.candidates[0].state == "lost"
    # The hold landed while the Candidate was live; the Candidate ended after it.
    assert after.deadline_at == registry.clock() + ORPHAN_GRACE
