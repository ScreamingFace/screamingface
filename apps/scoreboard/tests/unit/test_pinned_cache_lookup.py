"""`GET /v1/public/scores/by-pinned-cache/{frozen_copy_id}` and one score per frozen copy.

Spec section 5.

FEATURE: the SDK's `evaluate(pinned_cache=...)` looks a published run up by its pinned cache (the
frozen copy) and replays it. The lookup is public, read-only, and answers the same 404 for an
unknown, malformed or private copy, so nobody learns that a private copy exists. A copy names at
most one score: a second claim is a 422 `frozen_copy_claimed`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise.exceptions import OperationalError

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes import scores as score_routes
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

ALICE = "alice@example.test"
BOB = "bob@example.test"
COPY = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"
OTHER_COPY = "ffeeddcc-bbaa-4998-8776-655443322110"
DIGEST = "a" * 64


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
    await Benchmark.create(id="secret", display_name="Private", visibility="private")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


async def _post(http: AsyncClient, owner: str = ALICE, **overrides: Any) -> Any:
    return await http.post("/v1/scores", json=_payload(**overrides), headers=_as(owner))


async def _lookup(http: AsyncClient, copy: str) -> Any:
    return await http.get(f"/v1/public/scores/by-pinned-cache/{copy}")


# --- the lookup ----------------------------------------------------------------------------------


async def test_a_public_captured_score_answers_what_a_replay_needs(client: AsyncClient) -> None:
    created = await _post(client)
    assert created.status_code == 201, created.text

    response = await _lookup(client, COPY)

    assert response.status_code == 200
    assert response.json() == {
        "score_id": created.json()["id"],
        "benchmark_id": "hle",
        "benchmark_revision": "rev-1",
        "url4_expression": "url4://benchmark/spec-1",
        "answer_seed": 42,
        "score": 0.75,
        "total_questions": 4,
        "case_digest": DIGEST,
        "capture_status": "complete",
    }


async def test_the_lookup_is_not_served_under_the_access_gated_scores_path(
    client: AsyncClient,
) -> None:
    # WHY: production Cloudflare Access gates every `/v1/scores` subpath (e003f254a), so an
    # anonymous replay must reach the lookup under `/v1/public`. The old path must not answer it.
    created = await _post(client)
    assert created.status_code == 201, created.text

    response = await client.get(f"/v1/scores/by-pinned-cache/{COPY}")

    assert response.status_code == 404
    assert (await _lookup(client, COPY)).status_code == 200


async def test_the_copy_id_is_read_in_its_canonical_form(client: AsyncClient) -> None:
    created = await _post(client)

    response = await _lookup(client, COPY.upper())

    assert response.status_code == 200
    assert response.json()["score_id"] == created.json()["id"]


async def test_unknown_malformed_and_private_copies_answer_the_same_404(
    client: AsyncClient,
) -> None:
    private = await _post(client, owner=BOB, benchmark_id="secret", frozen_copy_id=OTHER_COPY)
    assert private.status_code == 201, private.text

    answers = [
        await _lookup(client, "11111111-2222-4333-8444-555555555555"),
        await _lookup(client, "not-a-uuid"),
        await _lookup(client, OTHER_COPY),
    ]

    assert [answer.status_code for answer in answers] == [404, 404, 404]
    assert [answer.json() for answer in answers] == [{"detail": "score not found"}] * 3
    assert {answer.headers["cache-control"] for answer in answers} == {"private, no-store"}


async def test_a_board_that_turned_private_answers_the_same_404(client: AsyncClient) -> None:
    await _post(client)
    await Benchmark.filter(id="hle").update(visibility="private")

    response = await _lookup(client, COPY)

    assert response.status_code == 404
    assert response.json() == {"detail": "score not found"}


async def test_a_partial_capture_still_answers_with_its_status(client: AsyncClient) -> None:
    # The lookup reports; deciding whether to replay a `partial` copy is the SDK's call.
    await _post(client, capture_status="partial")

    response = await _lookup(client, COPY)

    assert response.status_code == 200
    assert response.json()["capture_status"] == "partial"


# --- one copy, one score --------------------------------------------------------------------------


def _claimed(response: Any) -> bool:
    return response.status_code == 422 and response.json()["detail"]["code"] == (
        "frozen_copy_claimed"
    )


async def test_a_second_score_naming_the_same_copy_is_refused(client: AsyncClient) -> None:
    first = await _post(client)

    second = await _post(client, owner=BOB, spec_id="spec-2")

    assert first.status_code == 201
    assert _claimed(second), second.text
    assert await Score.all().count() == 1


async def test_a_same_owner_resubmit_onto_the_same_row_is_accepted(client: AsyncClient) -> None:
    first = await _post(client)

    again = await _post(client)

    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]


async def test_a_resubmit_filling_a_copy_another_score_holds_is_refused(
    client: AsyncClient,
) -> None:
    await _post(client)
    uncaptured: dict[str, Any] = {
        "capture_status": None,
        "frozen_copy_id": None,
        "case_digest": None,
    }
    other = await _post(client, spec_id="spec-2", **uncaptured)
    assert other.status_code == 201, other.text

    refill = await _post(client, spec_id="spec-2")

    assert _claimed(refill), refill.text
    stored = await Score.get(id=other.json()["id"])
    assert (stored.frozen_copy_id, stored.capture_status) == (None, None)


async def test_a_resubmit_filling_a_free_copy_is_accepted(client: AsyncClient) -> None:
    uncaptured: dict[str, Any] = {
        "capture_status": None,
        "frozen_copy_id": None,
        "case_digest": None,
    }
    created = await _post(client, **uncaptured)

    refill = await _post(client)

    assert refill.status_code == 200, refill.text
    assert (await Score.get(id=created.json()["id"])).frozen_copy_id == COPY


async def test_two_concurrent_claims_cannot_both_win(client: AsyncClient) -> None:
    results = await asyncio.gather(
        _post(client, spec_id="spec-a"),
        _post(client, owner=BOB, spec_id="spec-b"),
    )

    assert sorted(result.status_code for result in results) == [201, 422]
    assert [_claimed(result) for result in results].count(True) == 1
    assert await Score.filter(frozen_copy_id=COPY).count() == 1


async def test_a_claim_lost_to_the_index_is_still_a_422(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The race the pre-check cannot see: another claim commits between the check and the insert.
    # Disabling the pre-check makes the unique index the one that refuses.
    await _post(client)

    async def skipped(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ScoreStore, "_precheck_copy_claim", skipped)
    second = await _post(client, owner=BOB, spec_id="spec-2")

    assert _claimed(second), second.text
    assert await Score.all().count() == 1


async def test_a_fill_lost_to_the_index_is_still_a_422(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _post(client)
    uncaptured: dict[str, Any] = {
        "capture_status": None,
        "frozen_copy_id": None,
        "case_digest": None,
    }
    other = await _post(client, spec_id="spec-2", **uncaptured)

    async def skipped(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ScoreStore, "_precheck_copy_claim", skipped)
    refill = await _post(client, spec_id="spec-2")

    assert _claimed(refill), refill.text
    assert (await Score.get(id=other.json()["id"])).frozen_copy_id is None


async def test_the_openapi_document_names_the_lookup_and_the_refusal(tortoise_db: None) -> None:
    app = create_app(
        Settings.model_validate({"database_url": "sqlite://:memory:", "cors_origins": []})
    )
    paths = app.openapi()["paths"]

    lookup = paths["/v1/public/scores/by-pinned-cache/{frozen_copy_id}"]["get"]["responses"]
    submit = paths["/v1/scores"]["post"]["responses"]

    assert set(lookup) >= {"200", "404"}
    assert "422" in submit


@pytest.mark.parametrize("caller", [None, ALICE, BOB], ids=["anonymous", "owner", "other"])
async def test_visibility_flip_after_store_read_refuses_pinned_cache(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caller: str | None
) -> None:
    created = await _post(client)
    private = await _post(client, benchmark_id="secret", frozen_copy_id=OTHER_COPY)
    assert created.status_code == private.status_code == 201
    unknown_response = await _lookup(client, "11111111-2222-4333-8444-555555555555")
    private_response = await _lookup(client, OTHER_COPY)
    read_complete, resume = asyncio.Event(), asyncio.Event()
    original = ScoreStore.public_score_for_pinned_cache

    async def paused_lookup(self: ScoreStore, frozen_copy_id: str) -> Score | None:
        score = await original(self, frozen_copy_id)
        assert score is not None  # The real store already observed a public board.
        read_complete.set()
        await resume.wait()
        return score

    monkeypatch.setattr(ScoreStore, "public_score_for_pinned_cache", paused_lookup)
    # INVARIANT: do not trust the initial visibility after yielding; no sleep-based race.
    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
        pending = tasks.create_task(
            client.get(
                f"/v1/public/scores/by-pinned-cache/{COPY}",
                headers=_as(caller) if caller else {},
            )
        )
        await read_complete.wait()
        await Benchmark.filter(id="hle").update(visibility="private")
        resume.set()
    response = pending.result()
    assert (
        response.status_code == unknown_response.status_code == private_response.status_code == 404
    )
    assert response.content == unknown_response.content == private_response.content
    assert response.json() == {"detail": "score not found"}
    for name, expected in (
        ("cache-control", "private, no-store"),
        ("vary", "X-User-Email, Origin"),
    ):
        assert (
            response.headers[name]
            == unknown_response.headers[name]
            == private_response.headers[name]
        )
        assert response.headers[name] == expected


@pytest.mark.parametrize("stage", ["lookup", "final_check"])
async def test_pinned_cache_visibility_read_failure_is_sanitized_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    assert (await _post(client)).status_code == 201

    async def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise OperationalError("private database connection details")

    if stage == "lookup":
        monkeypatch.setattr(ScoreStore, "public_score_for_pinned_cache", unavailable)
    else:
        monkeypatch.setattr(score_routes, "turned_private", unavailable)
    response = await _lookup(client, COPY)
    assert response.status_code == 503
    assert response.json() == {"detail": score_routes.STORE_UNAVAILABLE_DETAIL}
