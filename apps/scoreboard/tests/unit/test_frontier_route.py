"""`GET /v1/leaderboard/{id}/frontier` on the frontier basis, end to end (OME-1145).

INVARIANT: the card and the table's Pareto marks are ONE definition. Every test here builds a
board, reads the table's `on_pareto_frontier` marks, and checks the statistic counted exactly
those rows. The live defect this replaces counted 10 rows while the table ranked 7.
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
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import ScoreSubmission, Visibility
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "draco-3pass"
REV = "2634cec91fd0f19a"
OLD_REV = "b8c8afd8f9dddca0"
CASES = 100
T0 = datetime(2026, 9, 1, tzinfo=UTC)

OPEN = ["openrouter/deepseek/deepseek-v4-pro", "openrouter/moonshotai/kimi-k2.6"]
CLOSED = ["openrouter/anthropic/claude-opus-4.8", "openrouter/openai/gpt-5.5"]


@pytest_asyncio.fixture
async def client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def _board(*, revision: str | None = REV, visibility: Visibility | None = None) -> None:
    await ScoreStore().register_benchmark(
        benchmark_id=BOARD,
        display_name="Draco 3-pass",
        revision=revision,
        case_count=CASES,
        visibility=visibility,
    )


async def _score(
    spec_id: str,
    score: float,
    cost: str | None,
    models: list[str] | None,
    *,
    day: int = 0,
    revision: str = REV,
    total: int = CASES,
) -> str:
    outcome = await ScoreStore().submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id=spec_id,
            url4_expression=f"url4://{spec_id}",
            submitted_by="tester@example.test",
            score=score,
            total_questions=total,
            ran_with_providers=["openrouter"],
            models=models,
            run_cost_usd=None if cost is None else Decimal(cost),
            run_cost_status="complete" if cost is not None else "unavailable",
            metadata={"benchmark_revision": revision},
        )
    )
    await Score.filter(id=outcome.score.id).update(
        submitted_at=T0 + timedelta(days=day), benchmark_revision=revision
    )
    return str(outcome.score.id)


async def _marked(client: httpx.AsyncClient) -> set[str]:
    board = (await client.get(f"/v1/leaderboard/{BOARD}")).json()
    return {e["spec_id"] for e in board["entries"] if e["on_pareto_frontier"]}


async def test_the_statistic_counts_exactly_the_tables_frontier_rows(
    client: httpx.AsyncClient,
) -> None:
    await _board()
    await _score("cheap-open", 0.5, "1.00", OPEN, day=0)
    await _score("dear-closed", 0.9, "5.00", CLOSED, day=1)
    await _score("dominated-open", 0.4, "6.00", OPEN, day=2)

    body = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    assert await _marked(client) == {"cheap-open", "dear-closed"}
    assert body["frontier_available"] is True
    assert body["frontier_size"] == 2
    assert (body["open_count"], body["closed_count"]) == (1, 1)
    assert body["open_share"] == 0.5


async def test_a_superseded_revision_is_not_counted(client: httpx.AsyncClient) -> None:
    """The live 10-vs-7: rows at the old revision were in the statistic but not on the table."""
    await _board()
    await _score("current", 0.5, "1.00", CLOSED, day=0)
    await _score("stale-open", 0.99, "0.10", OPEN, day=1, revision=OLD_REV)

    body = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    assert body["frontier_size"] == 1
    assert (body["open_count"], body["closed_count"]) == (0, 1)


async def test_a_partial_coverage_run_is_not_counted(client: httpx.AsyncClient) -> None:
    """OME-1056: fewer cases makes a good score easier, so it is not comparable."""
    await _board()
    await _score("full", 0.5, "1.00", CLOSED, day=0)
    await _score("one-case-open", 1.0, "0.01", OPEN, day=1, total=1)

    body = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    assert body["frontier_size"] == 1
    assert body["open_count"] == 0


async def test_an_unpinned_board_reports_no_frontier(client: httpx.AsyncClient) -> None:
    """D12: the table makes no frontier claim without a registered revision; nor does the card."""
    await _board(revision=None)
    await _score("a", 0.5, "1.00", OPEN)

    body = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    assert await _marked(client) == set()
    assert body["frontier_available"] is False
    assert body["open_share"] is None
    assert body["trend"] == []


async def test_legacy_rows_and_unrecognised_models_are_reported(
    client: httpx.AsyncClient,
) -> None:
    await _board()
    await _score("legacy", 0.5, "1.00", None, day=0)
    await _score("mystery", 0.9, "5.00", ["openrouter/nobody/mystery-1"], day=1)

    body = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    assert body["unidentified_count"] == 1
    assert body["unrecognised_models"] == ["openrouter/nobody/mystery-1"]
    assert (body["open_count"], body["closed_count"]) == (0, 1)


async def test_the_response_carries_exactly_the_new_fields(client: httpx.AsyncClient) -> None:
    """A characterisation guard: every field on one basis (D-L). `current` is gone."""
    await _board()

    body = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    assert set(body) == {
        "benchmark_id",
        "frontier_available",
        "frontier_size",
        "open_count",
        "closed_count",
        "unidentified_count",
        "unrecognised_models",
        "open_share",
        "trend",
    }
    assert body["open_share"] is None


async def test_the_trend_is_the_open_share_over_time(client: httpx.AsyncClient) -> None:
    await _board()
    await _score("first-closed", 0.5, "1.00", CLOSED, day=0)
    await _score("then-open", 0.9, "2.00", OPEN, day=1)

    trend = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()["trend"]

    assert [(p["open_share"], p["open_count"], p["closed_count"]) for p in trend] == [
        (0.0, 0, 1),
        (0.5, 1, 1),
    ]


async def test_a_private_board_still_has_no_frontier(client: httpx.AsyncClient) -> None:
    await _board(visibility="private")

    response = await client.get(f"/v1/leaderboard/{BOARD}/frontier")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "read", ["leaderboard_pareto_inputs", "frontier_history_inputs", "frontier_member_models"]
)
async def test_a_flip_during_any_frontier_read_withholds_the_aggregate(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, read: str
) -> None:
    """INVARIANT (OME-894): the privacy re-check is the last await, after EVERY participant read.

    The board turns private while each read runs in turn. None may leak the aggregate: a private
    board's frontier is 404 to everyone, participants included.
    """
    await _board()
    await _score("a", 0.5, "1.00", OPEN)
    real = getattr(ScoreStore, read)

    async def _flips(self: ScoreStore, *args: object, **kwargs: object) -> object:
        await Benchmark.filter(id=BOARD).update(visibility="private")
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(ScoreStore, read, _flips)

    response = await client.get(f"/v1/leaderboard/{BOARD}/frontier")

    assert response.status_code == 404
