"""The compact homepage summary agrees with the public board without N+1 reads."""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise
from tortoise.backends.base import executor

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score


@pytest.fixture(params=["sqlite", "postgres"])
def catalog_client(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient]:
    url = f"sqlite://{tmp_path / 'catalog.sqlite3'}"
    if request.param == "postgres":
        url = request.getfixturevalue("postgres_schema_database_url")
    monkeypatch.setattr(executor, "EXECUTOR_CACHE", {})
    with TestClient(create_app(Settings(database_url=url, cors_origins=[]))) as client:
        assert client.portal is not None
        client.portal.call(Tortoise.generate_schemas)
        yield client


async def seed_catalog() -> None:
    for name, revision, count in [
        ("pinned", "r1", 10),
        ("legacy", None, None),
        ("zero", "r1", 10),
        ("negative", "r1", 10),
        ("empty", "r1", 10),
        ("private", "r1", 10),
        ("legacy-null-visibility", None, None),
    ]:
        await Benchmark.create(
            id=name,
            display_name=name,
            revision=revision,
            case_count=count,
            description="Description",
            focus="Focus",
            visibility="private" if name == "private" else "public",
        )
    await Benchmark.filter(id="legacy-null-visibility").update(visibility=None)
    rows = [
        ("pinned", "same", "r1", 10, 0.5),
        ("pinned", "same", "r1", 10, 0.7),
        ("pinned", "other", "r1", 11, 0.6),
        ("pinned", "old", "r0", 10, 99),
        ("pinned", "missing", None, 10, 98),
        ("pinned", "partial", "r1", 9, 97),
        ("legacy", "same", "r0", 1, 0.4),
        ("legacy", "same", "r1", 2, 0.8),
        ("zero", "s", "r1", 10, 0),
        ("negative", "s", "r1", 10, -2),
        ("private", "secret", "r1", 10, 123),
    ]
    for board, spec, revision, count, score in rows:
        await Score.create(
            benchmark_id=board,
            spec_id=spec,
            benchmark_revision=revision,
            score=score,
            total_questions=count,
            ran_with_providers=[],
            url4_expression="url4://test",
            verified_by_screamingface=False,
        )


def test_summary_matches_ranked_boards_and_omits_details(catalog_client: TestClient) -> None:
    assert catalog_client.portal is not None
    catalog_client.portal.call(seed_catalog)
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    rows = response.json()["benchmarks"]
    expected = {
        "pinned": 0.7,
        "legacy": 0.8,
        "zero": 0,
        "negative": -2,
        "empty": None,
        "legacy-null-visibility": None,
    }
    assert {row["id"]: row["best_score"] for row in rows} == expected
    for row in rows:
        assert set(row) == {"id", "display_name", "description", "focus", "best_score"}
        board = catalog_client.get(f"/v1/leaderboard/{row['id']}?top=1")
        assert board.status_code == 200
        scores = [entry["score"] for entry in board.json()["entries"]]
        assert row["best_score"] == max(scores, default=None)
    # SDK catalog contract retains private metadata.
    assert "private" in {b["id"] for b in catalog_client.get("/v1/benchmarks").json()["benchmarks"]}


def test_summary_refreshes_after_score_and_visibility_changes(catalog_client: TestClient) -> None:
    assert catalog_client.portal is not None
    catalog_client.portal.call(seed_catalog)
    assert catalog_client.get("/v1/benchmarks/summary").status_code == 200

    async def change() -> None:
        await Score.filter(benchmark_id="zero").update(score=1.5)
        await Benchmark.filter(id="pinned").update(visibility="private")
        await Benchmark.filter(id="negative").update(revision="r2")

    catalog_client.portal.call(change)
    rows = catalog_client.get("/v1/benchmarks/summary").json()["benchmarks"]
    scores = {row["id"]: row["best_score"] for row in rows}
    assert scores["zero"] == 1.5
    assert scores["negative"] is None
    assert "pinned" not in scores


def test_summary_empty_catalog(catalog_client: TestClient) -> None:
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    assert response.json() == {"benchmarks": []}


