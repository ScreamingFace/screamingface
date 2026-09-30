"""The board's own configuration comes from the same snapshot as its scores (OME-1145).

Review round 3 (Dmitry, 2026-09-29): both routes read `Benchmark.revision` and `case_count`
BEFORE entering `read_snapshot()`. A re-registration landing between that read and the snapshot
let a score filed under the new revision be served under the old one's filter: a pairing that
never coexisted in any database state.

INVARIANT: the revision and case count used to filter a response are re-read inside the snapshot
that reads the scores. The privacy decision stays outside it, fresh.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark
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


def _reregister_as_the_snapshot_opens(monkeypatch: pytest.MonkeyPatch, new_revision: str) -> None:
    """Re-register the board between the handler's first read and the snapshot."""
    real = ScoreStore.read_snapshot

    @asynccontextmanager
    async def _snapshot(self: ScoreStore) -> AsyncIterator[Any]:
        await Benchmark.filter(id=BOARD).update(revision=new_revision)
        async with real(self) as snapshot:
            yield snapshot

    monkeypatch.setattr(ScoreStore, "read_snapshot", _snapshot)


def _record_revisions(monkeypatch: pytest.MonkeyPatch, method: str) -> list[object]:
    seen: list[object] = []
    real = getattr(ScoreStore, method)

    async def _recording(self: ScoreStore, *args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("registered_revision"))
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(ScoreStore, method, _recording)
    return seen


async def test_the_frontier_filters_with_the_revision_read_inside_the_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ScoreStore().register_benchmark(benchmark_id=BOARD, display_name="Draco", revision="r1")
    _reregister_as_the_snapshot_opens(monkeypatch, "r2")
    history = _record_revisions(monkeypatch, "frontier_history_inputs")
    current = _record_revisions(monkeypatch, "leaderboard_pareto_inputs")

    assert (await client.get(f"/v1/leaderboard/{BOARD}/frontier")).status_code == 200

    assert history == ["r2"]
    assert current == ["r2"]


async def test_the_table_filters_with_the_revision_read_inside_the_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ScoreStore().register_benchmark(benchmark_id=BOARD, display_name="Draco", revision="r1")
    _reregister_as_the_snapshot_opens(monkeypatch, "r2")
    page = _record_revisions(monkeypatch, "leaderboard")
    marks = _record_revisions(monkeypatch, "leaderboard_pareto_inputs")

    assert (await client.get(f"/v1/leaderboard/{BOARD}")).status_code == 200

    assert page == ["r2"]
    assert marks == ["r2"]
