"""End-to-end fixtures for the SF desktop "Publish to Leaderboard" payload (D-SCORE-006).

Simulates the exact wire shape the ScreamingFace desktop app POSTs to /v1/scores,
including the nested `client` object and the Idempotency-Key=<eval_run_id> header,
and confirms the round-trip, idempotency, unknown-benchmark, CORS, and contract
strictness behaviour the scoreboard side owns.
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
from scoreboard.scores.models import Benchmark

pytestmark = pytest.mark.asyncio

# A repeat "Publish" click sends the same eval_run_id, so it doubles as the
# Idempotency-Key — clicking twice must create exactly one row.
_EVAL_RUN_ID = "eval-run-abc123"


def _sf_payload(**overrides: Any) -> dict[str, Any]:
    """The documented SF desktop submission body (nested `client`)."""
    payload: dict[str, Any] = {
        "version": 1,
        "benchmark_id": "hle",
        "spec_id": "hle-ensemble-three",
        "url4_expression": "url4://ensemble(claude,codex,gemini)/hle",
        "score": 0.81,
        "total_questions": 1000,
        "correct_questions": 810,
        "ran_with_providers": ["claude", "codex", "gemini"],
        "run_cost_usd": "4.250000",
        "submitted_by": None,
        "ran_at_local": "2026-05-04T11:55:00Z",
        "client": {"name": "screamingface-desktop", "version": "0.4.2", "platform": "darwin"},
        "metadata": None,
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def app_with_benchmark(tortoise_db: None) -> FastAPI:
    settings = Settings(database_url="sqlite://:memory:", cors_origins=[])
    app = create_app(settings)
    await Benchmark.create(
        id="hle",
        display_name="Humanity's Last Exam",
        description="Fixture benchmark",
        dataset_url="https://example.test/hle.jsonl",
    )
    return app


@pytest_asyncio.fixture
async def sf_client(app_with_benchmark: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app_with_benchmark),
        base_url="http://test",
    ) as client:
        yield client


async def test_sf_payload_round_trips_201(sf_client: AsyncClient) -> None:
    response = await sf_client.post(
        "/v1/scores", json=_sf_payload(), headers={"Idempotency-Key": _EVAL_RUN_ID}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"]
    assert body["benchmark_id"] == "hle"
    assert body["spec_id"] == "hle-ensemble-three"
    assert body["score"] == 0.81
    assert body["total_questions"] == 1000
    assert body["correct_questions"] == 810
    assert body["ran_with_providers"] == ["claude", "codex", "gemini"]
    assert body["submitted_by"] is None
    # OME-820: verified defaults to True as a placeholder that asserts NOTHING —
    # nothing re-runs submissions and nothing attests where a run executed. The
    # False case stays covered by the explicit-False row test.
    assert body["verified_by_screamingface"] is True
    # Nested `client` on the request maps to the flat client_* read fields.
    assert body["client_name"] == "screamingface-desktop"
    assert body["client_version"] == "0.4.2"
    assert body["client_platform"] == "darwin"


async def test_repeat_publish_is_idempotent(sf_client: AsyncClient) -> None:
    first = await sf_client.post(
        "/v1/scores", json=_sf_payload(), headers={"Idempotency-Key": _EVAL_RUN_ID}
    )
    assert first.status_code == 201, first.text
    score_id = first.json()["id"]

    # Second click with the same eval_run_id must not create a duplicate.
    second = await sf_client.post(
        "/v1/scores", json=_sf_payload(), headers={"Idempotency-Key": _EVAL_RUN_ID}
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == score_id

    fetched = await sf_client.get(f"/v1/scores/{score_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == score_id


async def test_unknown_benchmark_returns_404(sf_client: AsyncClient) -> None:
    response = await sf_client.post(
        "/v1/scores",
        json=_sf_payload(benchmark_id="not-registered"),
        headers={"Idempotency-Key": "eval-run-unknown"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["field"] == "benchmark_id"


async def test_client_is_optional(sf_client: AsyncClient) -> None:
    payload = _sf_payload()
    payload.pop("client")
    response = await sf_client.post(
        "/v1/scores", json=payload, headers={"Idempotency-Key": "eval-run-no-client"}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["client_name"] is None
    assert body["client_version"] is None
    assert body["client_platform"] is None


async def test_flat_client_fields_are_rejected(sf_client: AsyncClient) -> None:
    # The contract is nested-only; the legacy flat shape must be rejected so SF
    # and the scoreboard cannot silently drift apart on the client metadata.
    payload = _sf_payload()
    payload.pop("client")
    payload["client_name"] = "screamingface-desktop"
    response = await sf_client.post(
        "/v1/scores", json=payload, headers={"Idempotency-Key": "eval-run-flat"}
    )
    assert response.status_code == 422


async def test_cors_allows_electron_renderer_origin() -> None:
    # Electron renderers fetch with an Origin header (e.g. file://). With
    # cors_origins=["*"] and credentials disabled, the API echoes ACAO: *.
    settings = Settings(database_url="sqlite://:memory:", cors_origins=["*"])
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz", headers={"Origin": "file://"})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"
