"""OME-1953: indexing describes displayed results and HTTP methods agree."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from pathlib import Path
from unittest.mock import AsyncMock
from xml.etree import ElementTree

import asyncpg
import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise
from tortoise.exceptions import DBConnectionError, OperationalError

from scoreboard import board_pages
from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Benchmark
from tests.unit.scores.test_baseline_comparison import BOARD, _board, _row
from tests.unit.test_board_pages import PUBLIC_ORIGIN, _head, _seed


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient]:
    settings = Settings(database_url=f"sqlite://{tmp_path / 'review.sqlite3'}", cors_origins=[])
    with TestClient(create_app(settings), follow_redirects=False) as test_client:
        assert test_client.portal is not None
        test_client.portal.call(Tortoise.generate_schemas)
        test_client.portal.call(_seed)
        yield test_client


@pytest.mark.parametrize(
    "path,status",
    [
        ("/benchmarks/draco-3pass/", 200),
        ("/benchmarks/draco-3pass", 301),
        ("/benchmarks/empty-board/", 200),
        ("/benchmarks/challenge/", 200),
        ("/benchmarks/missing/", 404),
        ("/benchmark.html?id=draco-3pass&utm_source=mail", 301),
        ("/benchmark.html", 200),
        ("/sitemap.xml", 200),
        ("/robots.txt", 200),
    ],
)
def test_head_agrees_with_get(client: TestClient, path: str, status: int) -> None:
    get, head = client.get(path), client.head(path)

    assert head.status_code == get.status_code == status
    for header in ("location", "content-type", "content-length", "cache-control"):
        assert head.headers.get(header) == get.headers.get(header)
    assert head.content == b""


@pytest.mark.parametrize("method", ["get", "head"])
def test_slash_redirect_keeps_exact_query(client: TestClient, method: str) -> None:
    query = "utm_source=email&tag=a%2Bb&tag=two&empty="
    response = client.request(method, f"/benchmarks/draco-3pass?{query}")

    assert response.status_code == 301
    assert response.headers["location"] == f"/benchmarks/draco-3pass/?{query}"


async def _import_result(state: str) -> None:
    await _board(visibility="private" if state == "private" else "public")
    row = _row(metadata=None) if state == "unreviewed" else _row()
    await BaselineStore().import_baseline(row)
    if state == "stale":
        await Benchmark.filter(id=BOARD).update(revision="different-revision")


@pytest.mark.parametrize("state", ["eligible", "unreviewed", "stale", "private"])
def test_imported_result_indexing_matches_display_eligibility(
    client: TestClient, state: str
) -> None:
    assert client.portal is not None
    client.portal.call(_import_result, state)
    response = client.get(f"/benchmarks/{BOARD}/")
    page = _head(response.text)
    sitemap = client.get("/sitemap.xml")
    urls = {
        node.text
        for node in ElementTree.fromstring(sitemap.text).iter(
            "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
        )
    }

    assert response.status_code == sitemap.status_code == 200
    indexable = state == "eligible"
    assert ("robots" not in page.meta) is indexable
    assert (f"{PUBLIC_ORIGIN}/benchmarks/{BOARD}/" in urls) is indexable
    if indexable:
        result = client.get(f"/v1/leaderboard/{BOARD}").json()
        assert result["entries"] == []
        assert result["baselines"][0]["ranking_eligible"] is True
    if state == "private":
        assert "SAT-English" not in response.text
        assert page.canonical is None


@pytest.mark.parametrize("path", ["/benchmarks/draco-3pass/", "/sitemap.xml"])
@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("database refused connection"),
        TimeoutError("database timed out"),
        DBConnectionError("database unavailable"),
        OperationalError("database unavailable"),
        asyncpg.PostgresConnectionError("connection lost"),
        asyncpg.CannotConnectNowError("database starting"),
        asyncpg.TooManyConnectionsError("database full"),
    ],
)
def test_database_unavailability_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str, error: Exception
) -> None:
    monkeypatch.setattr(board_pages, "list_benchmark_summaries", AsyncMock(side_effect=error))

    for method in ("get", "head"):
        response = client.request(method, path)
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"


def test_existence_read_has_the_same_outage_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Benchmark, "exists", AsyncMock(side_effect=ConnectionRefusedError()))

    assert client.get("/benchmarks/missing/").status_code == 503


def test_programming_errors_are_not_hidden_as_outages(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        board_pages, "list_benchmark_summaries", AsyncMock(side_effect=ValueError("bad code"))
    )

    with pytest.raises(ValueError, match="bad code"):
        client.get("/benchmarks/draco-3pass/")


@pytest.mark.parametrize("identifier", [".", ".."])
def test_dot_segment_ids_never_redirect_to_another_page(
    client: TestClient, identifier: str
) -> None:
    response = client.get("/benchmark.html", params={"id": identifier})

    assert response.status_code == 404
    assert "location" not in response.headers


def test_bare_board_shell_is_not_indexable(client: TestClient) -> None:
    for query in ("", "?id=", "?utm_source=email"):
        response = client.get("/benchmark.html" + query)
        assert response.status_code == 200
        assert response.headers["x-robots-tag"] == "noindex,follow"


def test_server_lead_matches_javascript_without_description(client: TestClient) -> None:
    assert client.portal is not None

    async def clear_description() -> None:
        await Benchmark.filter(id="draco-3pass").update(description=None)

    client.portal.call(clear_description)
    page = _head(client.get("/benchmarks/draco-3pass/").text)

    assert page.text["benchmark-desc"] == ""


def test_imported_indexing_preserves_homepage_summary_contract(client: TestClient) -> None:
    assert client.portal is not None
    client.portal.call(_import_result, "eligible")

    summaries = client.get("/v1/benchmarks/summary").json()["benchmarks"]
    board = next(row for row in summaries if row["id"] == BOARD)
    assert board["best_score"] is None
    assert "robots" not in _head(client.get(f"/benchmarks/{BOARD}/").text).meta


def test_visibility_is_rechecked_after_imported_result_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.portal is not None
    client.portal.call(_import_result, "eligible")
    original = BaselineStore.best_ranked_scores

    async def make_private(self: BaselineStore, ids: Sequence[str]) -> dict[str, float]:
        scores = await original(self, ids)
        await Benchmark.filter(id=BOARD).update(visibility="private")
        return scores

    monkeypatch.setattr(BaselineStore, "best_ranked_scores", make_private)
    page = client.get(f"/benchmarks/{BOARD}/")

    assert page.status_code == 200
    assert "SAT-English" not in page.text
    assert _head(page.text).meta["robots"] == "noindex,follow"
    assert f"/benchmarks/{BOARD}/" not in client.get("/sitemap.xml").text
