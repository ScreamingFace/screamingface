"""Each ranked leaderboard row says whether it is open (OME-1282, stacked on OME-1145).

FEATURE: the board shows WHICH entries win the open frontier, not only what share of it is open.
An "open frontier win" is a row carrying both `on_pareto_frontier` and `openness: "open"` (B1).

INVARIANT: the row's verdict is the card's verdict. Both come from `classify_entry`, so the table
can never call a row open that the "N% open" card counted closed.
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
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "draco-3pass"
REV = "rev-1"
T0 = datetime(2026, 9, 1, tzinfo=UTC)

OPEN = ["openrouter/deepseek/deepseek-v4-pro", "openrouter/moonshotai/kimi-k2.6"]
CLOSED = ["openrouter/deepseek/deepseek-v4-pro", "openrouter/openai/gpt-5.5"]


@pytest_asyncio.fixture
async def client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def _board() -> None:
    await ScoreStore().register_benchmark(
        benchmark_id=BOARD, display_name="Draco 3-pass", revision=REV, case_count=100
    )


async def _score(
    spec_id: str, score: float, cost: str, models: list[str] | None, hours: int
) -> str:
    outcome = await ScoreStore().submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id=spec_id,
            url4_expression=f"url4://{spec_id}",
            submitted_by="tester@example.test",
            score=score,
            total_questions=100,
            ran_with_providers=["openrouter"],
            models=models,
            run_cost_usd=Decimal(cost),
            run_cost_status="complete",
            metadata={"benchmark_revision": REV},
        )
    )
    await Score.filter(id=outcome.score.id).update(
        submitted_at=T0 + timedelta(hours=hours), benchmark_revision=REV
    )
    return str(outcome.score.id)


async def _rows(client: httpx.AsyncClient) -> dict[str, dict[str, object]]:
    body = (await client.get(f"/v1/leaderboard/{BOARD}")).json()
    return {entry["spec_id"]: entry for entry in body["entries"]}


async def test_every_ranked_row_carries_its_verdict(client: httpx.AsyncClient) -> None:
    await _board()
    await _score("open-run", 0.5, "1.00", OPEN, 0)
    await _score("closed-run", 0.9, "5.00", CLOSED, 1)
    await _score("legacy-run", 0.4, "0.50", None, 2)

    rows = await _rows(client)

    assert rows["open-run"]["openness"] == "open"
    assert rows["closed-run"]["openness"] == "closed"
    assert rows["legacy-run"]["openness"] == "unidentified"


async def test_an_unrecognised_model_closes_the_row(client: httpx.AsyncClient) -> None:
    await _board()
    await _score("mystery", 0.5, "1.00", ["openrouter/nobody/mystery-1"], 0)

    assert (await _rows(client))["mystery"]["openness"] == "closed"


async def test_the_override_decides_the_row(client: httpx.AsyncClient) -> None:
    await _board()
    score_id = await _score("corrected", 0.5, "1.00", CLOSED, 0)
    await Score.filter(id=score_id).update(openness_override="open")

    assert (await _rows(client))["corrected"]["openness"] == "open"


async def test_the_rows_agree_with_the_card(client: httpx.AsyncClient) -> None:
    """INVARIANT: the card's open count equals the frontier rows the table calls open."""
    await _board()
    await _score("cheap-open", 0.5, "1.00", OPEN, 0)
    await _score("dear-closed", 0.9, "5.00", CLOSED, 1)
    await _score("dominated-open", 0.4, "6.00", OPEN, 2)

    rows = await _rows(client)
    card = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    frontier = [r for r in rows.values() if r["on_pareto_frontier"]]
    assert card["open_count"] == sum(1 for r in frontier if r["openness"] == "open")
    assert card["closed_count"] == sum(1 for r in frontier if r["openness"] == "closed")


async def test_models_are_read_only_for_the_page(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT (OME-1179 constraint 4): the verdict read is bounded by the page, not the board."""
    await _board()
    for i in range(5):
        await _score(f"spec-{i}", 0.5 + i / 100, f"{i + 1}.00", OPEN, i)
    seen: list[int] = []
    real = ScoreStore.frontier_member_models

    async def _counting(self: ScoreStore, score_ids: list[str]) -> object:
        seen.append(len(score_ids))
        return await real(self, score_ids)

    monkeypatch.setattr(ScoreStore, "frontier_member_models", _counting)

    body = (await client.get(f"/v1/leaderboard/{BOARD}?top=2")).json()

    assert len(body["entries"]) == 2
    assert seen == [2]


async def test_a_flip_during_the_verdict_read_withholds_the_board(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT (OME-894): the privacy re-check comes after this read too."""
    await _board()
    await _score("a", 0.5, "1.00", OPEN, 0)
    real = ScoreStore.frontier_member_models

    async def _flips(self: ScoreStore, score_ids: list[str]) -> object:
        await Benchmark.filter(id=BOARD).update(visibility="private")
        return await real(self, score_ids)

    monkeypatch.setattr(ScoreStore, "frontier_member_models", _flips)

    body = (await client.get(f"/v1/leaderboard/{BOARD}")).json()

    assert body["entries"] == []
    assert body["scoped_to_caller"] is True
