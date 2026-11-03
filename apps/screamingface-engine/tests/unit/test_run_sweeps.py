"""E5 P1 spec R6 and R7, the App's Run sweeps: reconcile and retention, at start and hourly.

FEATURE: first-class Runs (OME-1785). The store's own queries are pinned by
`test_run_registry_lifecycle.py`; these drive them through the sweep the App runs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    LOST_AFTER,
    Clock,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    spec,
)

from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import RunRecord, owner_key
from screamingface_engine.runs.store import TortoiseRunStore
from screamingface_engine.runs.sweeps import RunSweeper

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
RETENTION = timedelta(days=30)


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


def _topic(run: int, index: int) -> str:
    return f"{run}{index}".ljust(64, "0")


async def _run(registry: Registry, count: int, key: str = "key-1") -> str:
    names = tuple(f"c{index}" for index in range(count))
    return (await registry.store.create(ALICE, spec(*names, client_key=key))).id


async def _read(registry: Registry, run_id: str) -> RunRecord:
    record = await registry.store.get(ALICE, run_id)
    assert record is not None
    return record


def _sweeper(registry: Registry, store: TortoiseRunStore | None = None) -> RunSweeper:
    return RunSweeper(store or registry.store, retention=RETENTION, clock=registry.clock)


async def test_reconcile_writes_only_lost_and_no_cost(registry: Registry) -> None:
    run_id = await _run(registry, 2)
    await registry.store.bind(ALICE, run_id, 0, _topic(1, 0))
    await registry.store.bind(ALICE, run_id, 1, _topic(1, 1))
    await registry.store.mark_scheduled(_topic(1, 1))
    registry.clock.advance(seconds=LOST_AFTER.total_seconds() + 1)

    await _sweeper(registry).sweep_once()

    record = await _read(registry, run_id)
    assert [c.state for c in record.candidates] == ["lost", "lost"]
    assert [c.cost_usd for c in record.candidates] == [None, None]
    assert [c.error_code for c in record.candidates] == [None, None]


async def test_a_surviving_stream_settles_only_candidates_past_the_cutoff(
    registry: Registry,
) -> None:
    run_id = await _run(registry, 2)
    await registry.store.bind(ALICE, run_id, 0, _topic(1, 0))
    registry.clock.advance(hours=1)
    await registry.store.bind(ALICE, run_id, 1, _topic(1, 1))
    registry.clock.advance(seconds=LOST_AFTER.total_seconds() - 3600 + 1)

    await _sweeper(registry).sweep_once()

    assert [c.state for c in (await _read(registry, run_id)).candidates] == ["lost", "pending"]


async def test_a_hosted_restart_leaves_a_queued_candidate_to_its_worker(
    registry: Registry,
) -> None:
    """Spec R6: JetStream keeps the outcome across the restart, so the worker still settles it."""
    run_id = await _run(registry, 1)
    await registry.store.bind(ALICE, run_id, 0, _topic(1, 0))
    await registry.store.mark_scheduled(_topic(1, 0))
    registry.clock.advance(minutes=5)
    restarted = registry.restarted(survives_restart=True)

    await _sweeper(registry, restarted).sweep_once()
    assert (await _read(registry, run_id)).candidates[0].state == "scheduled"

    await restarted.settle(_topic(1, 0), CandidateOutcome("succeeded", cost_usd=Decimal("0.25")))
    candidate = (await _read(registry, run_id)).candidates[0]
    assert (candidate.state, candidate.cost_usd) == ("succeeded", Decimal("0.25"))


async def test_a_local_restart_settles_every_in_flight_candidate_lost(registry: Registry) -> None:
    """Spec R6: an in-memory stream died with the old process, and its outcomes with it."""
    run_id = await _run(registry, 3)
    await registry.store.bind(ALICE, run_id, 0, _topic(1, 0))
    await registry.store.bind(ALICE, run_id, 1, _topic(1, 1))
    await registry.store.mark_scheduled(_topic(1, 1))
    registry.clock.advance(seconds=1)
    restarted = registry.restarted(survives_restart=False)

    await _sweeper(registry, restarted).sweep_once()

    # The unbound Candidate is the R5 grace's, not reconcile's.
    states = [c.state for c in (await _read(registry, run_id)).candidates]
    assert states == ["lost", "lost", "pending"]


async def test_expire_deletes_only_runs_older_than_the_retention(registry: Registry) -> None:
    old = await _run(registry, 1, key="old")
    registry.clock.advance(seconds=RETENTION.total_seconds() - 60)
    kept = await _run(registry, 1, key="kept")
    registry.clock.advance(seconds=61)

    await _sweeper(registry).sweep_once()

    assert await registry.store.get(ALICE, old) is None
    assert await registry.store.get(ALICE, kept) is not None


# --- the loop ----------------------------------------------------------------------------


class _FlakyRegistry:
    """Fails its first sweep, then counts the ones after."""

    def __init__(self) -> None:
        self.reconciles = 0
        self.cutoffs: list[datetime] = []

    async def reconcile(self) -> int:
        self.reconciles += 1
        if self.reconciles == 1:
            raise ConnectionError("database down")
        return 0

    async def expire(self, older_than: datetime) -> int:
        self.cutoffs.append(older_than)
        return 0


async def test_a_failed_sweep_is_logged_and_the_cadence_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    flaky = _FlakyRegistry()
    sweeper = RunSweeper(flaky, retention=RETENTION, clock=clock)

    with caplog.at_level(logging.ERROR):
        task = asyncio.create_task(sweeper.run(interval_s=0.01))
        while flaky.reconciles < 3:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "Run sweep failed" in caplog.text
    assert flaky.cutoffs[0] == clock() - RETENTION