@pytest.mark.parametrize("size", [1, 86])
def test_summary_uses_two_database_statements(
    catalog_client: TestClient, monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    assert catalog_client.portal is not None

    async def prepare() -> tuple[AsyncMock, AsyncMock]:
        await Benchmark.bulk_create(
            [Benchmark(id=f"b-{i}", display_name=f"Board {i}") for i in range(size)]
        )
        connection = Tortoise.get_connection("default")
        spy = AsyncMock(wraps=connection.execute_query)
        monkeypatch.setattr(connection, "execute_query", spy)
        dict_spy = AsyncMock(wraps=connection.execute_query_dict)
        monkeypatch.setattr(connection, "execute_query_dict", dict_spy)
        return spy, dict_spy

    spy, dict_spy = catalog_client.portal.call(prepare)
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    assert len(response.json()["benchmarks"]) == size
    assert spy.await_count + dict_spy.await_count == 2


def test_baselines_do_not_populate_empty_summary(catalog_client: TestClient) -> None:
    from scoreboard.scores.models import Baseline

    assert catalog_client.portal is not None

    async def seed() -> None:
        await Benchmark.create(id="baseline-only", display_name="Baseline only")
        await Baseline.create(
            benchmark_id="baseline-only", model_name="External", score=99, source="paper"
        )

    catalog_client.portal.call(seed)
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    assert response.json()["benchmarks"][0]["best_score"] is None
    assert response.headers["cache-control"] == "no-store"


def test_scope_variations_match_the_ranked_board(catalog_client: TestClient) -> None:
    assert catalog_client.portal is not None

    async def seed() -> None:
        for i, (revision, count) in enumerate([(None, 10), ("r1", None), ("r1", 0)]):
            board = f"scope-{i}"
            await Benchmark.create(
                id=board, display_name=board, revision=revision, case_count=count
            )
            for j, (rev, questions, score) in enumerate(
                [
                    (None, 10, 5),
                    ("r0", 20, 4),
                    ("r1", 9, 3),
                    ("r1", 10, 2),
                    ("r1", 11, 2),
                    ("r1", 10, -1),
                ]
            ):
                await Score.create(
                    benchmark_id=board,
                    spec_id=f"s-{j % 2}",
                    benchmark_revision=rev,
                    total_questions=questions,
                    score=score,
                    ran_with_providers=[],
                    url4_expression="url4://test",
                )

    catalog_client.portal.call(seed)
    rows = catalog_client.get("/v1/benchmarks/summary").json()["benchmarks"]
    assert len(rows) == 3
    for row in rows:
        board = catalog_client.get(f"/v1/leaderboard/{row['id']}?top=1")
        assert board.status_code == 200
        assert row["best_score"] == board.json()["entries"][0]["score"]


def test_private_flip_during_summary_read_is_excluded(
    catalog_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scoreboard.scores import catalog

    assert catalog_client.portal is not None
    catalog_client.portal.call(seed_catalog)
    original = catalog.execute_pypika

    async def flip_after_read(*args, **kwargs):
        result = await original(*args, **kwargs)
        await Benchmark.filter(id="pinned").update(visibility="private")
        return result

    monkeypatch.setattr(catalog, "execute_pypika", flip_after_read)
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    assert "pinned" not in {row["id"] for row in response.json()["benchmarks"]}


@pytest.mark.parametrize("corruption", ["providers", "text-score", "nan-score", "infinite-score"])
def test_corrupt_candidate_cannot_fail_other_catalog_cards(
    catalog_client: TestClient, corruption: str
) -> None:
    assert catalog_client.portal is not None

    dialect = catalog_client.portal.call(
        lambda: Tortoise.get_connection("default").capabilities.dialect
    )
    if dialect != "sqlite" and corruption == "text-score":
        pytest.skip("PostgreSQL rejects arbitrary text in a float column")

    async def corrupt() -> None:
        await seed_catalog()
        conn = Tortoise.get_connection("default")
        if corruption == "providers":
            # A malformed JSON document on SQLite; a valid JSON scalar that cannot
            # decode as provider JSON on PostgreSQL (JSON syntax itself is enforced).
            raw = "broken-json" if conn.capabilities.dialect == "sqlite" else '"broken-json"'
            await conn.execute_query(
                (
                    "UPDATE scores SET ran_with_providers = ? WHERE benchmark_id = 'zero'"
                    if dialect == "sqlite"
                    else "UPDATE scores SET ran_with_providers = $1 WHERE benchmark_id = 'zero'"
                ),
                [raw],
            )
        else:
            raw = {"text-score": "broken-score", "nan-score": "NaN", "infinite-score": "Infinity"}[
                corruption
            ]
            await conn.execute_query(
                (
                    "UPDATE scores SET score = ? WHERE benchmark_id = 'zero'"
                    if dialect == "sqlite"
                    else "UPDATE scores SET score = $1 WHERE benchmark_id = 'zero'"
                ),
                [raw if conn.capabilities.dialect == "sqlite" else float(raw)],
            )

    catalog_client.portal.call(corrupt)
    # Providers corruption is independently tested, not left over from an earlier
    # experiment. Its board must drop the row and still answer successfully.
    if corruption == "providers" and dialect == "sqlite":
        board = catalog_client.get("/v1/leaderboard/zero?top=1")
        assert board.status_code == 200
        assert board.json()["entries"] == []
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    scores = {row["id"]: row["best_score"] for row in response.json()["benchmarks"]}
    assert scores["zero"] is None
    assert scores["pinned"] == 0.7
    assert scores["negative"] == -2


@pytest.mark.parametrize(
    ("same_spec", "corrupt_newer", "expected"),
    [(True, True, None), (True, False, 0.9), (False, True, 0.9), (False, False, None)],
)
def test_corrupt_tied_candidate_obeys_top_one_selection(
    catalog_client: TestClient, same_spec: bool, corrupt_newer: bool, expected: float | None
) -> None:
    from datetime import UTC, datetime, timedelta

    assert catalog_client.portal is not None

    async def seed() -> str:
        await Benchmark.create(id="ties", display_name="Ties")
        conn = Tortoise.get_connection("default")
        dialect = conn.capabilities.dialect
        for i in range(2):
            entry = await Score.create(
                benchmark_id="ties",
                spec_id="s" if same_spec else f"s-{i}",
                score=0.9,
                total_questions=10,
                ran_with_providers=[],
                url4_expression="url4://test",
            )
            await Score.filter(id=entry.id).update(
                submitted_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)
            )
            if bool(i) == corrupt_newer:
                await conn.execute_query(
                    "UPDATE scores SET ran_with_providers = ? WHERE id = ?"
                    if dialect == "sqlite"
                    else "UPDATE scores SET ran_with_providers = $1 WHERE id = $2",
                    ["broken-json" if dialect == "sqlite" else '"broken-json"', str(entry.id)],
                )
        # A lower readable score must not replace an unreadable top=1 candidate.
        await Score.create(
            benchmark_id="ties",
            spec_id="lower",
            score=0.5,
            total_questions=10,
            ran_with_providers=[],
            url4_expression="url4://test",
        )
        return dialect

    dialect = catalog_client.portal.call(seed)
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    assert response.json()["benchmarks"][0]["best_score"] == expected
    if dialect == "sqlite":
        board = catalog_client.get("/v1/leaderboard/ties?top=1")
        assert board.status_code == 200
        assert [e["score"] for e in board.json()["entries"]] == (
            [] if expected is None else [expected]
        )


def test_unreadable_nullable_details_do_not_hide_catalog_score(catalog_client: TestClient) -> None:
    assert catalog_client.portal is not None
    dialect = catalog_client.portal.call(
        lambda: Tortoise.get_connection("default").capabilities.dialect
    )
    if dialect != "sqlite":
        pytest.skip("PostgreSQL enforces JSON syntax and numeric column types")

    async def corrupt() -> None:
        await seed_catalog()
        await Tortoise.get_connection("default").execute_query(
            "UPDATE scores SET authors = ?, run_cost_usd = ?, cache_saved_cost_usd = ? "
            "WHERE benchmark_id = 'zero'",
            ["broken-json", "broken-cost", "broken-saving"],
        )

    catalog_client.portal.call(corrupt)
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    scores = {row["id"]: row["best_score"] for row in response.json()["benchmarks"]}
    assert scores["zero"] == 0
    board = catalog_client.get("/v1/leaderboard/zero?top=1")
    assert board.status_code == 200
    assert board.json()["entries"][0]["score"] == 0
