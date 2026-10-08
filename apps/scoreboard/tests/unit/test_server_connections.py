"""Every scoreboard transaction names its connection (OME-1488).

#1213 (`OME-1452`) gave the web app a second Tortoise connection, `readiness`, reserved for
`/readyz`. With two connections Tortoise refuses an unnamed `in_transaction()`:

    tortoise.exceptions.ParamsError: You are running with multiple databases, so you should
    specify connection_name: ['default', 'readiness']

That took down every leaderboard and frontier read on dev (2026-10-05) and the submission path
with it. The unit suite never saw it: its `tortoise_db` fixture starts ONE connection.

INVARIANT: these tests start Tortoise exactly as the web app does (`build_server_tortoise_config`),
so the request paths run with both connections present.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from tortoise import Tortoise

from scoreboard.config import PoolSize
from scoreboard.db import READINESS_CONNECTION, build_server_tortoise_config
from scoreboard.delete_scores import delete_scores
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "draco-3pass"
REV = "rev-1"
SRC = Path(__file__).resolve().parents[2] / "src" / "scoreboard"


@pytest_asyncio.fixture
async def server_db() -> AsyncIterator[None]:
    config = build_server_tortoise_config("sqlite://:memory:", PoolSize(minsize=1, maxsize=5))
    assert set(config["connections"]) == {"default", READINESS_CONNECTION}
    await Tortoise.init(config=config)
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


def _submission(spec_id: str = "a") -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=BOARD,
        spec_id=spec_id,
        url4_expression=f"url4://{spec_id}",
        submitted_by="tester@example.test",
        score=0.5,
        total_questions=100,
        ran_with_providers=["openrouter"],
        run_cost_usd=Decimal("1.000000"),
        run_cost_status="complete",
        metadata={"benchmark_revision": REV},
    )


async def _board() -> ScoreStore:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id=BOARD, display_name="Draco 3-pass", revision=REV, case_count=100
    )
    return store


async def test_a_submission_works_with_the_readiness_connection_present(server_db: None) -> None:
    store = await _board()

    outcome = await store.submit(_submission())

    assert outcome.created is True


async def test_a_replay_works_with_the_readiness_connection_present(server_db: None) -> None:
    store = await _board()
    await store.submit(_submission())

    replay = await store.submit(_submission())

    assert replay.created is False


async def test_the_board_and_frontier_reads_work_with_the_readiness_connection_present(
    server_db: None,
) -> None:
    """The dev outage: `read_snapshot` is what both the table and the frontier card open."""
    store = await _board()
    await store.submit(_submission())

    async with store.read_snapshot() as snapshot:
        rows = await store.leaderboard(
            benchmark_id=BOARD,
            top_n=10,
            registered_revision=REV,
            registered_case_count=100,
            connection=snapshot,
        )

    assert [row.spec_id for row in rows] == ["a"]


async def test_a_delete_works_with_the_readiness_connection_present(server_db: None) -> None:
    store = await _board()
    await store.submit(_submission())

    cutoff = datetime.now(UTC) + timedelta(hours=1)
    deletion = await delete_scores(BOARD, submitted_before=cutoff, expected=1)

    assert len(deletion.rows) == 1


# --- The structural guard ------------------------------------------------------------------------


def _unnamed_transactions() -> list[str]:
    """Every `in_transaction(...)` call in the package that passes no `connection_name`.

    Parsed with `ast`, not searched as text: a call is a call however it is formatted.
    """
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "in_transaction":
                continue
            named = bool(node.args) or any(k.arg == "connection_name" for k in node.keywords)
            if not named:
                found.append(f"{path.relative_to(SRC)}:{node.lineno}")
    return found


def test_no_transaction_in_the_scoreboard_is_opened_without_naming_its_connection() -> None:
    """INVARIANT (OME-1488): a second configured connection can never make the choice ambiguous."""
    assert _unnamed_transactions() == []
