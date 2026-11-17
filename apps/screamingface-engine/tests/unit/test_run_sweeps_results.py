"""E5 P2 spec R13: retention deletes a Run's rows, and its objects go by age alone.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my Run's results and context leave
the Engine with my Run, 30 days on, and none outlives it for long.

WHY by age (#1759 review round 5): the bucket's lifecycle rule on S3, and `delete_older_than` in
a folder, remove every object a day after the retention, so a sweep deletes nothing by name.

Same databases as `test_run_registry_contract.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO

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
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.records import ContextRef, owner_key
from screamingface_engine.runs.sweeps import RunSweeper

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
RETENTION = timedelta(days=30)
DIGEST = "a" * 64


class _Results:
    """A run-results store that records how it is asked to remove objects."""

    def __init__(self) -> None:
        self.aged_before: list[datetime] = []

    def put(self, key: str, body: bytes) -> None:
        raise AssertionError("a sweep writes nothing")

    def put_file(self, key: str, handle: IO[bytes], size: int, sha256: str) -> None:
        raise AssertionError("a sweep writes nothing")

    def open(self, key: str) -> ArtifactContent | None:
        raise AssertionError("a sweep reads nothing")

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
    return RunSweeper(registry.store, retention=RETENTION, clock=registry.clock, results=results)


async def test_a_sweep_expires_the_rows_and_leaves_the_objects_to_their_age(
    registry: Registry,
) -> None:
    run_id = await _finished_run(registry, "k1")
    results = _Results()
    registry.clock.advance(days=31)

    await _sweeper(registry, results).sweep_once()

    assert await registry.store.get(ALICE, run_id) is None
    assert results.aged_before == [registry.clock() - RETENTION - timedelta(days=1)]


async def test_the_apps_start_settles_lost_candidates_and_leaves_retention_to_the_loop(
    registry: Registry,
) -> None:
    """#1759 review round 5: retention waits for the loop, so nothing it does holds the App's
    start."""
    run_id = await _finished_run(registry, "k1")
    results = _Results()
    registry.clock.advance(days=31)

    await _sweeper(registry, results).reconcile()

    assert results.aged_before == []
    assert await registry.store.get(ALICE, run_id) is not None
