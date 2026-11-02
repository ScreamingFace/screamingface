"""Metadata scalar validation and type-sensitive edit/audit regressions (OME-1596)."""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent

pytestmark = pytest.mark.asyncio
OWNER = "alice@example.test"
HEADERS = {"X-User-Email": OWNER}
PAYLOAD = {
    "benchmark_id": "hle",
    "spec_id": "scalar-regression",
    "url4_expression": "url4://benchmark/scalar-regression",
    "score": 0.75,
    "total_questions": 4,
    "ran_with_providers": ["openai"],
}


@pytest_asyncio.fixture
async def client(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = create_app(
        Settings.model_validate(
            {
                "database_url": "sqlite://:memory:",
                "cors_origins": [],
                "auth_mode": "cloudflare_headers",
                "allowed_networks": "127.0.0.1/32",
            }
        )
    )
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _metadata(field: str, values: dict[str, Any]) -> dict[str, Any]:
    return {OWNER: values} if field == "authors_metadata" else values


async def _edit(client: AsyncClient, score_id: str, method: str, fields: dict[str, Any]) -> None:
    if method == "patch":
        response = await client.patch(f"/v1/scores/{score_id}", json=fields, headers=HEADERS)
    else:
        response = await client.post("/v1/scores", json={**PAYLOAD, **fields}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == score_id


@pytest.mark.parametrize("field", ["paper_metadata", "authors_metadata"])
@pytest.mark.parametrize("value", [10**309, -(10**309)])
async def test_large_finite_integer_survives_submit_and_patch(
    client: AsyncClient, field: str, value: int
) -> None:
    metadata = _metadata(field, {"custom": value})
    created = await client.post("/v1/scores", json={**PAYLOAD, field: metadata}, headers=HEADERS)
    assert created.status_code == 201, created.text
    score_id = created.json()["id"]
    assert getattr(await Score.get(id=score_id), field) == metadata

    replacement = _metadata(field, {"custom": value + 1})
    await _edit(client, score_id, "patch", {field: replacement})
    assert getattr(await Score.get(id=score_id), field) == replacement
    [event] = await ScoreMetadataEvent.filter(score_id=score_id)
    assert getattr(event, f"old_{field}") == metadata
    assert getattr(event, f"new_{field}") == replacement


@pytest.mark.parametrize("field", ["paper_metadata", "authors_metadata"])
@pytest.mark.parametrize("method", ["patch", "resubmit"])
@pytest.mark.parametrize("old,new", [(1, True), (True, 1), (0, False), (False, 0)])
async def test_boolean_number_edit_is_saved_and_audited(
    client: AsyncClient, field: str, method: str, old: int | bool, new: int | bool
) -> None:
    before = _metadata(field, {"custom": old})
    after = _metadata(field, {"custom": new})
    created = await client.post("/v1/scores", json={**PAYLOAD, field: before}, headers=HEADERS)
    assert created.status_code == 201, created.text
    score_id = created.json()["id"]

    await _edit(client, score_id, method, {field: after})

    stored = await Score.get(id=score_id)
    values = getattr(stored, field)
    actual = values[OWNER]["custom"] if field == "authors_metadata" else values["custom"]
    assert type(actual) is type(new)
    assert actual == new
    [event] = await ScoreMetadataEvent.filter(score_id=score_id)
    assert event.source == method
    assert stored.metadata_updated_at == event.edited_at
    for prefix, expected in (("old", old), ("new", new)):
        snapshot = getattr(event, f"{prefix}_{field}")
        scalar = snapshot[OWNER]["custom"] if field == "authors_metadata" else snapshot["custom"]
        assert type(scalar) is type(expected)
        assert scalar == expected

    # Retrying the successful edit must not generate another audit event or timestamp.
    await _edit(client, score_id, method, {field: after})
    assert await ScoreMetadataEvent.filter(score_id=score_id).count() == 1
    assert (await Score.get(id=score_id)).metadata_updated_at == stored.metadata_updated_at


@pytest.mark.parametrize("field", ["paper_metadata", "authors_metadata"])
@pytest.mark.parametrize("method", ["patch", "resubmit"])
async def test_reordered_object_is_not_an_edit(
    client: AsyncClient, field: str, method: str
) -> None:
    before = _metadata(field, {"custom": True, "pages": 1})
    after = _metadata(field, {"pages": 1, "custom": True})
    created = await client.post("/v1/scores", json={**PAYLOAD, field: before}, headers=HEADERS)
    assert created.status_code == 201, created.text
    score_id = created.json()["id"]

    await _edit(client, score_id, method, {field: after})

    assert await ScoreMetadataEvent.filter(score_id=score_id).count() == 0
    assert (await Score.get(id=score_id)).metadata_updated_at is None


@pytest.mark.parametrize("field", ["paper_metadata", "authors_metadata"])
@pytest.mark.parametrize("method", ["patch", "resubmit"])
@pytest.mark.parametrize("old,new", [(1, 1.0), (1.0, 1)])
async def test_equal_numbers_are_not_an_edit(
    client: AsyncClient, field: str, method: str, old: int | float, new: int | float
) -> None:
    before = _metadata(field, {"custom": old})
    after = _metadata(field, {"custom": new})
    created = await client.post("/v1/scores", json={**PAYLOAD, field: before}, headers=HEADERS)
    assert created.status_code == 201, created.text
    score_id = created.json()["id"]

    await _edit(client, score_id, method, {field: after})

    assert await ScoreMetadataEvent.filter(score_id=score_id).count() == 0
    assert (await Score.get(id=score_id)).metadata_updated_at is None
