"""A separate paper URL cannot make the published metadata exceed its write limits."""

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
PAPER = "https://example.test/paper"
PAYLOAD = {
    "benchmark_id": "hle",
    "spec_id": "paper-limit",
    "url4_expression": "url4://paper-limit",
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
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-User-Email": OWNER},
    ) as http:
        yield http


async def _edit(client: AsyncClient, method: str, score_id: str, fields: dict[str, Any]) -> Any:
    if method == "patch":
        return await client.patch(f"/v1/scores/{score_id}", json=fields)
    return await client.post("/v1/scores", json={**PAYLOAD, **fields})


@pytest.mark.parametrize("method", ["patch", "resubmit"])
@pytest.mark.parametrize("keys,status", [(19, 200), (20, 422)])
async def test_separate_url_counts_toward_final_key_limit(
    client: AsyncClient, method: str, keys: int, status: int
) -> None:
    metadata = {f"k{i}": "v" for i in range(keys)}
    created = await client.post("/v1/scores", json={**PAYLOAD, "paper_metadata": metadata})
    assert created.status_code == 201, created.text
    score_id = created.json()["id"]

    edited = await _edit(client, method, score_id, {"paper_url": PAPER})

    assert edited.status_code == status, edited.text
    stored = await Score.get(id=score_id)
    assert stored.paper_metadata == metadata
    if status == 422:
        assert [e["loc"] for e in edited.json()["detail"]] == [["body", "paper_metadata"]]
        assert stored.paper_url is None
        assert stored.metadata_updated_at is None
        assert await ScoreMetadataEvent.all().count() == 0
    else:
        assert edited.json()["paper_metadata"] == {**metadata, "url": PAPER}
        # INVARIANT: the exact object returned by an accepted edit is writable unchanged.
        again = await _edit(
            client, method, score_id, {"paper_metadata": edited.json()["paper_metadata"]}
        )
        assert again.status_code == 200, again.text
        assert again.json()["paper_metadata"] == edited.json()["paper_metadata"]
        assert await ScoreMetadataEvent.all().count() == 1


@pytest.mark.parametrize("method", ["patch", "resubmit"])
async def test_separate_url_counts_toward_final_byte_limit(
    client: AsyncClient, method: str
) -> None:
    # Nineteen keys remain under 64 KiB as stored, but a long URL exceeds that
    # byte bound without exceeding the 20-key bound. Never drop existing fields to fit.
    metadata = {"title": "\x01" * 300, "citation": "\x01" * 2000}
    metadata.update({f"k{i}": "\x01" * 500 for i in range(17)})
    created = await client.post("/v1/scores", json={**PAYLOAD, "paper_metadata": metadata})
    assert created.status_code == 201, created.text
    score_id = created.json()["id"]

    edited = await _edit(client, method, score_id, {"paper_url": PAPER + "x" * 2000})

    assert edited.status_code == 422, edited.text
    assert [e["loc"] for e in edited.json()["detail"]] == [["body", "paper_metadata"]]
    stored = await Score.get(id=score_id)
    assert stored.paper_metadata == metadata
    assert stored.paper_url is None
    assert stored.metadata_updated_at is None
    assert await ScoreMetadataEvent.all().count() == 0


@pytest.mark.parametrize("method", ["patch", "resubmit"])
async def test_url_only_legacy_row_does_not_gain_a_metadata_object(
    client: AsyncClient, method: str
) -> None:
    created = await client.post("/v1/scores", json=PAYLOAD)
    score_id = created.json()["id"]

    edited = await _edit(client, method, score_id, {"paper_url": PAPER})

    assert edited.status_code == 200, edited.text
    assert edited.json()["paper_url"] == PAPER
    assert "paper_metadata" not in edited.json()
    assert (await Score.get(id=score_id)).paper_metadata is None


@pytest.mark.parametrize("method", ["patch", "resubmit"])
async def test_whole_replacement_validates_new_metadata_not_the_old_link(
    client: AsyncClient, method: str
) -> None:
    created = await client.post(
        "/v1/scores", json={**PAYLOAD, "paper_metadata": {"title": "Old", "url": PAPER}}
    )
    score_id = created.json()["id"]
    replacement = {f"k{i}": "v" for i in range(20)}

    edited = await _edit(client, method, score_id, {"paper_metadata": replacement})

    assert edited.status_code == 200, edited.text
    assert edited.json()["paper_metadata"] == replacement
    stored = await Score.get(id=score_id)
    assert stored.paper_url is None
    assert stored.paper_metadata == replacement


@pytest.mark.parametrize("field", ["paper_url", "paper_metadata"])
async def test_patch_can_still_clear_the_link(client: AsyncClient, field: str) -> None:
    created = await client.post(
        "/v1/scores", json={**PAYLOAD, "paper_metadata": {"title": "Old", "url": PAPER}}
    )
    score_id = created.json()["id"]

    edited = await client.patch(f"/v1/scores/{score_id}", json={field: None})

    assert edited.status_code == 200, edited.text
    stored = await Score.get(id=score_id)
    assert stored.paper_url is None
    assert stored.paper_metadata == (None if field == "paper_metadata" else {"title": "Old"})
