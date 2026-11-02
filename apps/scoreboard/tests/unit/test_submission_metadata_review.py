"""OME-969 review: bounded validation work and PostgreSQL numeric expansion."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise
from tortoise.backends.base import executor

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score

PAYLOAD = {
    "benchmark_id": "metadata-limits",
    "spec_id": "candidate",
    "url4_expression": "url4://candidate",
    "score": 0.75,
    "total_questions": 4,
    "ran_with_providers": ["openrouter"],
}


async def _seed() -> None:
    await Tortoise.generate_schemas()
    await Benchmark.create(id="metadata-limits", display_name="Metadata limits")


@pytest.fixture(params=["sqlite", "postgres"])
def bounded_client(request, tmp_path: Path, monkeypatch) -> Generator[TestClient, None, None]:
    url = f"sqlite://{tmp_path / 'metadata.sqlite3'}"
    if request.param == "postgres":
        if not os.getenv("SCOREBOARD_TEST_DATABASE_URL"):
            pytest.skip("requires PostgreSQL")
        url = request.getfixturevalue("postgres_schema_database_url")
    monkeypatch.setattr(executor, "EXECUTOR_CACHE", {})
    app = create_app(Settings(database_url=url, cors_origins=[]))
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.portal is not None
        client.portal.call(_seed)
        yield client


async def _count() -> int:
    return await Score.all().count()


@pytest.mark.parametrize("depth", [50, 500, 900, 1500])
def test_deep_metadata_returns_field_error_without_writing(bounded_client, depth):
    raw = json.dumps(PAYLOAD)[:-1] + ',"metadata":{"x":' + "[" * depth + "0" + "]" * depth + "}}"
    response = bounded_client.post(
        "/v1/scores", content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code in {400, 422}, response.text
    if response.status_code == 422:
        [error] = response.json()["detail"]
        assert error["loc"] == ["body", "metadata"]
        assert "input" not in error
    assert bounded_client.portal.call(_count) == 0


def test_json_decoder_depth_limit_is_a_client_error(bounded_client):
    raw = json.dumps(PAYLOAD)[:-1] + ',"metadata":{"x":' + "[" * 10000 + "0" + "]" * 10000 + "}}"
    response = bounded_client.post(
        "/v1/scores", content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400, response.text
    assert bounded_client.portal.call(_count) == 0


@pytest.mark.parametrize("number,count", [(1e308, 500), (-1e308, 450), (1e-308, 450)])
def test_expanded_numeric_metadata_cannot_exceed_budget(bounded_client, number, count):
    metadata = {"x": [number] * count}
    assert len(json.dumps(metadata)) <= 4096
    response = bounded_client.post("/v1/scores", json={**PAYLOAD, "metadata": metadata})
    assert response.status_code == 422, response.text
    assert any(error["loc"] == ["body", "metadata"] for error in response.json()["detail"])
    assert bounded_client.portal.call(_count) == 0


@pytest.mark.parametrize("padding,status", [(3774, 201), (3775, 422)])
def test_expanded_numeric_boundary_is_exact(bounded_client, padding, status):
    # 309 decimal digits plus JSON punctuation/string padding: exactly 4096 or 4097.
    metadata = {"x": [1e308, "a" * padding]}
    assert len(json.dumps({"x": [10**308, "a" * padding]})) == (4096 if status == 201 else 4097)
    response = bounded_client.post("/v1/scores", json={**PAYLOAD, "metadata": metadata})
    assert response.status_code == status, response.text
    assert bounded_client.portal.call(_count) == (1 if status == 201 else 0)
    if status == 201:
        stored_size = bounded_client.portal.call(_stored_jsonb_size)
        if stored_size is not None:
            assert stored_size == 4096


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_metadata_numbers_are_rejected(bounded_client, number):
    raw = json.dumps(PAYLOAD)[:-1] + ',"metadata":{"x":' + number + "}}"
    response = bounded_client.post(
        "/v1/scores", content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "metadata"]
    assert bounded_client.portal.call(_count) == 0


async def _stored_jsonb_size() -> int | None:
    connection = Tortoise.get_connection("default")
    if connection.capabilities.dialect != "postgres":
        return None
    [row] = await connection.execute_query_dict(
        "SELECT octet_length(metadata::text) AS size FROM scores"
    )
    return row["size"]
