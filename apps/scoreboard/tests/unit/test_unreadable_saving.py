"""An unreadable stored saving makes the reproduction cost unknown, never the bare spend (OME-1487).

FEATURE: `OME-1251` D5 / D7, follow-up to `OME-1382`. The raw leaderboard and Pareto reads decode
each money column themselves and degrade an undecodable value instead of failing the board. For the
spend that degraded value means "unknown". For a cache saving it used to mean "no saving", so a
`complete` row whose saving could not be read was ranked at its bare spend: far too cheap, and able
to take a frontier slot it has not earned.

INVARIANT: a saving that is present but unreadable serves no cost, so the row leaves the frontier
like any other unpriced row. A saving that is genuinely absent (NULL) still adds nothing.

WHY raw SQL: only SQLite can hold such a value (the column is VARCHAR(40) with no database-level
guard), and only for a row written outside the API, which validates every amount.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from tortoise import Tortoise

from scoreboard.config import Settings
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
SAVING_COLUMNS = ["cache_saved_cost_usd", "cache_saved_cost_archive_usd"]


@pytest_asyncio.fixture
async def client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def _score(spec_id: str, score: float, *, spend: str, hours: int) -> None:
    outcome = await ScoreStore().submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id=spec_id,
            url4_expression=f"url4://{spec_id}",
            submitted_by="tester@example.test",
            score=score,
            total_questions=100,
            ran_with_providers=["openrouter"],
            run_cost_usd=Decimal(spend),
            run_cost_status="complete",
            metadata={"benchmark_revision": REV},
        )
    )
    await Score.filter(id=outcome.score.id).update(
        submitted_at=T0 + timedelta(hours=hours), benchmark_revision=REV
    )


async def _board(*, unreadable_column: str | None) -> None:
    """A cheap cached row that beats an honest $2.00 row on score, both `complete`.

    On its bare $0.01 spend the cached row dominates the honest one. With ``unreadable_column`` set,
    the cached row's saving in that column holds text no decimal can be read from.
    """
    await ScoreStore().register_benchmark(
        benchmark_id=BOARD, display_name="Draco 3-pass", revision=REV, case_count=100
    )
    await _score(CACHED, 0.80, spend="0.010000", hours=0)
    await _score(HONEST, 0.70, spend="2.000000", hours=24)
    if unreadable_column is not None:
        # WHY the column name is interpolated: it is one of the two literals in SAVING_COLUMNS,
        # never input. The value itself is a bound parameter.
        await Tortoise.get_connection("default").execute_query(
            f"UPDATE scores SET {unreadable_column} = ? WHERE spec_id = ?",
            ["not-a-number", CACHED],
        )


async def _rows(client: httpx.AsyncClient) -> dict[str, dict[str, object]]:
    body = (await client.get(f"/v1/leaderboard/{BOARD}")).json()
    return {entry["spec_id"]: entry for entry in body["entries"]}


async def _pareto_costs() -> dict[str, Decimal | None]:
    entries = await ScoreStore().leaderboard_pareto_inputs(
        BOARD, registered_revision=REV, registered_case_count=100
    )
    return {entry.spec_id: entry.run_cost_usd for entry in entries}


# --- An unreadable saving ------------------------------------------------------------------------


@pytest.mark.parametrize("column", SAVING_COLUMNS)
async def test_the_table_serves_no_cost_for_a_row_whose_saving_is_unreadable(
    client: httpx.AsyncClient, column: str
) -> None:
    await _board(unreadable_column=column)

    rows = await _rows(client)

    assert rows[CACHED]["run_cost_usd"] is None
    assert rows[CACHED]["on_pareto_frontier"] is False
    # The row it would have dominated on its bare spend keeps its place.
    assert rows[HONEST]["run_cost_usd"] == "2.000000"
    assert rows[HONEST]["on_pareto_frontier"] is True


@pytest.mark.parametrize("column", SAVING_COLUMNS)
async def test_the_pareto_input_carries_no_cost_for_a_row_whose_saving_is_unreadable(
    tortoise_db: None, column: str
) -> None:
    await _board(unreadable_column=column)

    assert await _pareto_costs() == {CACHED: None, HONEST: Decimal("2.000000")}


# --- An absent saving is unchanged ---------------------------------------------------------------


async def test_the_table_serves_the_bare_spend_when_no_saving_is_stored(
    client: httpx.AsyncClient,
) -> None:
    """INVARIANT (D5): absent is not unreadable. A NULL saving adds nothing and costs nothing."""
    await _board(unreadable_column=None)

    rows = await _rows(client)

    assert rows[CACHED]["run_cost_usd"] == "0.010000"
    assert rows[CACHED]["on_pareto_frontier"] is True
    assert rows[HONEST]["on_pareto_frontier"] is False


async def test_the_pareto_input_carries_the_bare_spend_when_no_saving_is_stored(
    tortoise_db: None,
) -> None:
    await _board(unreadable_column=None)

    assert await _pareto_costs() == {CACHED: Decimal("0.010000"), HONEST: Decimal("2.000000")}


# --- The frontier card and its trend replay ------------------------------------------------------
#
# FEATURE: OME-1487, owner decision 2026-10-06: the card route reads the replay through its own
# query, which used to raise on an undecodable money column and 500 the card for the whole board.
# INVARIANT: the replay serves the same cost per row as the table: an unreadable spend is unknown,
# and an unreadable saving makes the reproduction cost unknown.

MONEY_COLUMNS = ["run_cost_usd", *SAVING_COLUMNS]


async def _replay_costs() -> dict[str, Decimal | None]:
    replay = await ScoreStore().frontier_history_inputs(
        BOARD, registered_revision=REV, registered_case_count=100
    )
    return {row.spec_id: row.run_cost_usd for row in replay}


@pytest.mark.parametrize("column", MONEY_COLUMNS)
async def test_the_card_counts_only_the_priced_row(client: httpx.AsyncClient, column: str) -> None:
    await _board(unreadable_column=column)

    response = await client.get(f"/v1/leaderboard/{BOARD}/frontier")

    assert response.status_code == 200
    assert response.json()["frontier_size"] == 1


@pytest.mark.parametrize("column", MONEY_COLUMNS)
async def test_the_replay_carries_no_cost_for_a_row_with_an_unreadable_money_column(
    tortoise_db: None, column: str
) -> None:
    await _board(unreadable_column=column)

    assert await _replay_costs() == {CACHED: None, HONEST: Decimal("2.000000")}


async def test_the_card_counts_the_cheap_row_when_no_saving_is_stored(
    client: httpx.AsyncClient,
) -> None:
    """Absent is not unreadable: the cheap row dominates, exactly as before this change."""
    await _board(unreadable_column=None)

    response = await client.get(f"/v1/leaderboard/{BOARD}/frontier")

    assert response.status_code == 200
    assert response.json()["frontier_size"] == 1
    assert await _replay_costs() == {CACHED: Decimal("0.010000"), HONEST: Decimal("2.000000")}


# --- A non-finite stored amount (review round 1, PR #1259) ---------------------------------------
#
# WHY: "NaN" decodes cleanly to Decimal("NaN"), so it never reached the unreadable path. Ranking
# then compared it and raised, which 500'd the table and the card for the whole board.
# INVARIANT: a non-finite stored amount is treated exactly like one that cannot be decoded.

NON_FINITE = "NaN"


async def _board_with_non_finite(column: str) -> None:
    await _board(unreadable_column=None)
    # WHY the column name is interpolated: it is one of the literals in MONEY_COLUMNS, never
    # input. The value itself is a bound parameter.
    await Tortoise.get_connection("default").execute_query(
        f"UPDATE scores SET {column} = ? WHERE spec_id = ?", [NON_FINITE, CACHED]
    )


@pytest.mark.parametrize("column", MONEY_COLUMNS)
async def test_the_table_serves_no_cost_for_a_non_finite_amount(
    client: httpx.AsyncClient, column: str
) -> None:
    await _board_with_non_finite(column)

    response = await client.get(f"/v1/leaderboard/{BOARD}")

    assert response.status_code == 200
    rows = {entry["spec_id"]: entry for entry in response.json()["entries"]}
    assert rows[CACHED]["run_cost_usd"] is None
    assert rows[CACHED]["on_pareto_frontier"] is False
    assert rows[HONEST]["run_cost_usd"] == "2.000000"
    assert rows[HONEST]["on_pareto_frontier"] is True


@pytest.mark.parametrize("column", MONEY_COLUMNS)
async def test_the_pareto_input_carries_no_cost_for_a_non_finite_amount(
    tortoise_db: None, column: str
) -> None:
    await _board_with_non_finite(column)

    assert await _pareto_costs() == {CACHED: None, HONEST: Decimal("2.000000")}


@pytest.mark.parametrize("column", MONEY_COLUMNS)
async def test_the_card_and_replay_ignore_a_non_finite_amount(
    client: httpx.AsyncClient, column: str
) -> None:
    await _board_with_non_finite(column)

    response = await client.get(f"/v1/leaderboard/{BOARD}/frontier")

    assert response.status_code == 200
    assert response.json()["frontier_size"] == 1
    assert await _replay_costs() == {CACHED: None, HONEST: Decimal("2.000000")}
