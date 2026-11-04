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

import pytest
import pytest_asyncio
from run_registry_support import DATABASES, T0, Registry, open_registry, spec

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

    assert await registry.store.expire(registry.clock() - timedelta(days=30)) == 1


async def test_concurrent_expiries_count_each_run_once(registry: Registry) -> None:
    await registry.store.create(ALICE, spec("alpha"))
    cutoff = T0 + timedelta(seconds=1)

    counts = await asyncio.gather(registry.store.expire(cutoff), registry.store.expire(cutoff))

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
    assert record is not None and record.state == "canceled"
    # A bind either landed before the cancel, which then stopped it, or was refused after it.
    assert {c.state for c in record.candidates} == {"stopped"}


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
