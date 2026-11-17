"""Revision archives never turn client assertions into best-value claims (OME-1708)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.purge_private_benchmark import export_sha256, purge_private_benchmark
from scoreboard.scores.models import Benchmark, BenchmarkRevision
from scoreboard.scores.store import ScoreStore
from tests.unit.test_leaderboard_revisions_route import _board_with_a_bump, _run

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def async_client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.parametrize("suffix", ["", "/frontier"])
async def test_unregistered_board_rejects_even_existing_revision_rows(
    async_client: httpx.AsyncClient, suffix: str
) -> None:
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro")
    await BenchmarkRevision.create(
        benchmark_id="mmlu_pro",
        revision="invented",
        first_seen_at=datetime.now(UTC),
        case_count=1,
        case_count_inferred=True,
    )
    await store.submit(_run("one-case", 1.0, revision="invented", total=1))
    response = await async_client.get(
        f"/v1/leaderboard/mmlu_pro{suffix}", params={"revision": "invented"}
    )
    assert response.status_code == 404
    revisions = await async_client.get("/v1/leaderboard/mmlu_pro/revisions")
    assert revisions.json()["revisions"] == []


@pytest.mark.parametrize("inferred,count", [(True, 1), (False, None)])
async def test_uncertain_historical_scope_is_browsable_without_frontier_claims(
    async_client: httpx.AsyncClient, inferred: bool, count: int | None
) -> None:
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="current", case_count=100)
    await BenchmarkRevision.create(
        benchmark_id="mmlu_pro",
        revision="unverified",
        first_seen_at=datetime.now(UTC),
        case_count=count,
        case_count_inferred=inferred,
    )
    await store.submit(_run("one-case", 1.0, revision="unverified", total=1))
    board = await async_client.get("/v1/leaderboard/mmlu_pro", params={"revision": "unverified"})
    assert board.status_code == 200
    assert len(board.json()["entries"]) == 1
    assert board.json()["entries"][0]["on_pareto_frontier"] is False
    frontier = await async_client.get(
        "/v1/leaderboard/mmlu_pro/frontier", params={"revision": "unverified"}
    )
    assert frontier.status_code == 200
    assert frontier.json()["frontier_size"] == 0


@pytest.mark.parametrize("rollback", [False, True])
async def test_latest_is_first_even_when_its_first_seen_date_is_older(
    async_client: httpx.AsyncClient, rollback: bool
) -> None:
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="a", case_count=100)
    await BenchmarkRevision.filter(benchmark_id="mmlu_pro", revision="a").update(
        first_seen_at=datetime(2026, 10, 1, tzinfo=UTC), first_seen_inferred=not rollback
    )
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="b", case_count=100)
    await BenchmarkRevision.filter(benchmark_id="mmlu_pro", revision="b").update(
        first_seen_at=datetime(2026, 11, 1, tzinfo=UTC)
    )
    await store.submit(_run("full", 0.9, revision="b"))
    if rollback:
        await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="a", case_count=100)
    else:
        # Migration shape: empty current uses benchmark creation, earlier than old results.
        await Benchmark.filter(id="mmlu_pro").update(revision="a")
    result = await async_client.get("/v1/leaderboard/mmlu_pro/revisions")
    latest, previous = result.json()["revisions"]
    assert (latest["revision"], latest["current"], latest["until"]) == ("a", True, None)
    assert latest["result_count"] == 0
    assert (previous["revision"], previous["current"], previous["result_count"]) == ("b", False, 1)
    assert previous["until"] is None  # No fabricated end date before B started.


async def test_current_count_tracks_registered_scope_when_seed_clears_it(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="current", case_count=100)
    await store.submit(_run("full", 0.9, revision="current"))
    await store.submit(_run("partial", 1.0, revision="current", total=1))
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="current", case_count=None)
    board = await async_client.get("/v1/leaderboard/mmlu_pro")
    revisions = await async_client.get("/v1/leaderboard/mmlu_pro/revisions")
    [current] = revisions.json()["revisions"]
    assert current["case_count"] is None
    assert current["case_count_inferred"] is False
    assert current["result_count"] == len(board.json()["entries"]) == 2


async def test_revision_counts_do_not_materialize_unbounded_display_rows(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ScoreStore()
    await _board_with_a_bump(store)
    await store.submit(_run("trio", 0.85, revision="rev-old"))
    await store.submit(_run("trio", 1.0, revision="rev-old", total=1))
    read = AsyncMock(side_effect=AssertionError("must count in SQL, not load display rows"))
    monkeypatch.setattr(ScoreStore, "leaderboard", read)
    revisions = await async_client.get("/v1/leaderboard/mmlu_pro/revisions")
    assert [(r["revision"], r["result_count"]) for r in revisions.json()["revisions"]] == [
        ("rev-new", 1),
        ("rev-old", 2),
    ]
    read.assert_not_awaited()


async def test_purge_removes_revision_history_in_the_same_transaction(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(
        "private-test", "Private", revision="old", case_count=10, visibility="private"
    )
    await store.register_benchmark("private-test", "Private", revision="new", case_count=20)
    await store.register_benchmark("keep", "Keep", revision="keep", case_count=1)
    assert await BenchmarkRevision.filter(benchmark_id="private-test").count() == 2
    result = await purge_private_benchmark("private-test", export_sha256([]), confirmed=True)
    assert result.startswith("purged 'private-test'")
    assert not await Benchmark.exists(id="private-test")
    assert not await BenchmarkRevision.filter(benchmark_id="private-test").exists()
    assert await BenchmarkRevision.filter(benchmark_id="keep").count() == 1
