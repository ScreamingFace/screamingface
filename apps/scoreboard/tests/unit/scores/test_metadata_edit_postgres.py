"""Two editors holding the same `If-Match` cannot both win, on PostgreSQL (MD-6, OME-1307 E14a).

WHY this needs PostgreSQL: SQLite serialises every transaction and `select_for_update` is a no-op
there, so the SQLite MD-6 test cannot show that the second editor WAITS on the row lock. Here the
first editor is held inside its transaction, holding the lock, and the test proves the second one
is blocked until the first commits. This file lives in the PostgreSQL CI lane.

WHY a self-contained connection: the same reason `test_delete_scores_postgres.py` gives (OME-430).
Runs only when SCOREBOARD_TEST_DATABASE_URL is set; skips otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from decimal import Decimal

import pytest
from tortoise import BaseDBAsyncClient, Tortoise

from scoreboard.db import build_tortoise_config
from scoreboard.scores import metadata_store as module
from scoreboard.scores.metadata_store import (
    MetadataEditOutcome,
    MetadataRevisionConflict,
    ScoreMetadataStore,
)
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
BOARD = "metadata-lock-pg"
OWNER = "ana@x.org"


async def _seed() -> uuid.UUID:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id=BOARD, display_name="Metadata lock")
    outcome = await store.submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id="a",
            url4_expression="url4://a",
            submitted_by=OWNER,
            score=0.5,
            total_questions=100,
            ran_with_providers=["openrouter"],
            run_cost_usd=Decimal("1.00"),
            run_cost_status="complete",
        )
    )
    return outcome.score.id


async def _edit(score_id: uuid.UUID, paper_url: str) -> MetadataEditOutcome:
    return await ScoreMetadataStore().update_metadata(
        score_id,
        changes={"paper_url": paper_url},
        expected_revision=1,
        editor=OWNER,
    )


class _PausedFirstEditor:
    """Wraps `_lock_row`: the FIRST editor stops right after it takes the row lock."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.locked = asyncio.Event()
        self.release = asyncio.Event()
        self._calls = 0
        real = module._lock_row

        async def _lock_then_pause(
            connection: BaseDBAsyncClient, score_id: uuid.UUID
        ) -> Score | None:
            row = await real(connection, score_id)
            self._calls += 1
            if self._calls == 1:
                self.locked.set()
                await self.release.wait()
            return row

        monkeypatch.setattr(module, "_lock_row", _lock_then_pause)


async def _assert_first_won(
    score_id: uuid.UUID, winner: MetadataEditOutcome, conflict: MetadataRevisionConflict
) -> None:
    assert winner.changed is True
    assert winner.score.metadata_revision == 2
    assert conflict.current.metadata_revision == 2
    assert conflict.current.paper_url == "https://x.org/one"
    stored = await Score.get(id=score_id)
    assert (stored.metadata_revision, stored.paper_url) == (2, "https://x.org/one")
    assert await ScoreMetadataEvent.filter(score_id=score_id).count() == 1


async def _drain_and_clean(*pending: asyncio.Task[object]) -> None:
    for task in pending:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=10)
    await Score.filter(benchmark_id=BOARD).delete()
    await Benchmark.filter(id=BOARD).delete()
    await Tortoise.close_connections()


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_md6_concurrent_patches_one_wins_one_412_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT (MD-D2): of two editors holding `If-Match: "1"`, one wins and one gets a 412.

    The second editor must be BLOCKED on the row lock while the first holds it, and only then see
    revision 2 and lose. Without the lock (or the conditional UPDATE) both would read revision 1.
    """
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    paused = _PausedFirstEditor(monkeypatch)
    tasks: list[asyncio.Task[MetadataEditOutcome]] = []
    try:
        await Tortoise.generate_schemas(safe=True)
        score_id = await _seed()

        first = asyncio.create_task(_edit(score_id, "https://x.org/one"))
        tasks.append(first)
        await asyncio.wait_for(paused.locked.wait(), timeout=10)
        second = asyncio.create_task(_edit(score_id, "https://x.org/two"))
        tasks.append(second)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), 0.5)
        # The second editor is waiting on the row lock, not already answered from a stale read.
        assert not second.done()

        paused.release.set()
        winner = await asyncio.wait_for(first, timeout=10)
        with pytest.raises(MetadataRevisionConflict) as conflict:
            await asyncio.wait_for(second, timeout=10)

        await _assert_first_won(score_id, winner, conflict.value)
    finally:
        # Always let the first editor end, or cleanup waits on its row lock forever.
        paused.release.set()
        await _drain_and_clean(*tasks)
