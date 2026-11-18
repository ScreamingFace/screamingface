"""The copy claim wiring of the app: lifespan, settings, OpenAPI and the delete path (OME-1947)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

import scoreboard.main as main_module
from scoreboard.config import Settings
from scoreboard.core.copy_claims import ClaimResult
from scoreboard.delete_scores import delete_scores
from scoreboard.gateway_copy_claims import GatewayCopyClaims
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore
from tests.unit.test_submit_claims_copy import ALICE, FakeClaims, _payload, _settings


@pytest.mark.asyncio
async def test_a_create_app_with_a_gateway_url_builds_the_claim_client_and_none_without(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    with_url = Settings.model_validate(
        {
            "database_url": "sqlite://:memory:",
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "127.0.0.1/32",
            "gateway_url": "http://gateway.test",
            "gateway_actor": "claims@example.test",
        }
    )

    app = create_app(with_url)
    assert isinstance(app.state.copy_claims, GatewayCopyClaims)
    await app.state.copy_claims.aclose()

    monkeypatch.delenv("SCOREBOARD_GATEWAY_URL", raising=False)
    assert create_app(_settings()).state.copy_claims is None


@pytest.mark.asyncio
async def test_delete_scores_makes_no_gateway_call(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCOREBOARD_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setenv("SCOREBOARD_GATEWAY_ACTOR", "claims@example.test")
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    outcome = await ScoreStore().submit(
        ScoreSubmission.model_validate({**_payload(), "submitted_by": ALICE})
    )
    claim_calls: list[str] = []
    send_calls: list[httpx.Request] = []

    async def claim_recorder(self: GatewayCopyClaims, copy_id: str) -> ClaimResult:
        claim_calls.append(copy_id)
        return ClaimResult.CLAIMED

    async def send_recorder(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> None:
        send_calls.append(request)
        raise AssertionError("no HTTP call")

    monkeypatch.setattr(GatewayCopyClaims, "claim", claim_recorder)
    monkeypatch.setattr(httpx.AsyncClient, "send", send_recorder)
    score_id = uuid.UUID(str(outcome.score.id))

    selection = await delete_scores("hle", score_ids=[score_id], expected=1)
    deleted = await delete_scores(
        "hle", score_ids=[score_id], expected=1, confirmed=True, expected_sha256=selection.sha256()
    )

    assert deleted.deleted is True
    assert await Score.all().count() == 0
    assert claim_calls == []
    assert send_calls == []


def test_the_lifespan_closes_the_claim_client_before_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    fake = FakeClaims(events)
    original_close = main_module.close_db

    async def recorded_close() -> None:
        events.append("database closed")
        await original_close()

    monkeypatch.setattr(main_module, "close_db", recorded_close)
    settings = Settings(database_url=f"sqlite://{tmp_path / 'scoreboard.sqlite3'}", cors_origins=[])

    with TestClient(create_app(settings, copy_claims=fake)) as http:
        assert http.get("/healthz").status_code == 200

    assert events == ["client closed", "database closed"]
    assert fake.calls == []


@pytest.mark.asyncio
async def test_the_openapi_text_names_the_new_refusals_and_keeps_the_503_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = create_app(_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        doc = (await http.get("/openapi.json")).json()
    post = doc["paths"]["/v1/scores"]["post"]["responses"]

    assert "frozen_copy_expired" in post["422"]["description"]
    assert "frozen_copy_unavailable" in post["422"]["description"]
    assert "frozen_copy_check_unavailable" in post["503"]["description"]
    ref = post["503"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/MessageErrorResponse")
