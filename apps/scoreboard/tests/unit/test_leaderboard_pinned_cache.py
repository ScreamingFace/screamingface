"""`pinned_cache` on a public ranked row (spec section 6).

FEATURE: each fully captured public row names its pinned cache, so the portal's Reproduce button
can copy `sf.evaluate(pinned_cache="<id>")`. Computed per request like `on_pareto_frontier`, in the
same snapshot as the rows, and never on `LeaderboardEntry` (private `my_submissions`, the export).
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
COPY = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"
PARTIAL_COPY = "ffeeddcc-bbaa-4998-8776-655443322110"


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


def test_the_field_is_on_the_ranked_row_only() -> None:
    assert "pinned_cache" in RankedLeaderboardEntry.model_fields
    assert "pinned_cache" not in LeaderboardEntry.model_fields


async def test_only_a_complete_capture_names_its_pinned_cache(client: AsyncClient) -> None:
    await _submit(client, "complete", capture_status="complete", frozen_copy_id=COPY)
    await _submit(client, "partial", capture_status="partial", frozen_copy_id=PARTIAL_COPY)
    await _submit(client, "no-copy", capture_status="partial")
    await _submit(client, "legacy")
    await _submit(client, "complete-no-copy", capture_status="complete")

    response = await client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    # Absent and null mean the same, no Reproduce; a row with nothing to replay leaves it out.
    by_spec = {entry["spec_id"]: entry.get("pinned_cache") for entry in response.json()["entries"]}
    assert by_spec == {
        "complete": COPY,
        "partial": None,
        "no-copy": None,
        "legacy": None,
        "complete-no-copy": None,
    }
    others = [entry for entry in response.json()["entries"] if entry["spec_id"] != "complete"]
    assert all("pinned_cache" not in entry for entry in others)


async def test_a_private_board_carries_no_pinned_cache_anywhere(client: AsyncClient) -> None:
    await _submit(client, "complete", capture_status="complete", frozen_copy_id=COPY)
    await ScoreStore().set_visibility("hle", "private")

    response = await client.get("/v1/leaderboard/hle", headers={"X-User-Email": ALICE})

    body = response.json()
    assert body["entries"] == []
    assert len(body["my_submissions"]) == 1
    assert "pinned_cache" not in body["my_submissions"][0]


async def test_the_side_read_returns_only_complete_captures() -> None:
    # Unit view of the store read the route uses, with no database: an empty id list reads
    # nothing and answers nothing.
    assert await ScoreStore().pinned_caches_for_score_ids([]) == {}
