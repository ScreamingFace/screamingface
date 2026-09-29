"""Every participant read of a route shares ONE snapshot (review round 1, OME-1145).

The frontier route read its inputs, its history and its models in three independent statements,
so a submission landing between them could make the summary describe one board and the trend
another. The table route had the same split between its page and its frontier marks.

These tests pin the wiring on SQLite: each read receives the connection `read_snapshot()` yielded.
That REPEATABLE READ really holds one snapshot on PostgreSQL is proven by
`scores/test_read_snapshot_postgres.py`, in the PostgreSQL CI lane.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "draco-3pass"


@pytest_asyncio.fixture
async def client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def _seed() -> None:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id=BOARD, display_name="Draco", revision="rev", case_count=100
    )
    await store.submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id="a",
            url4_expression="url4://a",
            submitted_by="tester@example.test",
            score=0.5,
            total_questions=100,
            ran_with_providers=["openrouter"],
            models=["openrouter/deepseek/deepseek-v4-pro"],
            run_cost_usd=Decimal("1.00"),
            run_cost_status="complete",
            metadata={"benchmark_revision": "rev"},
        )
    )


def _record(monkeypatch: pytest.MonkeyPatch, methods: list[str]) -> dict[str, object]:
    seen: dict[str, object] = {}
    for name in methods:
        real = getattr(ScoreStore, name)

        def _wrap(real=real, name=name):  # type: ignore[no-untyped-def]
            async def _recording(self, *args, connection=None, **kwargs):  # type: ignore[no-untyped-def]
                seen[name] = connection
                return await real(self, *args, connection=connection, **kwargs)

            return _recording

        monkeypatch.setattr(ScoreStore, name, _wrap())
    return seen


async def test_the_frontier_route_reads_everything_from_one_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed()
    methods = ["leaderboard_pareto_inputs", "frontier_history_inputs", "frontier_member_models"]
    seen = _record(monkeypatch, methods)

    assert (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).status_code == 200

    assert set(seen) == set(methods)
    connections = set(map(id, seen.values()))
    assert None not in seen.values()
    assert len(connections) == 1


async def test_the_table_route_marks_its_page_from_the_same_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed()
    methods = ["leaderboard", "leaderboard_pareto_inputs"]
    seen = _record(monkeypatch, methods)

    assert (await client.get(f"/v1/leaderboard/{BOARD}")).status_code == 200

    assert set(seen) == set(methods)
    assert None not in seen.values()
    assert len(set(map(id, seen.values()))) == 1
