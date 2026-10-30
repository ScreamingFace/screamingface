"""OME-969: public submissions obey the same metadata budget as baseline imports."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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


@pytest_asyncio.fixture
async def metadata_client(tortoise_db: None) -> AsyncGenerator[AsyncClient, None]:
    await Benchmark.create(id="metadata-limits", display_name="Metadata limits")
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"x": "a" * 4088},  # 4097 serialized bytes: one past the shared cap.
        {"x": "a" * 65536},
        {"x": "é" * 682},  # ASCII JSON escapes count, as on the baseline path.
        {"a": {"b": {"c": {"d": {"e": 1}}}}},
        {"a": [[[{"e": 1}]]]},
    ],
)
async def test_oversized_or_deep_metadata_is_422_without_writing(
    metadata_client: AsyncClient, metadata: dict[str, object]
) -> None:
    response = await metadata_client.post("/v1/scores", json={**PAYLOAD, "metadata": metadata})
    assert response.status_code == 422, response.text
    assert any(e["loc"] == ["body", "metadata"] for e in response.json()["detail"])
    assert await Score.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"trace_id": "abc123"},
        {"x": "a" * 4087},  # Exactly 4096 serialized bytes.
        {"x": "é" * 681 + "a"},  # Exactly 4096, including escaped Unicode.
        {"a": {"b": {"c": {"d": 1}}}},
        {"a": [[[1]]]},
    ],
)
async def test_valid_metadata_round_trips(
    metadata_client: AsyncClient, metadata: dict[str, object] | None
) -> None:
    if metadata and "x" in metadata:
        assert len(json.dumps(metadata).encode("utf-8")) == 4096
    response = await metadata_client.post("/v1/scores", json={**PAYLOAD, "metadata": metadata})
    assert response.status_code == 201, response.text
    assert response.json()["metadata"] == metadata
    stored = await Score.get(id=response.json()["id"])
    assert stored.metadata == metadata


@pytest.mark.asyncio
async def test_omitting_metadata_remains_valid(metadata_client: AsyncClient) -> None:
    response = await metadata_client.post("/v1/scores", json=PAYLOAD)
    assert response.status_code == 201, response.text
    assert response.json()["metadata"] is None
