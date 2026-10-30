"""OME-1517: corrupt stored money must not take down participant/history reads."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise
from tortoise.backends.base import executor
from tortoise.exceptions import OperationalError

from scoreboard.config import Settings
from scoreboard.export_private_submissions import collect_submissions, format_jsonl_bytes
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark

OWNER = "alice@example.test"
FIELDS = ["run_cost_usd", "cache_saved_cost_usd", "cache_saved_cost_archive_usd"]
PAYLOAD = {
    "benchmark_id": "cost-reads",
    "spec_id": "candidate",
    "url4_expression": "url4://candidate",
    "score": 0.7,
    "total_questions": 10,
    "ran_with_providers": ["openai"],
    "run_cost_usd": "1.250000",
    "run_cost_status": "complete",
    "cache_saved_cost_usd": "0.500000",
    "cache_saved_cost_archive_usd": "0.250000",
}


async def _seed() -> None:
    await Tortoise.generate_schemas()
    await Benchmark.create(id="cost-reads", display_name="Cost reads", visibility="private")


@pytest.fixture(params=["sqlite", "postgres"])
def cost_client(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, str], None, None]:
    backend = request.param
    database_url = f"sqlite://{tmp_path / 'costs.sqlite3'}"
    if backend == "postgres":
        if not os.getenv("SCOREBOARD_TEST_DATABASE_URL"):
            pytest.skip("requires PostgreSQL")
        database_url = request.getfixturevalue("postgres_schema_database_url")
    monkeypatch.setattr(executor, "EXECUTOR_CACHE", {})
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = create_app(
        Settings.model_validate(
            {
                "database_url": database_url,
                "cors_origins": [],
                "auth_mode": "cloudflare_headers",
                "allowed_networks": "127.0.0.1/32",
            }
        )
    )
    with TestClient(
        app,
        raise_server_exceptions=False,
        client=("127.0.0.1", 50000),
        headers={"X-User-Email": OWNER},
    ) as client:
        assert client.portal is not None
        client.portal.call(_seed)
        yield client, backend


def _create(client: TestClient, **overrides: Any) -> str:
    response = client.post("/v1/scores", json={**PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _corrupt(field: str, value: str, score_id: str, backend: str) -> None:
    assert field in FIELDS
    conn = Tortoise.get_connection("default")
    if backend == "postgres":
        await conn.execute_query(
            f'UPDATE scores SET "{field}" = $1::text::numeric WHERE id = $2',
            [value, UUID(score_id)],
        )
    else:
        await conn.execute_query(f'UPDATE scores SET "{field}" = ? WHERE id = ?', [value, score_id])


async def _money_snapshot() -> list[dict[str, Any]]:
    return await Tortoise.get_connection("default").execute_query_dict(
        "SELECT id, CAST(run_cost_usd AS TEXT) AS spend, "
        "CAST(cache_saved_cost_usd AS TEXT) AS saving, "
        "CAST(cache_saved_cost_archive_usd AS TEXT) AS archive FROM scores ORDER BY id"
    )


def _read(client: TestClient, surface: str) -> list[dict[str, Any]]:
    url = "/v1/leaderboard/cost-reads" + ("/candidate/history" if surface == "history" else "")
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()["submissions" if surface == "history" else "my_submissions"]


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("bad", ["NaN", "not-a-number"])
@pytest.mark.parametrize("surface", ["mine", "history"])
def test_bad_stored_amount_serves_unknown_without_dropping_rows(
    cost_client: tuple[TestClient, str], field: str, bad: str, surface: str
) -> None:
    client, backend = cost_client
    score_id = _create(client)
    _create(client, score=0.8)
    assert client.portal is not None
    if backend == "postgres" and bad == "not-a-number":
        # PostgreSQL refuses malformed NUMERIC text, but does store NaN (checked below).
        with pytest.raises(OperationalError, match="invalid input syntax"):
            client.portal.call(_corrupt, field, bad, score_id, backend)
        return
    client.portal.call(_corrupt, field, bad, score_id, backend)
    before = client.portal.call(_money_snapshot)
    rows = _read(client, surface)
    assert len(rows) == 2
    by_score = {row["score"]: row for row in rows}
    assert by_score[0.7]["run_cost_usd"] is None
    assert Decimal(by_score[0.8]["run_cost_usd"]) == Decimal("2")
    assert client.portal.call(_money_snapshot) == before


@pytest.mark.parametrize("surface", ["mine", "history"])
@pytest.mark.parametrize(
    "saving,archive,expected",
    [
        (None, None, "1.25"),
        ("0.50", None, "1.75"),
        (None, "0.25", "1.50"),
        ("0.50", "0.25", "2.00"),
    ],
)
def test_valid_and_absent_savings_keep_existing_meaning(
    cost_client: tuple[TestClient, str],
    surface: str,
    saving: str | None,
    archive: str | None,
    expected: str,
) -> None:
    client, _ = cost_client
    _create(client, cache_saved_cost_usd=saving, cache_saved_cost_archive_usd=archive)
    [row] = _read(client, surface)
    assert Decimal(row["run_cost_usd"]) == Decimal(expected)


async def _export() -> bytes:
    return format_jsonl_bytes(await collect_submissions("cost-reads"))


def test_served_reads_preserve_export_bytes_and_stored_cost_parts(
    cost_client: tuple[TestClient, str],
) -> None:
    client, _ = cost_client
    _create(client)
    assert client.portal is not None
    before = client.portal.call(_export)
    exported = json.loads(before)
    assert [exported[field] for field in FIELDS] == ["1.250000", "0.500000", "0.250000"]
    assert exported["submitted_by"] == OWNER
    for surface in ["mine", "history"]:
        _read(client, surface)
    assert client.portal.call(_export) == before


def test_owner_scope_history_limit_and_newest_first_survive(
    cost_client: tuple[TestClient, str],
) -> None:
    client, _ = cost_client
    _create(client)
    newest = _create(client, score=0.8)
    other = client.post(
        "/v1/scores", json={**PAYLOAD, "score": 0.9}, headers={"X-User-Email": "bob@example.test"}
    )
    assert other.status_code == 201, other.text
    for surface in ["mine", "history"]:
        assert [row["score"] for row in _read(client, surface)] == [0.8, 0.7]
    response = client.get("/v1/leaderboard/cost-reads/candidate/history?limit=1")
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["submissions"]] == [newest]


async def _legacy_timestamp(backend: str) -> None:
    # SQLite can contain legacy naive timestamps; the ORM previously interpreted these as UTC.
    timestamp = "2020-01-02 03:04:05" + ("+00:00" if backend == "postgres" else "")
    conn = Tortoise.get_connection("default")
    placeholder = "$1::text::timestamptz" if backend == "postgres" else "?"
    await conn.execute_query(f"UPDATE scores SET submitted_at = {placeholder}", [timestamp])


def test_served_reads_keep_the_orm_timestamp_interpretation(
    cost_client: tuple[TestClient, str],
) -> None:
    client, backend = cost_client
    _create(client)
    assert client.portal is not None
    client.portal.call(_legacy_timestamp, backend)
    for surface in ["mine", "history"]:
        [row] = _read(client, surface)
        assert row["submitted_at"] == "2020-01-02T03:04:05Z"
