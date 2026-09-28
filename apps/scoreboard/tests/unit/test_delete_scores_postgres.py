"""The selected scores are LOCKED from digest check to delete (review round 2, OME-1385).

WHY this needs PostgreSQL: the benchmark lock serialises submit and replay, but not every write
takes it (`ScoreStore.mark_verified` updates a score directly). Without a row lock, a score could
change after its digest matched the reviewed backup and before it was deleted, so the command would
delete a row that differs from the backup. SQLite cannot show row locks, so this file lives in the
PostgreSQL CI lane.

WHY a self-contained connection: the same reason `scores/test_idempotency_postgres.py` gives
(OME-430). Runs only when SCOREBOARD_TEST_DATABASE_URL is set; skips otherwise.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest
from tortoise import BaseDBAsyncClient, Tortoise

from scoreboard import delete_scores as module
from scoreboard.db import build_tortoise_config
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
BOARD = "delete-lock-pg"
CUTOFF = datetime(2030, 1, 1, tzinfo=UTC)


async def _seed() -> uuid.UUID:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id=BOARD, display_name="Lock")
    outcome = await store.submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id="a",
            url4_expression="url4://a",
            submitted_by="tester@example.test",
            score=0.5,
            total_questions=100,
            ran_with_providers=["openrouter"],
            run_cost_usd=Decimal("1.00"),
            run_cost_status="complete",
        )
    )
    return outcome.score.id


async def _try_to_take(score_id: uuid.UUID) -> str:
    """A writer OUTSIDE the deleting transaction tries to lock the same row, without waiting."""
    other = await asyncpg.connect(DATABASE_URL.replace("postgres://", "postgresql://", 1))
    try:
        await other.execute("SELECT 1 FROM scores WHERE id = $1 FOR UPDATE NOWAIT", score_id)
        return "acquired"
    except asyncpg.exceptions.LockNotAvailableError:
        return "locked"
    finally:
        await other.close()


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_the_selected_rows_are_locked_when_the_delete_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    try:
        await Tortoise.generate_schemas(safe=True)
        score_id = await _seed()
        probe: list[str] = []
        real = module._delete_rows

        async def _probe_then_delete(connection: BaseDBAsyncClient, ids: list[uuid.UUID]) -> int:
            probe.append(await _try_to_take(score_id))
            return await real(connection, ids)

        reviewed = await module.delete_scores(BOARD, submitted_before=CUTOFF, expected=1)
        monkeypatch.setattr(module, "_delete_rows", _probe_then_delete)
        await module.delete_scores(
            BOARD,
            submitted_before=CUTOFF,
            expected=1,
            confirmed=True,
            expected_sha256=reviewed.sha256(),
        )

        # INVARIANT: nobody else could take the row between the digest check and the delete.
        assert probe == ["locked"]
        assert not await Score.filter(id=score_id).exists()
    finally:
        await Score.filter(benchmark_id=BOARD).delete()
        await Benchmark.filter(id=BOARD).delete()
        await Tortoise.close_connections()
