"""PB-8 — only one worker leases a publish row, on PostgreSQL (erd 2.6, PB-D2).

FEATURE: OME-1307 (E14). INVARIANT under test: `PublicationStore.lease_next` hands one due row to
exactly one worker, and a worker never waits on a row another worker holds (SKIP LOCKED).

WHY a self-contained connection and not the `tortoise_db` fixture: same reason as
`test_idempotency_postgres.py` (OME-430). Runs only when SCOREBOARD_TEST_DATABASE_URL is set.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest
from tortoise import Tortoise

from scoreboard.db import build_tortoise_config
from scoreboard.scores.models import Benchmark, CacheVersionPublication, ReportedResult, Score
from scoreboard.scores.publication_store import LEASE_S, PublicationStore

asyncpg = import_module("asyncpg")

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
_BOARD = "publish-lease-pg"
_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


async def _one_due_row() -> None:
    await Benchmark.create(id=_BOARD, display_name="Lease", redistributable=True)
    head = await Score.create(
        benchmark_id=_BOARD,
        spec_id="spec",
        url4_expression="(https://model.test/a)!'x'",
        submitted_by="ana@x.org",
        score=0.5,
        total_questions=2,
        ran_with_providers=[],
    )
    result = await ReportedResult.create(
        head=head,
        is_original=True,
        reporter="ana@x.org",
        score=0.5,
        total_questions=2,
        cache_version_id="6f1c1d0a-0000-4000-8000-000000000001",
        cache_version_sha256="a" * 64,
    )
    await CacheVersionPublication.create(
        result=result, state="requested", requested_at=_NOW, release_tag="cv-x"
    )


async def _cleanup() -> None:
    # Remove only what this test created: the database may be shared.
    # WHY ids first: PostgreSQL has no `DELETE ... LEFT JOIN`, which a filter across a relation
    # would render.
    head_ids = await Score.filter(benchmark_id=_BOARD).values_list("id", flat=True)
    result_ids = await ReportedResult.filter(head_id__in=head_ids).values_list("id", flat=True)
    await CacheVersionPublication.filter(result_id__in=result_ids).delete()
    await ReportedResult.filter(id__in=result_ids).delete()
    await Score.filter(id__in=head_ids).delete()
    await Benchmark.filter(id=_BOARD).delete()


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_only_one_worker_leases_a_row() -> None:
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    try:
        await Tortoise.generate_schemas(safe=True)
        await _one_due_row()
        store = PublicationStore("https://scoreboard.test")

        first, second = await asyncio.gather(store.lease_next(_NOW), store.lease_next(_NOW))

        assert [job is not None for job in (first, second)].count(True) == 1
        # A third call before the lease ends finds nothing, and one after it ends finds the job.
        assert await store.lease_next(_NOW + timedelta(seconds=LEASE_S - 1)) is None
        again = await store.lease_next(_NOW + timedelta(seconds=LEASE_S + 1))
        assert again is not None
    finally:
        await _cleanup()
        await Tortoise.close_connections()


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_a_worker_does_not_wait_for_a_row_another_worker_holds() -> None:
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    try:
        await Tortoise.generate_schemas(safe=True)
        await _one_due_row()
        store = PublicationStore("https://scoreboard.test")

        row = await CacheVersionPublication.filter(release_tag="cv-x").first()
        assert row is not None
        # WHY a raw connection for the holder: Tortoise reuses the current transaction for any
        # nested `in_transaction()`, in this task and in a task it starts, so the second read
        # would run on the holder's own connection and never contend for the lock.
        holder = await asyncpg.connect(DATABASE_URL)
        try:
            async with holder.transaction():
                await holder.fetchrow(
                    "SELECT id FROM cache_version_publication WHERE id = $1 FOR UPDATE", row.id
                )
                # WHY a timeout: without SKIP LOCKED the second read would wait for `holder` to
                # end, which never happens inside this block.
                skipped = await asyncio.wait_for(store.lease_next(_NOW), timeout=5)
        finally:
            await holder.close()

        assert skipped is None
    finally:
        await _cleanup()
        await Tortoise.close_connections()
