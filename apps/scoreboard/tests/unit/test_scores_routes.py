from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise.exceptions import IntegrityError, OperationalError

from scoreboard.config import AuthMode, Settings
from scoreboard.main import create_app
from scoreboard.routes.scores import MISSING_IDENTITY_DETAIL, identity_is_verified
from scoreboard.scores.models import Benchmark, IdempotencyKey, Score
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio


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
    # WHY monkeypatch FORWARDED_ALLOW_IPS explicitly, not left at ambient/unset env: unset
    # falls back to uvicorn's own default "127.0.0.1" (see main.py), which is the EXACT SAME
    # address as this fixture's allowed_networks below — chosen because ASGITransport's default
    # fake peer is ("127.0.0.1", 123). create_app's overlap guard now refuses exactly that
    # combination (FORWARDED_ALLOW_IPS overlapping allowed_networks), so this fixture must pin
    # FORWARDED_ALLOW_IPS to something genuinely disjoint instead of relying on the implicit
    # uvicorn default no longer being safe to assume here.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    # model_validate, not the constructor: allowed_networks arrives as a comma-separated
    # STRING (as the environment supplies it) and is parsed into networks by the
    # mode="before" validator — the behavior under test, same idiom aigateway's own
    # allowed_networks tests use.
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


@pytest_asyncio.fixture
async def untrusted_peer_score_client(
    app_with_cloudflare_auth: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    # A peer address deliberately outside app_with_cloudflare_auth's allowed_networks
    # (127.0.0.1/32), to exercise the 403 "untrusted peer" path.
    async with AsyncClient(
        transport=ASGITransport(app=app_with_cloudflare_auth, client=("203.0.113.5", 443)),
        base_url="http://test",
    ) as client:
        yield client


async def test_post_score_creates_new_row_201(score_client: AsyncClient) -> None:
    response = await score_client.post("/v1/scores", json=_valid_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["benchmark_id"] == "hle"
    assert body["spec_id"] == "spec-1"
    assert body["submitted_at"]
    # OME-820: verified defaults to True as a placeholder that asserts NOTHING —
    # nothing re-runs submissions and nothing attests where a run executed. The
    # False case stays covered by the explicit-False row test.
    assert body["verified_by_screamingface"] is True


async def test_post_score_without_idempotency_key_dedupes_identical_recipe(
    score_client: AsyncClient,
) -> None:
    # WHY: dedup is server-enforced by recipe content hash, independent of any
    # client-supplied header — a resubmitted identical recipe returns the existing
    # row instead of creating a duplicate (OME-391 / C28).
    first = await score_client.post(
        "/v1/scores", json=_valid_payload(score=0.5, correct_questions=2)
    )
    second = await score_client.post(
        "/v1/scores", json=_valid_payload(score=0.5, correct_questions=2)
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


async def test_post_score_with_live_idempotency_key_returns_200(
    score_client: AsyncClient,
) -> None:
    headers = {"Idempotency-Key": "repeat-key"}
    first = await score_client.post("/v1/scores", json=_valid_payload(), headers=headers)
    second = await score_client.post("/v1/scores", json=_valid_payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["submitted_at"] == first.json()["submitted_at"]


async def test_post_score_with_expired_idempotency_key_creates_new_row(
    score_client: AsyncClient,
) -> None:
    headers = {"Idempotency-Key": "expired-key"}
    first = await score_client.post("/v1/scores", json=_valid_payload(), headers=headers)
    await IdempotencyKey.filter(key="expired-key").update(
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert await ScoreStore().get_by_idempotency_key("expired-key") is None

    # A genuinely different recipe (not just a different key) — proves the expired
    # key no longer blocks resubmission, without colliding with the unrelated
    # content-hash dedup guard this test isn't exercising.
    second = await score_client.post(
        "/v1/scores",
        json=_valid_payload(score=1.0, correct_questions=4),
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]


async def test_post_score_never_cross_checks_score_against_counts(
    score_client: AsyncClient,
) -> None:
    # INVARIANT (OME-866): the Engine benchmark is the sole scoring authority — the
    # route's old ±0.01 accuracy-vs-correct/total tolerance check was deleted, not
    # replaced. A score that disagrees with the optional binary-era counts is stored
    # exactly as submitted (the pre-OME-866 version of this test asserted 400 here).
    response = await score_client.post(
        "/v1/scores",
        json=_valid_payload(score=0.5, total_questions=100, correct_questions=10),
    )

    assert response.status_code == 201
    assert response.json()["score"] == 0.5


async def test_post_score_unknown_benchmark_id_returns_404(score_client: AsyncClient) -> None:
    response = await score_client.post(
        "/v1/scores",
        json=_valid_payload(benchmark_id="missing"),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["field"] == "benchmark_id"


async def test_post_score_future_version_returns_422(score_client: AsyncClient) -> None:
    response = await score_client.post("/v1/scores", json=_valid_payload(version=2))

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "version"]


@pytest.mark.parametrize("run_cost_usd", [None, pytest.param("omitted", id="omitted")])
async def test_post_score_requires_a_non_null_run_cost(
    score_client: AsyncClient,
    run_cost_usd: str | None,
) -> None:
    payload = _valid_payload(run_cost_usd=run_cost_usd)
    if run_cost_usd == "omitted":
        payload.pop("run_cost_usd")

    response = await score_client.post("/v1/scores", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "run_cost_usd"]


async def test_post_score_url4_expression_too_long_returns_422(
    score_client: AsyncClient,
) -> None:
    response = await score_client.post(
        "/v1/scores",
        json=_valid_payload(url4_expression="x" * 32_001),
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "url4_expression"]


async def test_post_score_non_finite_score_returns_422(score_client: AsyncClient) -> None:
    # WHY the string: JSON itself cannot carry NaN, so the boundary the route defends
    # is a coercible-looking value that is not a strict finite number (OME-866).
    response = await score_client.post("/v1/scores", json=_valid_payload(score="NaN"))

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "score"]


async def test_post_score_store_unavailable_returns_503(
    score_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_operational_error(*args: object, **kwargs: object) -> bool:
        raise OperationalError("database is locked")

    monkeypatch.setattr(Benchmark, "exists", raise_operational_error)

    response = await score_client.post("/v1/scores", json=_valid_payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}


async def test_get_score_by_id_returns_row(score_client: AsyncClient) -> None:
    created = await score_client.post("/v1/scores", json=_valid_payload())

    response = await score_client.get(f"/v1/scores/{created.json()['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]
    assert response.json()["benchmark_id"] == "hle"


async def test_get_score_unknown_id_returns_404(score_client: AsyncClient) -> None:
    response = await score_client.get(f"/v1/scores/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "score not found"}


async def test_post_score_default_auth_mode_disabled_trusts_free_text(
    score_client: AsyncClient,
) -> None:
    # WHY: SCOREBOARD_AUTH_MODE unset (local dev, and every fixture above) must stay a
    # true no-op — the client-supplied submitted_by is trusted unchanged (OME-404's
    # documented default, so no existing deployment/test breaks from this change).
    response = await score_client.post("/v1/scores", json=_valid_payload(submitted_by="tester"))

    assert response.status_code == 201
    assert response.json()["submitted_by"] == "tester"


async def test_post_score_with_identity_header_stores_header_email(
    cloudflare_score_client: AsyncClient,
) -> None:
    response = await cloudflare_score_client.post(
        "/v1/scores",
        json=_valid_payload(submitted_by="someone-else"),
        headers={"X-User-Email": "researcher@example.test"},
    )

    assert response.status_code == 201
    # WHY: the header always wins over whatever the request body claims — a caller
    # cannot submit under another person's name. The body claimed "someone-else", so
    # seeing the header's identity here still proves that.
    #
    # OME-834: the published form is the local part only — the read API is public and
    # unauthenticated, so the domain is withheld to keep addresses out of scrapers.
    assert response.json()["submitted_by"] == "researcher"
    # ...and the row keeps the full address, which is what this test's name claims and
    # the response alone never verified. OpenMined must still be able to contact and
    # audit the verified identity behind a score (OME-404).
    stored = await Score.get(id=response.json()["id"])
    assert stored.submitted_by == "researcher@example.test"


async def test_post_score_missing_identity_header_returns_401(
    cloudflare_score_client: AsyncClient,
) -> None:
    response = await cloudflare_score_client.post("/v1/scores", json=_valid_payload())

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_IDENTITY_DETAIL}


async def test_post_score_blank_identity_header_returns_401(
    cloudflare_score_client: AsyncClient,
) -> None:
    response = await cloudflare_score_client.post(
        "/v1/scores",
        json=_valid_payload(),
        headers={"X-User-Email": "   "},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_IDENTITY_DETAIL}


async def test_post_score_missing_identity_header_wins_over_bad_accuracy(
    cloudflare_score_client: AsyncClient,
) -> None:
    # WHY: pins the exact regression round-1 self-review found and fixed — identity must be
    # checked before business-rule validation, so an unauthenticated caller never learns
    # anything about why its payload would otherwise be rejected. A future reorder that moves
    # the accuracy check back above _resolve_submitter must fail this test (400, not 401).
    response = await cloudflare_score_client.post(
        "/v1/scores",
        json=_valid_payload(score=0.5, total_questions=100, correct_questions=10),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_IDENTITY_DETAIL}


async def test_post_score_untrusted_peer_wins_over_unknown_benchmark(
    untrusted_peer_score_client: AsyncClient,
) -> None:
    # WHY: same regression class as above, for the 403/peer-check path against the
    # benchmark-existence check instead of the accuracy check.
    response = await untrusted_peer_score_client.post(
        "/v1/scores",
        json=_valid_payload(benchmark_id="missing"),
        headers={"X-User-Email": "researcher@example.test"},
    )

    assert response.status_code == 403


async def test_get_score_remains_public_when_cloudflare_headers_configured(
    cloudflare_score_client: AsyncClient,
) -> None:
    # WHY: GET has no auth wiring at all — pinned so a future refactor that shares a
    # dependency between routes can't silently make score reads non-public.
    created = await cloudflare_score_client.post(
        "/v1/scores",
        json=_valid_payload(),
        headers={"X-User-Email": "researcher@example.test"},
    )

    response = await cloudflare_score_client.get(f"/v1/scores/{created.json()['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]


async def test_post_score_untrusted_peer_returns_403_even_with_valid_header(
    untrusted_peer_score_client: AsyncClient,
) -> None:
    response = await untrusted_peer_score_client.post(
        "/v1/scores",
        json=_valid_payload(),
        headers={"X-User-Email": "researcher@example.test"},
    )

    assert response.status_code == 403


async def test_post_score_forwarded_for_header_never_substitutes_for_real_peer(
    untrusted_peer_score_client: AsyncClient,
) -> None:
    # WHY: X-Forwarded-For is exactly as forgeable as X-User-Email itself — trusting it
    # to decide whether to trust the identity header would be circular.
    response = await untrusted_peer_score_client.post(
        "/v1/scores",
        json=_valid_payload(),
        headers={"X-User-Email": "researcher@example.test", "X-Forwarded-For": "127.0.0.1"},
    )

    assert response.status_code == 403


async def test_openapi_schema_includes_new_endpoints(score_client: AsyncClient) -> None:
    response = await score_client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    post_score = paths["/v1/scores"]["post"]
    get_score = paths["/v1/scores/{score_id}"]["get"]

    assert post_score["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ScoreSubmission",
    )
    assert "run_cost_usd" in response.json()["components"]["schemas"]["ScoreSubmission"]["required"]
    assert post_score["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ScoreSchema",
    )
    assert post_score["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ScoreSchema",
    )
    assert post_score["responses"]["400"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/FieldErrorResponse",
    )
    assert post_score["responses"]["401"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MessageErrorResponse",
    )
    assert post_score["responses"]["403"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MessageErrorResponse",
    )
    assert post_score["responses"]["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/FieldErrorResponse",
    )
    assert post_score["responses"]["503"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MessageErrorResponse",
    )
    assert get_score["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ScoreSchema",
    )
    assert get_score["responses"]["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MessageErrorResponse",
    )
    assert get_score["responses"]["503"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MessageErrorResponse",
    )


# --- OME-894: a private benchmark's scores are not readable by UUID --------------------------
# The four leaderboard read paths were secured first; this one was missed. A score UUID is handed
# out by the submission response and by per-spec history, so `GET /v1/scores/{id}` was a fifth
# score-bearing path that returned a private submission's url4_expression and metadata to anyone
# holding the id. Found in review of PR #719.

PRIVATE_BENCHMARK = "healthbench-worst30"


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


async def test_get_score_on_a_private_benchmark_is_404_for_an_anonymous_caller(
    cloudflare_score_client: AsyncClient,
) -> None:
    score_id = await _private_score(cloudflare_score_client, "alice@example.test")

    response = await cloudflare_score_client.get(f"/v1/scores/{score_id}")

    # INVARIANT: the SAME 404 an unknown id gets. Holding a real id must not be confirmable.
    assert response.status_code == 404
    assert response.json() == {"detail": "score not found"}


async def test_get_score_on_a_private_benchmark_is_404_for_another_participant(
    cloudflare_score_client: AsyncClient,
) -> None:
    score_id = await _private_score(cloudflare_score_client, "alice@example.test")

    response = await cloudflare_score_client.get(
        f"/v1/scores/{score_id}", headers={"X-User-Email": "bob@example.test"}
    )

    assert response.status_code == 404


async def test_get_score_on_a_private_benchmark_is_served_to_its_own_submitter(
    cloudflare_score_client: AsyncClient,
) -> None:
    score_id = await _private_score(cloudflare_score_client, "alice@example.test")

    response = await cloudflare_score_client.get(
        f"/v1/scores/{score_id}", headers={"X-User-Email": "alice@example.test"}
    )

    assert response.status_code == 200
    assert response.json()["id"] == score_id


async def test_get_score_on_a_public_benchmark_stays_anonymous(
    score_client: AsyncClient,
) -> None:
    # The regression guard: securing the private path must not close the public one.
    created = await score_client.post("/v1/scores", json=_valid_payload())

    response = await score_client.get(f"/v1/scores/{created.json()['id']}")

    assert response.status_code == 200


# --- review round 3: a private board cannot accept writes without verified identity -----------
# In auth_mode=disabled `_resolve_submitter` trusts the body's `submitted_by`. Combined with
# per-submitter dedup that becomes a READ primitive: forge a participant's address, submit a
# matching recipe, and the dedup path returns their stored row — url4, metadata and id included.
# Reproduced before fixing. Reads already fail closed under `disabled` (OME-894 D2); writes now
# match, so a private board is inert in both directions until identity is real.


async def test_a_private_benchmark_refuses_submissions_when_auth_is_disabled(
    score_client: AsyncClient,
) -> None:
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    payload = _valid_payload()
    payload["benchmark_id"] = "private-x"

    response = await score_client.post("/v1/scores", json=payload)

    assert response.status_code == 403


async def test_the_refusal_happens_before_any_dedup_lookup(
    score_client: AsyncClient,
) -> None:
    # INVARIANT: the refusal must precede the store, or the forged request still learns whether a
    # matching row exists from the response it gets back.
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    victim = _valid_payload()
    victim["benchmark_id"] = "private-x"
    victim["submitted_by"] = "alice@example.test"
    victim["metadata"] = {"notes": "alice internal"}
    await Score.create(
        benchmark_id="private-x",
        spec_id=victim["spec_id"],
        url4_expression=victim["url4_expression"],
        submitted_by="alice@example.test",
        score=victim["score"],
        total_questions=victim["total_questions"],
        ran_with_providers=victim["ran_with_providers"],
        metadata={"notes": "alice internal"},
    )

    forged = await score_client.post("/v1/scores", json=victim)

    assert forged.status_code == 403
    assert "alice internal" not in forged.text


async def test_a_public_benchmark_still_accepts_submissions_when_auth_is_disabled(
    score_client: AsyncClient,
) -> None:
    # The regression guard: closing the private write path must not close the public one, which
    # is how every existing deployment submits today.
    response = await score_client.post("/v1/scores", json=_valid_payload())

    assert response.status_code == 201


async def test_a_private_benchmark_accepts_submissions_with_verified_identity(
    cloudflare_score_client: AsyncClient,
) -> None:
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    payload = _valid_payload()
    payload["benchmark_id"] = "private-x"

    response = await cloudflare_score_client.post(
        "/v1/scores", json=payload, headers={"X-User-Email": "alice@example.test"}
    )

    assert response.status_code == 201


async def test_a_database_failure_on_the_visibility_lookup_is_a_503(
    score_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: this endpoint documents 503 for database failures. The OME-894 visibility lookup
    # is a SECOND read after the score fetch, so a transient disconnect between the two escaped
    # the existing handler as an unhandled 500 (found in review of PR #719). Both reads belong
    # inside one error boundary.
    created = await score_client.post("/v1/scores", json=_valid_payload())

    async def _disconnected(*args: object, **kwargs: object) -> None:
        raise OperationalError("connection lost")

    monkeypatch.setattr("scoreboard.routes.scores.Benchmark.get_or_none", _disconnected)

    response = await score_client.get(f"/v1/scores/{created.json()['id']}")

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}


# --- review round 6: the two 404s must be indistinguishable ---------------------------------
# `get_score` raises the same status and detail for an unknown id and for a private score the
# caller may not read, and the invariant comment says so. The private refusal carried
# `PRIVATE_CACHE_HEADERS` and the unknown-id 404 did not, so the response headers alone
# confirmed that a real private score id existed. Found in review of PR #719.


async def test_the_unknown_id_404_is_indistinguishable_from_the_private_refusal(
    cloudflare_score_client: AsyncClient,
) -> None:
    score_id = await _private_score(cloudflare_score_client, "alice@example.test")

    refused = await cloudflare_score_client.get(
        f"/v1/scores/{score_id}", headers={"X-User-Email": "bob@example.test"}
    )
    unknown = await cloudflare_score_client.get(
        f"/v1/scores/{uuid4()}", headers={"X-User-Email": "bob@example.test"}
    )

    assert refused.status_code == unknown.status_code == 404
    assert refused.json() == unknown.json()
    # INVARIANT: the discriminator must not survive in the headers either.
    assert refused.headers.get("cache-control") == unknown.headers.get("cache-control")
    assert refused.headers.get("vary") == unknown.headers.get("vary")


async def test_an_unknown_score_id_is_not_shared_cacheable(
    cloudflare_score_client: AsyncClient,
) -> None:
    # Asserted on its own so the pair above cannot pass by BOTH responses losing the policy.
    response = await cloudflare_score_client.get(f"/v1/scores/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"


# --- review round 17: one authority for visibility, read where it governs persistence --------
# The route read visibility to decide whether to refuse an unverified write, and the store read it
# AGAIN to decide per-submitter semantics. The write is governed by the SECOND read, so flipping a
# board public -> private between them — which the seed job does on every deploy — let the guard
# pass on stale data and persisted an unverified claim on a private board. Found in review of #719.


async def test_a_visibility_flip_between_the_reads_cannot_persist_an_unverified_write(
    score_client: AsyncClient,
) -> None:
    # INVARIANT: there is no window. A third read earlier in the route would not close this; the
    # refusal has to be taken at the read that decides persistence.
    await Benchmark.create(id="race-x", display_name="Race", visibility="public")
    real_submit = ScoreStore.submit

    async def _flip_then_submit(self, submission, idempotency_key=None, **kwargs):  # type: ignore[no-untyped-def]
        # Stands in for the seed job landing mid-request.
        await Benchmark.filter(id="race-x").update(visibility="private")
        return await real_submit(self, submission, idempotency_key=idempotency_key, **kwargs)

    payload = _valid_payload()
    payload["benchmark_id"] = "race-x"
    payload["submitted_by"] = "victim@example.test"
    payload["metadata"] = {"attacker": "controlled"}

    ScoreStore.submit = _flip_then_submit  # type: ignore[method-assign]
    try:
        response = await score_client.post("/v1/scores", json=payload)
    finally:
        ScoreStore.submit = real_submit  # type: ignore[method-assign]

    assert response.status_code == 403, response.text
    assert await Score.get_or_none(spec_id=payload["spec_id"]) is None, (
        "an unverified claim was persisted on a board that is private by the time it was written"
    )


def test_an_unrecognised_auth_mode_does_not_count_as_verified() -> None:
    # INVARIANT: the route derives `identity_verified` from an ALLOWLIST of modes that actually
    # verify, not from "anything but disabled". A third mode added later would otherwise be treated
    # as verifying by default — the fail-open direction, on the decision that governs private
    # writes. Passing a mode outside the Literal is the point: it stands in for that future value.
    assert identity_is_verified("cloudflare_headers") is True
    assert identity_is_verified("disabled") is False
    assert identity_is_verified(cast(AuthMode, "some-future-sso-mode")) is False


async def test_a_visibility_flip_mid_flight_is_a_409_not_a_500(
    score_client: AsyncClient,
) -> None:
    # INVARIANT: refusing a request whose rules changed underneath it is a CONFLICT, not a server
    # error. Nothing is wrong with the request; a retry gets one consistent view. Surfacing it as a
    # 500 would read as a bug in the board and hide a correct refusal.
    await Benchmark.create(id="flip-x", display_name="Flip", visibility="public")
    real = ScoreStore._resolve_existing

    async def _flip(self, idempotency_key, content_hash):  # type: ignore[no-untyped-def]
        await Benchmark.filter(id="flip-x").update(visibility="private")
        return await real(self, idempotency_key, content_hash)

    payload = _valid_payload()
    payload["benchmark_id"] = "flip-x"

    ScoreStore._resolve_existing = _flip  # type: ignore[method-assign]
    try:
        response = await score_client.post("/v1/scores", json=payload)
    finally:
        ScoreStore._resolve_existing = real  # type: ignore[method-assign]

    assert response.status_code == 409, response.text
    assert await Score.get_or_none(spec_id=payload["spec_id"]) is None


async def test_a_flip_after_the_visibility_read_withholds_the_score(
    score_client: AsyncClient,
) -> None:
    # The window on this route is read -> serialise rather than read -> query: nothing else is
    # fetched after the benchmark read. Narrower than the leaderboard's, closed the same way, so
    # every score-bearing read answers from one view of `visibility` (review of PR #719).
    await Benchmark.create(id="late-x", display_name="Late", visibility="public")
    payload = _valid_payload()
    payload["benchmark_id"] = "late-x"
    created = await score_client.post("/v1/scores", json=payload)
    assert created.status_code == 201
    score_id = created.json()["id"]

    real = Benchmark.get_or_none

    async def _flip_after_read(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = await real(*args, **kwargs)
        await Benchmark.filter(id="late-x").update(visibility="private")
        return result

    Benchmark.get_or_none = _flip_after_read  # type: ignore[method-assign]
    try:
        response = await score_client.get(f"/v1/scores/{score_id}")
    finally:
        Benchmark.get_or_none = real  # type: ignore[method-assign]

    assert response.status_code == 404, response.text
    assert response.headers["cache-control"] == "private, no-store"


def _lose_the_race_and_flip(benchmark_id: str) -> tuple[object, object, dict[str, int]]:
    """Blind the precheck, flip the board on the retry lookup, and fail the first insert."""
    real_resolve = ScoreStore._resolve_existing
    real_create = Score.create
    seen = {"resolves": 0, "raises": 0}

    async def _resolve(self, idempotency_key, content_hash):  # type: ignore[no-untyped-def]
        seen["resolves"] += 1
        if seen["resolves"] == 1:
            return None
        await Benchmark.filter(id=benchmark_id).update(visibility="private")
        return await real_resolve(self, idempotency_key, content_hash)

    async def _create(**kwargs):  # type: ignore[no-untyped-def]
        if not seen["raises"]:
            seen["raises"] += 1
            raise IntegrityError("simulated concurrent insert")
        return await real_create(**kwargs)

    return _resolve, _create, seen


async def test_a_lost_race_after_a_flip_is_a_conflict_not_a_store_outage(
    score_client: AsyncClient,
) -> None:
    # INVARIANT: a concurrency conflict on a board that changed underneath the request is a 409.
    #
    # `IntegrityError` SUBCLASSES `OperationalError`, so re-raising it was caught by the route's
    # store-unavailable handler and answered `503 score store unavailable` — telling the client the
    # database is down when the board had merely changed, and masking a conflict as an outage. The
    # privacy gate is what made this reachable: after a flip the winner's row is no longer readable,
    # so nothing resolves and the bare `raise` runs (review of PR #719).
    await Benchmark.create(id="lost-x", display_name="Lost", visibility="public")
    payload = _valid_payload()
    payload["benchmark_id"] = "lost-x"
    assert (await score_client.post("/v1/scores", json=payload)).status_code == 201

    real_resolve, real_create = ScoreStore._resolve_existing, Score.create
    resolve, create, seen = _lose_the_race_and_flip("lost-x")
    ScoreStore._resolve_existing, Score.create = resolve, create  # type: ignore[method-assign]
    try:
        response = await score_client.post(
            "/v1/scores", json=dict(payload, spec_id="loser", submitted_by="bob@example.test")
        )
    finally:
        ScoreStore._resolve_existing = real_resolve  # type: ignore[method-assign]
        Score.create = real_create  # type: ignore[method-assign]

    assert seen["raises"], "the IntegrityError branch was never reached"
    assert response.status_code == 409, response.text
