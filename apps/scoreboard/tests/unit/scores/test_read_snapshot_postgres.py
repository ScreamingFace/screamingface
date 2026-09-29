"""`ScoreStore.read_snapshot()` really holds one snapshot on PostgreSQL (review round 1, OME-1145).

WHY this needs PostgreSQL: its default, READ COMMITTED, gives every statement a fresh snapshot, so
the frontier route's three reads could see three different boards. The fix sets REPEATABLE READ
at the start of the transaction. SQLite cannot show the difference, which is why this file lives
in the PostgreSQL CI lane.

WHY a self-contained connection: the same reason `test_idempotency_postgres.py` gives (OME-430).

Runs only when SCOREBOARD_TEST_DATABASE_URL is set; skips otherwise.
"""

from __future__ import annotations

import os
from decimal import Decimal

import asyncpg
import pytest
from tortoise import Tortoise

from scoreboard.db import build_tortoise_config
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
BOARD = "snapshot-pg"


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_a_write_committed_mid_snapshot_is_not_seen_by_later_reads() -> None:
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    try:
        await Tortoise.generate_schemas(safe=True)
        store = ScoreStore()
        await store.register_benchmark(
            benchmark_id=BOARD, display_name="Snapshot", revision="rev", case_count=100
        )
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
                metadata={"benchmark_revision": "rev"},
            )
        )
        await Score.filter(id=outcome.score.id).update(benchmark_revision="rev")

        async with store.read_snapshot() as snapshot:
            before = await store.frontier_history_inputs(
                BOARD, registered_revision="rev", registered_case_count=100, connection=snapshot
            )
            # A writer OUTSIDE the transaction commits a change mid-request.
            other = await asyncpg.connect(DATABASE_URL.replace("postgres://", "postgresql://", 1))
            try:
                await other.execute(
                    "UPDATE scores SET score = 0.99 WHERE id = $1", outcome.score.id
                )
            finally:
                await other.close()
            after = await store.frontier_history_inputs(
                BOARD, registered_revision="rev", registered_case_count=100, connection=snapshot
            )

        # INVARIANT: both reads saw the board as it was when the snapshot began.
        assert [row.score for row in before] == [0.5]
        assert [row.score for row in after] == [0.5]

        committed = await store.frontier_history_inputs(
            BOARD, registered_revision="rev", registered_case_count=100
        )
        assert [row.score for row in committed] == [0.99]
    finally:
        await Score.filter(benchmark_id=BOARD).delete()
        await Benchmark.filter(id=BOARD).delete()
        await Tortoise.close_connections()
