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

import asyncio
import contextlib
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
from scoreboard.scores.store import ScoreStore, SubmitOutcome

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


def _identical() -> ScoreSubmission:
    return ScoreSubmission(
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


async def _drain_and_clean(pending: asyncio.Task[object] | None) -> None:
    if pending is not None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(pending, timeout=10)
    await Score.filter(benchmark_id=BOARD).delete()
    await Benchmark.filter(id=BOARD).delete()
    await Tortoise.close_connections()


class _PausedDelete:
    """A confirmed delete that stops after taking its locks, until released."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.locks_held = asyncio.Event()
        self.release = asyncio.Event()
        self.task: asyncio.Task[object] | None = None
        real = module._delete_rows

        async def _pause_then_delete(connection: BaseDBAsyncClient, ids: list[uuid.UUID]) -> int:
            self.locks_held.set()
            await self.release.wait()
            return await real(connection, ids)

        self._monkeypatch = monkeypatch
        self._pause = _pause_then_delete

    async def start(self) -> None:
        reviewed = await module.delete_scores(BOARD, submitted_before=CUTOFF, expected=1)
        self._monkeypatch.setattr(module, "_delete_rows", self._pause)
        self.task = asyncio.create_task(
            module.delete_scores(
                BOARD,
                submitted_before=CUTOFF,
                expected=1,
                confirmed=True,
                expected_sha256=reviewed.sha256(),
            )
        )
        await asyncio.wait_for(self.locks_held.wait(), timeout=10)

    async def finish(self) -> None:
        # Always let the delete end, or cleanup waits on its row lock forever.
        self.release.set()
        if self.task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.task, timeout=10)


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_a_replay_racing_the_delete_is_not_acknowledged_and_then_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 3 (Dmitry, reproduced on PostgreSQL 17).

    An identical resubmission finds the stored row and, with nothing to fill, used to return it
    without any lock: `created=False` and its id, while the delete holding that row committed a
    moment later. The submitter was told the score was stored, and it was gone.

    INVARIANT: the replay waits for an in-flight delete of its row. If the row is gone when the
    delete commits, the submission is stored as new, so what the submitter is told is true.
    """
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    paused = _PausedDelete(monkeypatch)
    replaying: asyncio.Task[object] | None = None
    try:
        await Tortoise.generate_schemas(safe=True)
        old_id = await _seed()
        await paused.start()

        replaying = asyncio.create_task(ScoreStore().submit(_identical()))
        await asyncio.sleep(0.5)
        # The replay must be waiting on the delete, not already answered from a doomed row.
        assert not replaying.done()

        await paused.finish()
        outcome = await asyncio.wait_for(replaying, timeout=10)

        assert isinstance(outcome, SubmitOutcome)
        assert outcome.created is True
        assert outcome.score.id != old_id
        assert await Score.filter(id=outcome.score.id).exists()
        assert not await Score.filter(id=old_id).exists()
    finally:
        await paused.finish()
        await _drain_and_clean(replaying)
