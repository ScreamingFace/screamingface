"""The submit claims the frozen copy before the store (OME-1947; prd/score-claim.md K-9 to K-16,
K-23, K-24, K-35).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.core.copy_claims import ClaimResult
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.store import ScoreStore

ALICE = "alice@example.test"
BOB = "bob@example.test"
COPY = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"
DIGEST = "a" * 64
UNCAPTURED: dict[str, Any] = {"capture_status": None, "frozen_copy_id": None, "case_digest": None}

# INVARIANT: the three texts are copied from contracts.md K5. Do not import them from the route.
EXPIRED_TEXT = (
    "the pinned cache of this run expired: no score used it in its retention period. Run the "
    "evaluation again with capture=True to submit a reproducible score."
)
UNAVAILABLE_TEXT = (
    "the pinned cache of this run is not available: the run did not seal it, or this gateway "
    "does not hold it. Run the evaluation again and submit the new result."
)
CHECK_TEXT = "the pinned cache of this run could not be checked. Try again."


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "benchmark_revision": "rev-1",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.75,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
        "capture_status": "complete",
        "frozen_copy_id": COPY,
        "answer_seed": 42,
        "case_digest": DIGEST,
    }
    payload.update(overrides)
    return payload


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


async def _post(
    http: AsyncClient, owner: str = ALICE, headers: dict[str, str] | None = None, **overrides: Any
) -> Any:
    return await http.post(
        "/v1/scores", json=_payload(**overrides), headers={**_as(owner), **(headers or {})}
    )


class FakeClaims:
    def __init__(self, order: list[str]) -> None:
        self.result = ClaimResult.CLAIMED
        self.calls: list[str] = []
        self.order = order

    async def claim(self, copy_id: str) -> ClaimResult:
        self.calls.append(copy_id)
        self.order.append("claim")
        return self.result

    async def aclose(self) -> None:
        self.order.append("client closed")


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "database_url": "sqlite://:memory:",
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "127.0.0.1/32",
        }
    )


@pytest.fixture
def order() -> list[str]:
    return []


@pytest.fixture
def claims(order: list[str]) -> FakeClaims:
    return FakeClaims(order)


@pytest.fixture
def record_store(monkeypatch: pytest.MonkeyPatch, order: list[str]) -> None:
    original = ScoreStore.submit

    async def recorded(self: ScoreStore, *args: Any, **kwargs: Any) -> Any:
        order.append("store")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ScoreStore, "submit", recorded)


@pytest_asyncio.fixture
async def client(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch, claims: FakeClaims, record_store: None
) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = create_app(_settings(), copy_claims=claims)
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def plain(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[FastAPI, AsyncClient], None]:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    monkeypatch.delenv("SCOREBOARD_GATEWAY_URL", raising=False)
    app = create_app(_settings())
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield app, http


@pytest.mark.asyncio
async def test_with_no_gateway_url_a_submit_with_a_copy_is_stored_and_makes_no_http_call(
    plain: tuple[FastAPI, AsyncClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, http = plain
    sent: list[httpx.Request] = []

    async def recorder(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> None:
        sent.append(request)
        raise AssertionError("no HTTP call")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", recorder)
    response = await _post(http)

    assert response.status_code == 201
    assert sent == []
    assert app.state.copy_claims is None
    assert await Score.filter(frozen_copy_id=COPY).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [ClaimResult.CLAIMED, ClaimResult.ALREADY])
async def test_a_kept_copy_is_claimed_before_the_store(
    client: AsyncClient, claims: FakeClaims, order: list[str], result: ClaimResult
) -> None:
    claims.result = result

    response = await _post(client)

    assert response.status_code == 201
    assert order == ["claim", "store"]
    assert claims.calls == [COPY]


@pytest.mark.asyncio
async def test_an_expired_copy_is_refused_with_422_and_nothing_is_stored(
    client: AsyncClient, claims: FakeClaims, order: list[str]
) -> None:
    claims.result = ClaimResult.EXPIRED

    response = await _post(client)

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "frozen_copy_expired", "message": EXPIRED_TEXT}
    assert order == ["claim"]
    assert await Score.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result", [ClaimResult.NOT_SEALED, ClaimResult.ABANDONED, ClaimResult.NOT_FOUND]
)
async def test_an_unavailable_copy_is_refused_with_422_and_nothing_is_stored(
    client: AsyncClient, claims: FakeClaims, order: list[str], result: ClaimResult
) -> None:
    claims.result = result

    response = await _post(client)

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "frozen_copy_unavailable",
        "message": UNAVAILABLE_TEXT,
    }
    assert order == ["claim"]
    assert await Score.all().count() == 0


@pytest.mark.asyncio
async def test_no_answer_from_the_gateway_is_a_503_with_retry_after(
    client: AsyncClient, claims: FakeClaims, order: list[str]
) -> None:
    claims.result = ClaimResult.UNAVAILABLE

    response = await _post(client)

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "frozen_copy_check_unavailable",
        "message": CHECK_TEXT,
    }
    assert response.headers["retry-after"] == "5"
    assert order == ["claim"]
    assert await Score.all().count() == 0


@pytest.mark.asyncio
async def test_a_submit_with_no_copy_makes_no_claim(
    client: AsyncClient, claims: FakeClaims, order: list[str]
) -> None:
    response = await _post(client, **UNCAPTURED)

    assert response.status_code == 201
    assert claims.calls == []
    assert order == ["store"]


@pytest.mark.asyncio
async def test_a_store_refusal_after_a_claim_makes_no_second_call(
    client: AsyncClient, claims: FakeClaims
) -> None:
    first = await _post(client)
    assert first.status_code == 201
    claims.calls.clear()
    claims.result = ClaimResult.ALREADY

    second = await _post(client, owner=BOB, spec_id="spec-2")

    assert second.status_code == 422
    assert second.json()["detail"]["code"] == "frozen_copy_claimed"
    assert claims.calls == [COPY]
    assert await Score.all().count() == 1


@pytest.mark.asyncio
async def test_a_repeat_with_the_same_idempotency_key_claims_again(
    client: AsyncClient, claims: FakeClaims
) -> None:
    key = {"Idempotency-Key": "repeat-key"}

    first = await _post(client, headers=key)
    second = await _post(client, headers=key)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert claims.calls == [COPY, COPY]


@pytest.mark.asyncio
async def test_a_repeat_whose_copy_is_no_longer_sealed_is_refused_and_the_row_is_unchanged(
    client: AsyncClient, claims: FakeClaims
) -> None:
    key = {"Idempotency-Key": "sealed-key"}
    first = await _post(client, headers=key)
    assert first.status_code == 201
    before = (await Score.filter(id=first.json()["id"]).values())[0]
    claims.result = ClaimResult.NOT_SEALED

    second = await _post(client, headers=key)

    assert second.status_code == 422
    assert second.json()["detail"]["code"] == "frozen_copy_unavailable"
    after = (await Score.filter(id=first.json()["id"]).values())[0]
    assert after == before
    assert await Score.all().count() == 1


@pytest.mark.asyncio
async def test_a_refill_of_a_copy_that_is_not_sealed_keeps_the_field_empty(
    client: AsyncClient, claims: FakeClaims, order: list[str]
) -> None:
    created = await _post(client, **UNCAPTURED)
    assert created.status_code == 201
    assert claims.calls == []
    claims.result = ClaimResult.NOT_SEALED

    refill = await _post(client)

    assert refill.status_code == 422
    assert refill.json()["detail"]["code"] == "frozen_copy_unavailable"
    stored = await Score.get(id=created.json()["id"])
    assert stored.frozen_copy_id is None
    assert claims.calls == [COPY]
    assert order == ["store", "claim"]


@pytest.mark.asyncio
async def test_with_no_gateway_url_a_warning_names_the_copy(
    plain: tuple[FastAPI, AsyncClient], caplog: pytest.LogCaptureFixture
) -> None:
    _, http = plain

    with caplog.at_level(logging.WARNING, logger="scoreboard"):
        response = await _post(http)

    assert response.status_code == 201
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and COPY in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "no claim" in warnings[0]
    assert "no gateway URL" in warnings[0]


@pytest.mark.asyncio
async def test_a_refused_claim_logs_the_result_and_the_copy_but_no_email(
    client: AsyncClient, claims: FakeClaims, caplog: pytest.LogCaptureFixture
) -> None:
    claims.result = ClaimResult.NOT_SEALED

    with caplog.at_level(logging.INFO, logger="scoreboard"):
        response = await _post(client, owner=ALICE)

    assert response.status_code == 422
    refused = [
        r
        for r in caplog.records
        if r.name == "scoreboard.routes.copy_claim" and r.levelno == logging.WARNING
    ]
    assert len(refused) == 1
    assert "not_sealed" in refused[0].getMessage()
    assert COPY in refused[0].getMessage()
    assert all(ALICE not in r.getMessage() for r in caplog.records)
