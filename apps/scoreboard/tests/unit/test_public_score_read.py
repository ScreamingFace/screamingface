"""The anonymous read-only alias ``GET /v1/public/scores/{id}``.

FEATURE: the production Cloudflare Access application covers every ``/v1/scores`` subpath, so the
portal's anonymous spec page cannot call ``GET /v1/scores/{id}``. The alias serves the same body
from a path Access does not cover.

INVARIANT: the alias never reads the caller's identity. A private-board score is the same 404 for
every caller through it, the owner included, and that 404 is byte-identical to an unknown id.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise.exceptions import OperationalError

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

PRIVATE_BENCHMARK = "healthbench-worst30"
NOT_FOUND = {"detail": "score not found"}
PRIVATE_CACHE = "private, no-store"


def _alias(score_id: object) -> str:
    return f"/v1/public/scores/{score_id}"


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "submitted_by": "tester",
        "score": 0.75,
        "total_questions": 4,
        "correct_questions": 3,
        "ran_with_providers": ["openai"],
        "run_cost_usd": "1.250000",
        "run_cost_status": "complete",
        "ran_at_local": "2026-05-21T12:00:00+00:00",
        "client": {"name": "scoreboard-test", "version": "0.1.0", "platform": "test"},
        "metadata": {"source": "unit"},
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
async def score_client(app_with_benchmark: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app_with_benchmark),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def app_with_cloudflare_auth(tortoise_db: None, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # WHY monkeypatch FORWARDED_ALLOW_IPS explicitly: create_app's overlap guard refuses
    # FORWARDED_ALLOW_IPS overlapping allowed_networks, and the ASGI fake peer is 127.0.0.1.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    settings = Settings.model_validate(
        {
            "database_url": "sqlite://:memory:",
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "127.0.0.1/32",
        }
    )
    app = create_app(settings)
    await Benchmark.create(
        id="hle",
        display_name="Humanity's Last Exam",
        description="Fixture benchmark",
        dataset_url="https://example.test/hle.jsonl",
    )
    return app


@pytest_asyncio.fixture
async def cloudflare_score_client(
    app_with_cloudflare_auth: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    # WHY: httpx's ASGITransport reports a fixed peer, ("127.0.0.1", 123) by default —
    # matches the fixture's allowed_networks above so the trusted-peer path is exercised.
    async with AsyncClient(
        transport=ASGITransport(app=app_with_cloudflare_auth),
        base_url="http://test",
    ) as client:
        yield client


async def _public_score(client: AsyncClient, **overrides: Any) -> str:
    created = await client.post("/v1/scores", json=_valid_payload(**overrides))
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _private_score(client: AsyncClient, submitter: str) -> str:
    await Benchmark.create(
        id=PRIVATE_BENCHMARK,
        display_name="HealthBench Worst-30% Challenge",
        visibility="private",
    )
    payload = _valid_payload()
    payload["benchmark_id"] = PRIVATE_BENCHMARK
    created = await client.post("/v1/scores", json=payload, headers={"X-User-Email": submitter})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_public_read_serves_a_public_score_anonymously(score_client: AsyncClient) -> None:
    score_id = await _public_score(score_client)

    response = await score_client.get(_alias(score_id))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == score_id
    assert body["url4_expression"] == "url4://benchmark/spec-1"


async def test_public_read_body_equals_the_canonical_read(score_client: AsyncClient) -> None:
    score_id = await _public_score(score_client, paper_url="https://arxiv.org/abs/2610.01234")

    alias = await score_client.get(_alias(score_id))
    canonical = await score_client.get(f"/v1/scores/{score_id}")

    assert alias.status_code == canonical.status_code == 200
    assert alias.json() == canonical.json()


async def test_public_read_of_a_public_score_is_not_marked_private(
    score_client: AsyncClient,
) -> None:
    score_id = await _public_score(score_client)

    response = await score_client.get(_alias(score_id))

    assert response.status_code == 200
    # WHY: a public 200 is shareable; the private policy is for identity-scoped answers only.
    assert "cache-control" not in response.headers


async def test_public_read_carries_the_reproduction_count(
    score_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    score_id = await _public_score(score_client)

    async def fake(self: ScoreStore, score_id: object) -> tuple[int, datetime]:
        return 2, datetime(2026, 10, 6, 12, 30, tzinfo=UTC)

    monkeypatch.setattr(ScoreStore, "reproduction_aggregate", fake)

    response = await score_client.get(_alias(score_id))

    assert response.status_code == 200
    body = response.json()
    assert body["reproduction_count"] == 2
    assert body["last_reproduced_at"].startswith("2026-10-06T12:30:00")


async def test_public_read_unknown_id_is_the_private_404(score_client: AsyncClient) -> None:
    response = await score_client.get(_alias(uuid4()))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert response.headers["cache-control"] == PRIVATE_CACHE
    assert response.headers["vary"] == "X-User-Email, Origin"


async def test_public_read_hides_a_private_score_from_an_anonymous_caller(
    cloudflare_score_client: AsyncClient,
) -> None:
    score_id = await _private_score(cloudflare_score_client, "alice@example.test")

    response = await cloudflare_score_client.get(_alias(score_id))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert response.headers["cache-control"] == PRIVATE_CACHE


async def test_public_read_ignores_the_owner_identity(
    cloudflare_score_client: AsyncClient,
) -> None:
    score_id = await _private_score(cloudflare_score_client, "alice@example.test")
    owner = {"X-User-Email": "alice@example.test"}

    alias = await cloudflare_score_client.get(_alias(score_id), headers=owner)
    canonical = await cloudflare_score_client.get(f"/v1/scores/{score_id}", headers=owner)

    # INVARIANT: the alias never reads identity, so the owner gets the same refusal as anyone.
    assert alias.status_code == 404
    assert alias.json() == NOT_FOUND
    assert alias.headers["cache-control"] == PRIVATE_CACHE
    # The canonical owner read is unchanged.
    assert canonical.status_code == 200


async def test_public_read_private_refusal_is_indistinguishable_from_unknown(
    cloudflare_score_client: AsyncClient,
) -> None:
    score_id = await _private_score(cloudflare_score_client, "alice@example.test")
    bob = {"X-User-Email": "bob@example.test"}

    refused = await cloudflare_score_client.get(_alias(score_id), headers=bob)
    unknown = await cloudflare_score_client.get(_alias(uuid4()), headers=bob)

    assert refused.status_code == unknown.status_code == 404
    assert refused.json() == unknown.json()
    # WHY: the framework's own 404 is {"detail": "Not Found"}, so pin the app's refusal too.
    assert refused.json() == NOT_FOUND
    assert refused.headers["cache-control"] == PRIVATE_CACHE
    assert refused.headers.get("vary") == unknown.headers.get("vary")
    assert refused.headers.get("cache-control") == unknown.headers.get("cache-control")


async def test_public_read_refuses_a_board_that_turned_private_mid_read(
    score_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    score_id = await _public_score(score_client)

    async def turned(benchmark_id: str) -> bool:
        return True

    monkeypatch.setattr("scoreboard.routes.scores.turned_private", turned)

    response = await score_client.get(_alias(score_id))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert response.headers["cache-control"] == PRIVATE_CACHE


async def test_public_read_store_unavailable_is_503(
    score_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    score_id = await _public_score(score_client)

    async def unavailable(**kwargs: Any) -> None:
        raise OperationalError("database is locked")

    monkeypatch.setattr(Score, "get_or_none", unavailable)

    response = await score_client.get(_alias(score_id))

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}


async def test_public_read_rejects_a_non_uuid_id(score_client: AsyncClient) -> None:
    response = await score_client.get("/v1/public/scores/not-a-uuid")

    assert response.status_code == 422


async def test_public_path_is_read_only(score_client: AsyncClient) -> None:
    score_id = await _public_score(score_client)
    # WHY: pin the GET first, so this cannot pass while the route is missing and the
    # framework's own answer to POST and PATCH is the thing being observed.
    assert (await score_client.get(_alias(score_id))).status_code == 200

    posted = await score_client.post(_alias(score_id), json={})
    patched = await score_client.patch(_alias(score_id), json={})

    assert posted.status_code == 405
    assert patched.status_code == 405


async def test_openapi_documents_the_public_read(score_client: AsyncClient) -> None:
    response = await score_client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/v1/public/scores/{score_id}"]

    assert set(operation) == {"get"}
    get = operation["get"]
    assert get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ScoreSchema"
    )
    assert get["responses"]["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MessageErrorResponse"
    )
    assert get["responses"]["503"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MessageErrorResponse"
    )
