"""The clustered submit on a real database: SC-10 (race) and SC-17a (results-list p99).

WHY PostgreSQL: SQLite serializes writers and takes no row lock, so two concurrent submits to one
board never overlap there. On PostgreSQL the benchmark row lock (`lock_visibility`) makes the 2nd
submit wait for the first, and the partial unique index I-S1 plus the unique `run_id` are what
turn a lost race into a retry.

WHY a self-contained connection: the same reason `test_idempotency_postgres.py` gives (OME-430).
Runs only when SCOREBOARD_TEST_DATABASE_URL is set; skips otherwise. CI runs it in the `postgres`
job of scoreboard-tests.yml (`test_postgres_regressions_run_in_ci.py` checks the name is listed).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from tortoise import Tortoise

from scoreboard.adapters.url4_fingerprinter import Url4Fingerprinter
from scoreboard.core.paging import Cursor
from scoreboard.core.registry import RegistryService
from scoreboard.db import build_tortoise_config
from scoreboard.scores.cluster_store import ClusterOutcome, ClusterStore
from scoreboard.scores.models import (
    Benchmark,
    ReportedResult,
    Score,
    System,
    SystemRevision,
)
from scoreboard.scores.models.partial_indexes import create_partial_unique_indexes
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore
from scoreboard.scores.system_registry_store import TortoiseSystemRepository

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
ANA = "ana@x.org"
BRUNO = "bruno@y.org"

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def _database(board: str, name: str) -> AsyncIterator[ClusterStore]:
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    try:
        await Tortoise.generate_schemas(safe=True)
        await create_partial_unique_indexes(Tortoise.get_connection("default"))
        await Benchmark.create(id=board, display_name=board)
        registry = RegistryService(TortoiseSystemRepository(), Url4Fingerprinter())
        yield ClusterStore(ScoreStore(), registry)
    finally:
        # Clean only this test's rows: the database may be shared, and the ids are per run.
        # WHY one delete: the foreign keys of `reported_result` and `cache_version_publication`
        # cascade from the head (D8), so the head takes its results with it.
        await Score.filter(benchmark_id=board).delete()
        system = await System.get_or_none(name=name)
        if system is not None:
            await SystemRevision.filter(system_id=system.id).delete()
            await system.delete()
        await Benchmark.filter(id=board).delete()
        await Tortoise.close_connections()


def _submission(board: str, name: str, who: str, score: float) -> ScoreSubmission:
    # WHY the url4 carries the run's name: a fingerprint is unique across ALL systems, so a fixed
    # text would land on the system that an earlier run left behind.
    return ScoreSubmission(
        benchmark_id=board,
        spec_id=name,
        url4_expression=f"(https://model.test/{name})!'answer'",
        submitted_by=who,
        score=score,
        total_questions=10,
        ran_with_providers=["openai"],
    )


async def _submit(store: ClusterStore, submission: ScoreSubmission, key: str) -> ClusterOutcome:
    return await store.submit(submission, idempotency_key=key, identity_verified=True, claims=None)


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_concurrent_new_cluster_one_head_loser_becomes_result() -> None:
    board, name = f"cluster-{uuid4().hex[:12]}", f"race-{uuid4().hex[:12]}"
    async with _database(board, name) as store:
        ana, bruno = await asyncio.gather(
            _submit(store, _submission(board, name, ANA, 0.5), "ana-run"),
            _submit(store, _submission(board, name, BRUNO, 0.6), "bruno-run"),
        )

        assert ana.head.id == bruno.head.id
        assert await Score.filter(benchmark_id=board).count() == 1
        results = await ReportedResult.filter(head_id=ana.head.id)
        assert len(results) == 2
        assert sum(1 for row in results if row.is_original) == 1
        assert sorted(o.kind for o in (ana, bruno)) == ["new_head", "reported_result"]
        assert await System.filter(name=name).count() == 1


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_results_page_p99_under_200ms_at_10000_results() -> None:
    board, name = f"cluster-{uuid4().hex[:12]}", f"page-{uuid4().hex[:12]}"
    async with _database(board, name) as store:
        head = (await _submit(store, _submission(board, name, ANA, 0.5), "run-0")).head
        rows = [
            ReportedResult(head_id=head.id, is_original=False, score=0.5, total_questions=10)
            for _ in range(10_000)
        ]
        for start in range(0, len(rows), 1_000):
            await ReportedResult.bulk_create(rows[start : start + 1_000])

        times: list[float] = []
        after: Cursor | None = None
        for _ in range(100):
            began = time.perf_counter()
            page = await store.results_page(head.id, after=after, limit=50)
            times.append(time.perf_counter() - began)
            last = page[49]
            after = Cursor(submitted_at=last.submitted_at, id=last.id)

        assert sorted(times)[98] <= 0.200
