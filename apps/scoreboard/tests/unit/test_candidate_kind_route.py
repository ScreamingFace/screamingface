"""`candidate_kind` on a public ranked row (OME-1852).

FEATURE: the public Pareto chart draws a single model as a circle and a fusion as a square
(Option A). Each ranked row carries which one it is, computed per request like `openness` and
`pinned_cache`, from the row's own `metadata.candidate_kind` — never from `spec_id` or
`ran_with_providers` length, and never stored on `LeaderboardEntry` (private `my_submissions`,
the export).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes.leaderboard import RankedLeaderboardEntry
from scoreboard.scores.models import Benchmark
from scoreboard.scores.schemas import LeaderboardEntry
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

ALICE = "alice@example.test"


def _payload(spec_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": spec_id,
        "url4_expression": f"url4://benchmark/{spec_id}",
        "score": 0.5,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def client(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app: FastAPI = create_app(
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


async def _submit(http: AsyncClient, spec_id: str, **overrides: Any) -> None:
    created = await http.post(
        "/v1/scores", json=_payload(spec_id, **overrides), headers={"X-User-Email": ALICE}
    )
    assert created.status_code == 201, created.text


async def test_the_field_is_on_the_ranked_row_only() -> None:
    assert "candidate_kind" in RankedLeaderboardEntry.model_fields
    assert "candidate_kind" not in LeaderboardEntry.model_fields


async def test_each_declared_kind_round_trips_and_an_unrecognised_one_is_unknown(
    client: AsyncClient,
) -> None:
    await _submit(client, "a-model", metadata={"candidate_kind": "model"})
    await _submit(client, "a-fusion", metadata={"candidate_kind": "fusion"})
    # The Client's own compiler emits these further kinds; neither is a fusion.
    await _submit(client, "a-pipeline", metadata={"candidate_kind": "pipeline"})
    await _submit(client, "no-metadata")
    await _submit(client, "junk-value", metadata={"candidate_kind": 42})

    response = await client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    by_spec = {entry["spec_id"]: entry["candidate_kind"] for entry in response.json()["entries"]}
    assert by_spec == {
        "a-model": "model",
        "a-fusion": "fusion",
        "a-pipeline": "unknown",
        "no-metadata": "unknown",
        "junk-value": "unknown",
    }


async def test_never_derived_from_spec_id_or_provider_count(client: AsyncClient) -> None:
    # A spec_id that reads like a fusion, and three providers (which OME-769's own column
    # comment says is not a valid fusion/solo test either), must still read Unknown absent a
    # real declaration.
    await _submit(
        client,
        "my-3-model-fusion-ensemble",
        ran_with_providers=["openai", "anthropic", "gemini"],
    )

    response = await client.get("/v1/leaderboard/hle")

    entry = response.json()["entries"][0]
    assert entry["candidate_kind"] == "unknown"


async def test_a_private_board_carries_no_candidate_kind_anywhere(client: AsyncClient) -> None:
    await _submit(client, "fusion-row", metadata={"candidate_kind": "fusion"})
    await ScoreStore().set_visibility("hle", "private")

    response = await client.get("/v1/leaderboard/hle", headers={"X-User-Email": ALICE})

    body = response.json()
    assert body["entries"] == []
    assert len(body["my_submissions"]) == 1
    assert "candidate_kind" not in body["my_submissions"][0]


async def test_an_empty_page_reads_no_candidate_kinds() -> None:
    # The store read the route uses, with no database: an empty id list reads nothing.
    assert await ScoreStore().candidate_kinds_for_score_ids([]) == {}
