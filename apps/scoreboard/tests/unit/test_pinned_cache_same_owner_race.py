"""A same-owner retry racing its own first submission is a dedup, never a second claim on the copy.

FEATURE: one frozen copy names one score (spec section 5), but a same-owner resubmit that the
board deduplicates onto the same row is not a second claim. A client that retries after a timeout
sends the same submission while the first is still in flight. Found end to end: six parallel
identical posts answered [201, 422, 422, 422, 422, 422] on PostgreSQL 17, because the copy
pre-check saw the row the winner had just committed and refused before the dedup path could run.

The race is driven deterministically: the first dedup lookup is made to miss (as it does when
the winner has not committed yet) while the winner's row is already stored, so the copy pre-check
is the first read to see it.
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
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

ALICE = "alice@example.test"
BOB = "bob@example.test"
COPY = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "benchmark_revision": "rev-1",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.3,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
        "capture_status": "complete",
        "frozen_copy_id": COPY,
        "case_digest": "a" * 64,
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


def _miss_the_first_dedup_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the next `_resolve_owned` miss once, as it does before the winner commits."""
    original = ScoreStore._resolve_owned
    calls = {"count": 0}

    async def racing(self: ScoreStore, *args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            return None, None
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ScoreStore, "_resolve_owned", racing)


@pytest.mark.parametrize("key", [None, "retry-key-1"])
async def test_a_retry_that_finds_its_own_row_at_the_precheck_is_a_dedup(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    headers = {"X-User-Email": ALICE, **({} if key is None else {"Idempotency-Key": key})}
    first = await client.post("/v1/scores", json=_payload(), headers=headers)
    assert first.status_code == 201, first.text

    _miss_the_first_dedup_lookup(monkeypatch)
    retry = await client.post("/v1/scores", json=_payload(), headers=headers)

    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert await Score.filter(frozen_copy_id=COPY).count() == 1


async def test_a_different_recipe_racing_for_the_copy_is_still_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await client.post("/v1/scores", json=_payload(), headers={"X-User-Email": ALICE})
    assert first.status_code == 201, first.text

    _miss_the_first_dedup_lookup(monkeypatch)
    other = await client.post(
        "/v1/scores", json=_payload(spec_id="spec-2"), headers={"X-User-Email": BOB}
    )

    assert other.status_code == 422, other.text
    assert other.json()["detail"]["code"] == "frozen_copy_claimed"
    assert await Score.all().count() == 1


async def test_another_owner_sending_the_same_public_recipe_gets_the_stored_row(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On a public board the recipe, not the submitter, is the identity, so this is the board's
    # existing dedup (a 200 with the stored row, nothing rewritten), not a claim on the copy.
    first = await client.post("/v1/scores", json=_payload(), headers={"X-User-Email": ALICE})

    _miss_the_first_dedup_lookup(monkeypatch)
    same_recipe = await client.post("/v1/scores", json=_payload(), headers={"X-User-Email": BOB})

    assert same_recipe.status_code == 200, same_recipe.text
    assert same_recipe.json()["id"] == first.json()["id"]
