"""Enrichment is dated when it happened, not when the row was first submitted (OME-1145).

Review round 3 (Dmitry, 2026-09-29): a same-owner resubmission can fill a stored row's missing
cost or models (fill-only, `_replay_updates`). The daily trend replayed each row's CURRENT values
at its original `submitted_at`, so a row enriched on Sep 5 showed its Sep 5 cost and models on
Sep 1's point: a day-end state that never existed.

INVARIANT: a row enters the trend at its effective time, the later of `submitted_at` and
`enriched_at`. `enriched_at` is stamped only when a replay fills a field the frontier reads.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.frontier import HistoryRow, replay_frontier
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

BOARD = "draco-3pass"
REV = "rev"
T0 = datetime(2026, 9, 1, tzinfo=UTC)
OPEN = ["openrouter/deepseek/deepseek-v4-pro"]


# --- The replay uses the effective time --------------------------------------------------------


def test_an_enriched_row_enters_the_replay_on_its_enrichment_day() -> None:
    rows = [
        HistoryRow("a", "a", 0.5, Decimal("1"), T0, enriched_at=T0 + timedelta(days=4)),
        HistoryRow("b", "b", 0.9, Decimal("5"), T0 + timedelta(days=1)),
    ]

    replay = replay_frontier(rows)

    assert [(at, frontier) for at, frontier in replay.steps] == [
        (T0 + timedelta(days=1), frozenset({"b"})),
        (T0 + timedelta(days=4), frozenset({"a", "b"})),
    ]


def test_an_unenriched_row_keeps_its_submission_day() -> None:
    row = HistoryRow("a", "a", 0.5, Decimal("1"), T0)

    assert replay_frontier([row]).steps[0][0] == T0


def test_a_late_enrichment_does_not_win_a_tie_the_table_gives_to_the_newer_submission() -> None:
    """INVARIANT: best-per-spec breaks a score tie on `submitted_at`, as the ranked query does.

    Rows now arrive in `effective_at` order. Without the explicit tie-break, the old row enriched
    on day 4 would displace the day-2 submission of the same spec and score.
    """
    old = HistoryRow("old", "s", 0.5, Decimal("1"), T0, enriched_at=T0 + timedelta(days=4))
    new = HistoryRow("new", "s", 0.5, Decimal("1"), T0 + timedelta(days=2))

    replay = replay_frontier([old, new])

    assert replay.steps[-1][1] == frozenset({"new"})


# --- The store stamps it -----------------------------------------------------------------------


def _submission(*, models: list[str] | None, cost: str | None, authors: list[str] | None = None):
    return ScoreSubmission(
        benchmark_id=BOARD,
        spec_id="a",
        url4_expression="url4://a",
        submitted_by="tester@example.test",
        score=0.5,
        total_questions=100,
        ran_with_providers=["openrouter"],
        models=models,
        authors=authors,
        run_cost_usd=None if cost is None else Decimal(cost),
        run_cost_status="complete" if cost is not None else None,
        metadata={"benchmark_revision": REV},
    )


async def _seed_bare() -> str:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id=BOARD, display_name="Draco", revision=REV, case_count=100
    )
    outcome = await store.submit(_submission(models=None, cost=None))
    await Score.filter(id=outcome.score.id).update(submitted_at=T0, benchmark_revision=REV)
    return str(outcome.score.id)


@pytest.mark.asyncio
async def test_filling_cost_or_models_stamps_enriched_at(tortoise_db: None) -> None:
    score_id = await _seed_bare()

    outcome = await ScoreStore().submit(_submission(models=OPEN, cost="1.00"))

    assert outcome.created is False
    row = await Score.get(id=score_id)
    assert row.enriched_at is not None
    assert row.enriched_at > T0


@pytest.mark.asyncio
async def test_filling_only_authors_does_not_stamp_enriched_at(tortoise_db: None) -> None:
    """Authors and metadata do not change what the frontier reads, so they are not an event."""
    score_id = await _seed_bare()

    await ScoreStore().submit(_submission(models=None, cost=None, authors=["someone@example.test"]))

    assert (await Score.get(id=score_id)).enriched_at is None


@pytest.mark.asyncio
async def test_the_history_read_carries_enriched_at(tortoise_db: None) -> None:
    await _seed_bare()
    await ScoreStore().submit(_submission(models=OPEN, cost="1.00"))

    rows = await ScoreStore().frontier_history_inputs(
        BOARD, registered_revision=REV, registered_case_count=100
    )

    assert rows[0].submitted_at == T0
    assert rows[0].enriched_at is not None and rows[0].enriched_at > T0


# --- End to end: the reviewer's scenario -------------------------------------------------------


@pytest_asyncio.fixture
async def client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


@pytest.mark.asyncio
async def test_a_later_enrichment_is_not_backdated_into_the_trend(
    client: httpx.AsyncClient,
) -> None:
    """Dmitry's reproduction: unpriced and unidentified on Sep 1, enriched later by a replay."""
    await _seed_bare()
    await ScoreStore().submit(_submission(models=OPEN, cost="1.00"))

    trend = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()["trend"]

    assert trend, "the enriched row is on the frontier now, so the trend has a point"
    assert all(not point["at"].startswith("2026-09-01") for point in trend)
