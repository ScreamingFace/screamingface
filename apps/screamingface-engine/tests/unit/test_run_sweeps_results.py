"""E5 P2 spec R13: retention deletes the objects a Run names before its rows.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my Run's results and context leave
the Engine with my Run, 30 days on, and none outlives it for long.

Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
    start_spec,
)

from screamingface_engine.artifacts.ports import ArtifactContent
from screamingface_engine.artifacts.run_results import context_key, result_key, result_prefix
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import ContextRef, owner_key
from screamingface_engine.runs.sweeps import RunSweeper

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
RETENTION = timedelta(days=30)
DIGEST = "a" * 64
# The empty result each run writes first, to check the store answers (spec R5).
PROBE = hashlib.sha256(b"").hexdigest()


class _Results:
    """A run-results store that records deletes, refusing those that name ``refused``."""

    def __init__(self, refused: str | None = None) -> None:
        self.deleted: list[str] = []
        self.refused = refused
        self.aged_before: list[datetime] = []

    def put(self, key: str, body: bytes) -> None:
        raise AssertionError("a sweep writes nothing")

    def open(self, key: str) -> ArtifactContent | None:
        return None

    def delete(self, keys: Iterable[str]) -> None:
        keys = list(keys)
        if self.refused is not None and self.refused in keys:
            raise OSError("the store refused the delete")
        self.deleted.extend(keys)

    def delete_older_than(self, cutoff: datetime) -> int:
        self.aged_before.append(cutoff)
        return 0


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def _finished_run(registry: Registry, client_key: str) -> str:
    """A Run with a context and one Candidate whose record names its result."""
    run, _ = await registry.store.register(
        ALICE, start_spec("a", client_key=client_key, context=ContextRef("c" * 64, 10))
    )
    topic = f"t-{client_key}"
    await registry.store.bind(ALICE, run.id, 0, topic)
    await registry.store.mark_scheduled(topic)
    record = {"result": {"media_type": "application/json", "size_bytes": 2, "sha256": DIGEST}}
    await registry.store.settle(topic, CandidateOutcome("succeeded", record=record))
    return run.id


def _sweeper(registry: Registry, results: _Results) -> RunSweeper:
    return RunSweeper(
        registry.store,
        retention=RETENTION,
        clock=registry.clock,
        results=results,
        objects=registry.store.stored_objects,
    )


async def test_a_run_names_its_context_and_its_recorded_results(registry: Registry) -> None:
    run_id = await _finished_run(registry, "k1")

    keys = await registry.store.stored_objects([run_id])

    assert sorted(keys[run_id]) == sorted(
        [
            context_key(run_id),
            result_key(result_prefix(run_id, 0), DIGEST),
            result_key(result_prefix(run_id, 0), PROBE),
        ]
    )


async def test_a_candidate_with_no_record_still_names_its_probe(registry: Registry) -> None:
    """A run that failed after its probe leaves that object; a store with no lifecycle rule (the
    bundled Garage) would otherwise keep it for good."""
    run, _ = await registry.store.register(ALICE, start_spec("a", "b", "c"))
    for index in (0, 1):
        await registry.store.bind(ALICE, run.id, index, f"t-probe-{index}")

    keys = await registry.store.stored_objects([run.id])

    # The third never started, so it wrote no probe and names none.
    assert sorted(keys[run.id]) == sorted(
        [result_key(result_prefix(run.id, i), PROBE) for i in (0, 1)]
    )


async def test_a_sweep_deletes_a_runs_objects_and_then_its_rows(registry: Registry) -> None:
    run_id = await _finished_run(registry, "k1")
    results = _Results()
    registry.clock.advance(days=31)

    await _sweeper(registry, results).sweep_once()

    assert sorted(results.deleted) == sorted(
        [
            context_key(run_id),
            result_key(result_prefix(run_id, 0), DIGEST),
            result_key(result_prefix(run_id, 0), PROBE),
        ]
    )
    assert await registry.store.get(ALICE, run_id) is None


async def test_a_run_whose_delete_failed_keeps_its_rows_and_the_others_go(
    registry: Registry,
) -> None:
    kept = await _finished_run(registry, "k1")
    gone = await _finished_run(registry, "k2")
    results = _Results(refused=context_key(kept))
    registry.clock.advance(days=31)

    await _sweeper(registry, results).sweep_once()

    assert await registry.store.get(ALICE, kept) is not None
    assert await registry.store.get(ALICE, gone) is None


async def test_what_no_run_names_is_removed_by_age_a_day_after_the_retention(
    registry: Registry,
) -> None:
    results = _Results()

    await _sweeper(registry, results).sweep_once()

    assert results.aged_before == [registry.clock() - RETENTION - timedelta(days=1)]
