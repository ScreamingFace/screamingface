"""Every ranking and display path serves the reproduction cost, and the export does not (OME-1382).

FEATURE: `OME-1251` D5 / `OME-1143`. A cached run that spent $0.01 and whose cache avoided $4.99
costs $5.00 to reproduce. Ranked on its spend it dominates an honest $2.00 run it did not beat on
cost; ranked on what reproducing it costs, both are on the frontier.

INVARIANT (`OME-1145` D-L): one number per row everywhere a cost is ranked or shown: the table,
the frontier marks, the chart input, the card, the trend and the spec history.

INVARIANT: the private export keeps the three STORED fields. Its bytes are the sha256 that
authorises a purge, so it never carries the derived sum.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.export_private_submissions import collect_submissions, format_jsonl_bytes
from scoreboard.main import create_app
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "draco-3pass"
REV = "rev-1"
T0 = datetime(2026, 9, 1, tzinfo=UTC)
CACHED = "cached"
HONEST = "honest"


@pytest_asyncio.fixture
async def client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def _score(
    spec_id: str,
    score: float,
    *,
    spend: str | None,
    status: str | None,
    saving: str | None,
    hours: int,
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
            run_cost_usd=None if spend is None else Decimal(spend),
            run_cost_status=status,  # type: ignore[arg-type]
            cache_saved_cost_usd=None if saving is None else Decimal(saving),
            metadata={"benchmark_revision": REV},
        )
    )
    await Score.filter(id=outcome.score.id).update(
        submitted_at=T0 + timedelta(hours=hours), benchmark_revision=REV
    )
    return str(outcome.score.id)


async def _board(*, cached_status: str = "complete") -> None:
    await ScoreStore().register_benchmark(
        benchmark_id=BOARD, display_name="Draco 3-pass", revision=REV, case_count=100
    )
    cached_spend = "0.010000" if cached_status == "complete" else None
    await _score(CACHED, 0.80, spend=cached_spend, status=cached_status, saving="4.990000", hours=0)
    await _score(HONEST, 0.70, spend="2.000000", status="complete", saving=None, hours=24)


async def _rows(client: httpx.AsyncClient) -> dict[str, dict[str, object]]:
    body = (await client.get(f"/v1/leaderboard/{BOARD}")).json()
    return {entry["spec_id"]: entry for entry in body["entries"]}


# --- The table, the marks and the chart input ----------------------------------------------------


async def test_the_table_shows_spend_plus_saving_for_a_cached_complete_row(
    client: httpx.AsyncClient,
) -> None:
    await _board()

    rows = await _rows(client)

    assert rows[CACHED]["run_cost_usd"] == "5.000000"
    assert rows[HONEST]["run_cost_usd"] == "2.000000"


async def test_the_frontier_ranks_on_the_reproduction_cost(client: httpx.AsyncClient) -> None:
    """On spend alone the cached row dominates the honest one; on what it costs, neither does."""
    await _board()

    rows = await _rows(client)

    assert rows[CACHED]["on_pareto_frontier"] is True
    assert rows[HONEST]["on_pareto_frontier"] is True


async def test_the_card_counts_the_same_frontier_as_the_marks(client: httpx.AsyncClient) -> None:
    await _board()

    frontier = (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).json()

    assert frontier["frontier_size"] == 2


async def test_the_trend_replays_the_same_cost_as_the_current_frontier(
    client: httpx.AsyncClient,
) -> None:
    """INVARIANT: the last trend point describes the same frontier the card does.

    The trend replays the whole history on its own read. If that read kept the bare spend, the
    honest row would be dominated in the replay while the card counts it, and the trend's last
    point would describe a board the page is not showing.
    """
    await _board()

    replay = await ScoreStore().frontier_history_inputs(
        BOARD, registered_revision=REV, registered_case_count=100
    )

    costs = {row.spec_id: row.run_cost_usd for row in replay}
    assert costs == {CACHED: Decimal("5.000000"), HONEST: Decimal("2.000000")}


# --- What is NOT summed --------------------------------------------------------------------------


async def test_a_partial_row_with_a_saving_still_shows_no_cost_and_stays_off_the_frontier(
    client: httpx.AsyncClient,
) -> None:
    """INVARIANT: a saving is never promoted to a cost (#1187 sends any cached run as partial)."""
    await _board(cached_status="partial")

    rows = await _rows(client)

    assert rows[CACHED]["run_cost_usd"] is None
    assert rows[CACHED]["on_pareto_frontier"] is False
    assert rows[HONEST]["on_pareto_frontier"] is True


async def test_a_row_with_no_saving_is_unchanged(client: httpx.AsyncClient) -> None:
    await ScoreStore().register_benchmark(
        benchmark_id=BOARD, display_name="Draco 3-pass", revision=REV, case_count=100
    )
    await _score(HONEST, 0.70, spend="2.000000", status="complete", saving=None, hours=0)

    assert (await _rows(client))[HONEST]["run_cost_usd"] == "2.000000"


# --- The other display paths ---------------------------------------------------------------------


async def test_the_spec_history_shows_the_same_cost_as_the_table(
    client: httpx.AsyncClient,
) -> None:
    await _board()

    body = (await client.get(f"/v1/leaderboard/{BOARD}/{CACHED}/history")).json()

    assert [s["run_cost_usd"] for s in body["submissions"]] == ["5.000000"]


async def test_a_participants_own_rows_show_the_same_cost(tortoise_db: None) -> None:
    await _board()

    owned = await ScoreStore().list_owned_entries(BOARD, "tester@example.test")

    assert {row.spec_id: row.run_cost_usd for row in owned} == {
        CACHED: Decimal("5.000000"),
        HONEST: Decimal("2.000000"),
    }


# --- The export ----------------------------------------------------------------------------------


async def test_the_export_keeps_the_stored_spend_status_and_saving(tortoise_db: None) -> None:
    """INVARIANT: the purge-authorising export carries what is STORED, never the derived sum."""
    await _board()

    lines = format_jsonl_bytes(await collect_submissions(BOARD)).decode().splitlines()
    exported = {row["spec_id"]: row for row in map(json.loads, lines)}

    assert Decimal(exported[CACHED]["run_cost_usd"]) == Decimal("0.010000")
    assert exported[CACHED]["run_cost_status"] == "complete"
    assert Decimal(exported[CACHED]["cache_saved_cost_usd"]) == Decimal("4.990000")


# --- D7: the archive-matched saving joins the sum ------------------------------------------------


async def test_the_table_and_frontier_include_an_archive_saving(
    client: httpx.AsyncClient,
) -> None:
    """The draco-3pass seed is all archive-matched; its rows rank on what they cost to reproduce."""
    await ScoreStore().register_benchmark(
        benchmark_id=BOARD, display_name="Draco 3-pass", revision=REV, case_count=100
    )
    outcome = await ScoreStore().submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id=CACHED,
            url4_expression=f"url4://{CACHED}",
            submitted_by="tester@example.test",
            score=0.80,
            total_questions=100,
            ran_with_providers=["openrouter"],
            run_cost_usd=Decimal("0.010000"),
            run_cost_status="complete",
            cache_saved_cost_usd=Decimal("1.000000"),
            cache_saved_cost_archive_usd=Decimal("3.990000"),
            metadata={"benchmark_revision": REV},
        )
    )
    await Score.filter(id=outcome.score.id).update(submitted_at=T0, benchmark_revision=REV)
    await _score(HONEST, 0.70, spend="2.000000", status="complete", saving=None, hours=24)

    rows = await _rows(client)

    assert rows[CACHED]["run_cost_usd"] == "5.000000"
    assert rows[HONEST]["on_pareto_frontier"] is True
