"""Recorded reproductions of a score (E14 B4, PRD `reproduce` R4, R6, R12-R15, R18, R22; TDD #7-13).

FEATURE: OME-1307 — `POST /v1/scores/{id}/reproductions` stores one row for each exact replay a
verified identity reports, with no cap. The score read derives the count and the last time from
those rows; nothing is stored on `scores`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise.exceptions import OperationalError

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes.dependencies import MISSING_IDENTITY_DETAIL, UNTRUSTED_PEER_DETAIL
from scoreboard.scores.models import Benchmark, Score, ScoreReproduction
from scoreboard.scores.schemas import ReproductionSubmission
from scoreboard.scores.store import (
    BenchmarkVisibilityChanged,
    ReproductionRunIdConflict,
    ScoreStore,
    _score_to_schema,
)

ALICE = "alice@example.test"
BOB = "bob@example.test"
CAROL = "carol@example.test"
LABEL = "cr-0123456789ab"
OTHER_LABEL = "cr-ba9876543210"


def _payload(**overrides: Any) -> dict[str, Any]:
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
        "reproducible": "complete",
        "cache_revision": LABEL,
        "answer_seed": 42,
    }
    payload.update(overrides)
    return payload


def _record(**overrides: Any) -> dict[str, Any]:
    """A reproduction body that matches `_payload()` exactly."""
    body: dict[str, Any] = {
        "run_id": f"run-{uuid4()}",
        "score": 0.75,
        "total_questions": 4,
        "cache_revision": LABEL,
        "client": {"name": "screamingface", "version": "0.2.0", "platform": "darwin"},
    }
    body.update(overrides)
    return body


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


async def _make_app(tortoise_db: None, **settings: object) -> FastAPI:
    app = create_app(
        Settings.model_validate(
            {"database_url": "sqlite://:memory:", "cors_origins": [], **settings}
        )
    )
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    return app


def _client(app: FastAPI, peer: tuple[str, int] | None = None) -> AsyncClient:
    transport = ASGITransport(app=app) if peer is None else ASGITransport(app=app, client=peer)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def cloudflare_app(tortoise_db: None, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # Same pins as `app_with_cloudflare_auth` in test_scores_routes.py: FORWARDED_ALLOW_IPS must
    # be disjoint from allowed_networks, and ASGITransport's fake peer is 127.0.0.1.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    return await _make_app(
        tortoise_db, auth_mode="cloudflare_headers", allowed_networks="127.0.0.1/32"
    )


@pytest_asyncio.fixture
async def client(cloudflare_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with _client(cloudflare_app) as http:
        yield http


@pytest_asyncio.fixture
async def disabled_client(tortoise_db: None) -> AsyncGenerator[AsyncClient, None]:
    async with _client(await _make_app(tortoise_db)) as http:
        yield http


async def _submit(http: AsyncClient, owner: str = ALICE, **overrides: Any) -> str:
    created = await http.post(
        "/v1/scores", json=_payload(**overrides), headers={"X-User-Email": owner}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _rows(score_id: str) -> list[ScoreReproduction]:
    return await ScoreReproduction.filter(score_id=score_id).order_by("reproduced_at")


# --- #7 R12: no identity is 401, an untrusted peer is 403 (the PATCH rules) -------------------


@pytest.mark.asyncio
async def test_record_without_identity_is_401(client: AsyncClient) -> None:
    score_id = await _submit(client)

    missing = await client.post(f"/v1/scores/{score_id}/reproductions", json=_record())
    blank = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as("  ")
    )

    assert missing.status_code == 401
    assert missing.json() == {"detail": MISSING_IDENTITY_DETAIL}
    assert blank.status_code == 401
    assert await _rows(score_id) == []


@pytest.mark.asyncio
async def test_record_without_identity_is_401_before_anything_else_is_checked(
    client: AsyncClient,
) -> None:
    # An unauthenticated caller must not learn whether the id exists or why its body is refused:
    # 401, never 404 or 422.
    unknown = await client.post(f"/v1/scores/{uuid4()}/reproductions", json=_record())
    malformed = await client.post(f"/v1/scores/{uuid4()}/reproductions", json={})

    assert unknown.status_code == 401
    assert malformed.status_code == 401


@pytest.mark.asyncio
async def test_record_from_an_untrusted_peer_is_403(cloudflare_app: FastAPI) -> None:
    async with _client(cloudflare_app) as trusted:
        score_id = await _submit(trusted)
    async with _client(cloudflare_app, peer=("203.0.113.5", 443)) as untrusted:
        response = await untrusted.post(
            f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
        )

    assert response.status_code == 403
    assert response.json() == {"detail": UNTRUSTED_PEER_DETAIL}
    assert await _rows(score_id) == []


# --- #8 R13: a score that is not `complete` is a 409 not_reproducible -------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"reproducible": "partial"}, id="partial"),
        pytest.param({"reproducible": None, "cache_revision": None}, id="null-legacy"),
    ],
)
async def test_record_on_a_partial_or_null_score_is_409(
    client: AsyncClient, overrides: dict[str, Any]
) -> None:
    payload = {k: v for k, v in _payload(**overrides).items() if v is not None}
    created = await client.post("/v1/scores", json=payload, headers=_as(ALICE))
    score_id = created.json()["id"]

    response = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "not_reproducible"
    assert isinstance(detail["message"], str)
    assert await _rows(score_id) == []


# --- #9 R14: a body that differs from the stored score is a 422 not_exact ---------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"score": 0.7}, id="score"),
        pytest.param({"score": 0.7500000000000001}, id="score-one-ulp-off"),
        pytest.param({"total_questions": 5}, id="total-questions"),
        pytest.param({"cache_revision": OTHER_LABEL}, id="other-label"),
        pytest.param({"cache_revision": None}, id="no-label-for-a-labelled-score"),
    ],
)
async def test_record_with_mismatched_numbers_or_revision_is_422_not_exact(
    client: AsyncClient, overrides: dict[str, Any]
) -> None:
    score_id = await _submit(client)

    response = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(**overrides), headers=_as(BOB)
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "not_exact"
    assert isinstance(detail["message"], str)
    assert await _rows(score_id) == []


@pytest.mark.asyncio
async def test_a_label_for_a_score_stored_without_one_is_not_exact(client: AsyncClient) -> None:
    # A `complete` run with no cacheable call has no label (R23); a record that names one differs.
    score_id = await _submit(client, cache_revision=None)

    without = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(cache_revision=None), headers=_as(BOB)
    )
    with_label = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
    )

    assert without.status_code == 201, without.text
    assert without.json()["cache_revision"] is None
    assert with_label.status_code == 422
    assert with_label.json()["detail"]["code"] == "not_exact"


@pytest.mark.asyncio
async def test_the_refusals_are_checked_in_the_documented_order(client: AsyncClient) -> None:
    # 404 (private, not yours) before 409 (not complete) before 422 (not exact).
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    partial = await _submit(client, reproducible="partial", cache_revision=None)
    private = await _submit(
        client, benchmark_id="private-x", reproducible="partial", cache_revision=None
    )

    not_complete_and_not_exact = await client.post(
        f"/v1/scores/{partial}/reproductions", json=_record(score=0.1), headers=_as(BOB)
    )
    private_and_not_complete = await client.post(
        f"/v1/scores/{private}/reproductions", json=_record(score=0.1), headers=_as(BOB)
    )

    assert not_complete_and_not_exact.status_code == 409
    assert private_and_not_complete.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"run_id": ""}, id="empty-run-id"),
        pytest.param({"run_id": "r" * 129}, id="long-run-id"),
        pytest.param({"cache_revision": "cr-XYZ"}, id="bad-label"),
        pytest.param({"extra": 1}, id="unknown-field"),
    ],
)
async def test_record_with_a_malformed_body_is_a_plain_422(
    client: AsyncClient, body: dict[str, Any]
) -> None:
    score_id = await _submit(client)

    response = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(**body), headers=_as(BOB)
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert await _rows(score_id) == []


@pytest.mark.asyncio
async def test_record_without_the_client_block_is_a_422(client: AsyncClient) -> None:
    score_id = await _submit(client)
    body = _record()
    del body["client"]

    response = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB)
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "client"]


# --- the happy path and the response shape (K7) -----------------------------------------------


@pytest.mark.asyncio
async def test_an_exact_record_stores_one_row_and_answers_201(client: AsyncClient) -> None:
    score_id = await _submit(client)
    body = _record(run_id="run-1")

    response = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB)
    )

    assert response.status_code == 201, response.text
    shown = response.json()
    assert set(shown) == {
        "id",
        "score_id",
        "reproduced_by",
        "reproduced_at",
        "run_id",
        "cache_revision",
        "client_version",
    }
    assert shown["score_id"] == score_id
    assert shown["reproduced_by"] == BOB
    assert shown["run_id"] == "run-1"
    assert shown["cache_revision"] == LABEL
    assert shown["client_version"] == "0.2.0"
    (row,) = await _rows(score_id)
    assert str(row.id) == shown["id"]
    assert row.reproduced_by == BOB


@pytest.mark.asyncio
async def test_any_verified_identity_may_record_including_the_submitter(
    client: AsyncClient,
) -> None:
    score_id = await _submit(client, ALICE)

    owner = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(ALICE)
    )
    stranger = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
    )

    assert owner.status_code == stranger.status_code == 201
    assert {row.reproduced_by for row in await _rows(score_id)} == {ALICE, BOB}


@pytest.mark.asyncio
async def test_a_client_without_a_version_stores_no_version(client: AsyncClient) -> None:
    score_id = await _submit(client)

    response = await client.post(
        f"/v1/scores/{score_id}/reproductions",
        json=_record(client={"name": "screamingface"}),
        headers=_as(BOB),
    )

    assert response.status_code == 201, response.text
    assert response.json()["client_version"] is None


# --- #10 R15: a private-board score is the owner's alone --------------------------------------


@pytest.mark.asyncio
async def test_record_on_a_private_score_by_a_non_owner_is_the_same_404_as_an_unknown_id(
    client: AsyncClient,
) -> None:
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    score_id = await _submit(client, ALICE, benchmark_id="private-x")

    stranger = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
    )
    unknown = await client.post(
        f"/v1/scores/{uuid4()}/reproductions", json=_record(), headers=_as(BOB)
    )
    owner = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(ALICE)
    )

    assert stranger.status_code == unknown.status_code == 404
    # Byte-identical, so holding a real id is not confirmable (OME-894), including the cache policy.
    assert stranger.json() == unknown.json() == {"detail": "score not found"}
    assert stranger.headers["cache-control"] == unknown.headers["cache-control"]
    assert stranger.headers["vary"] == unknown.headers["vary"]
    assert owner.status_code == 201, owner.text
    assert [row.reproduced_by for row in await _rows(score_id)] == [ALICE]


@pytest.mark.asyncio
async def test_an_unverified_claim_never_reaches_a_private_score(
    disabled_client: AsyncClient,
) -> None:
    # In `disabled` mode `X-User-Email` is an unverified claim, so naming the owner must not open a
    # private row (the `get_score` and `_load_owned_score` rule). The row is made directly: a
    # private board takes no write in this mode.
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    score = await Score.create(
        benchmark_id="private-x",
        spec_id="spec-1",
        url4_expression="url4://x",
        submitted_by=ALICE,
        score=0.75,
        total_questions=4,
        ran_with_providers=["openai"],
        reproducible="complete",
        cache_revision=LABEL,
    )

    response = await disabled_client.post(
        f"/v1/scores/{score.id}/reproductions", json=_record(), headers=_as(ALICE)
    )

    assert response.status_code == 404
    assert await _rows(str(score.id)) == []


@pytest.mark.asyncio
async def test_record_on_an_unknown_score_is_404(client: AsyncClient) -> None:
    response = await client.post(
        f"/v1/scores/{uuid4()}/reproductions", json=_record(), headers=_as(BOB)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "score not found"}


@pytest.mark.asyncio
async def test_record_in_disabled_mode_trusts_x_user_email_on_a_public_score(
    disabled_client: AsyncClient,
) -> None:
    created = await disabled_client.post("/v1/scores", json=_payload())
    score_id = created.json()["id"]

    anonymous = await disabled_client.post(f"/v1/scores/{score_id}/reproductions", json=_record())
    named = await disabled_client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
    )

    assert anonymous.status_code == 401
    assert named.status_code == 201, named.text


# --- #11 R18: the same run twice returns the first row ----------------------------------------


@pytest.mark.asyncio
async def test_record_same_run_twice_returns_the_first_row_with_200(client: AsyncClient) -> None:
    score_id = await _submit(client)
    body = _record(run_id="run-1")

    first = await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))
    second = await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(await _rows(score_id)) == 1


@pytest.mark.asyncio
async def test_the_same_run_id_on_another_score_is_a_new_record(client: AsyncClient) -> None:
    # The unique pair is `(score_id, run_id)`, not `run_id` alone.
    one = await _submit(client, spec_id="spec-1")
    two = await _submit(client, spec_id="spec-2")

    first = await client.post(
        f"/v1/scores/{one}/reproductions", json=_record(run_id="run-1"), headers=_as(BOB)
    )
    second = await client.post(
        f"/v1/scores/{two}/reproductions", json=_record(run_id="run-1"), headers=_as(BOB)
    )

    assert first.status_code == second.status_code == 201


@pytest.mark.asyncio
async def test_two_records_of_one_run_at_the_same_time_insert_one_row(
    client: AsyncClient,
) -> None:
    # R22: whichever loses the unique index re-reads the winner's row and answers 200.
    score_id = await _submit(client)
    body = _record(run_id="run-1")

    results = await asyncio.gather(
        *(
            client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))
            for _ in range(2)
        )
    )

    assert sorted(response.status_code for response in results) == [200, 201]
    assert len(await _rows(score_id)) == 1


@pytest.mark.asyncio
async def test_a_record_for_a_score_deleted_meanwhile_reports_it_gone(client: AsyncClient) -> None:
    score_id = await _submit(client)
    await Score.filter(id=score_id).delete()

    # The route found the score, then it vanished before the insert: the store reports it as gone
    # (the route answers 404), rather than a foreign-key failure that reads as an unavailable store.
    outcome = await ScoreStore().record_reproduction(
        UUID(score_id),
        reproduced_by=BOB,
        submission=ReproductionSubmission(**_record()),
        benchmark_id="hle",
        expect_private=False,
    )

    assert outcome is None


# --- #12 R6: the same identity may record again with a new run, with no cap -------------------


@pytest.mark.asyncio
async def test_same_identity_new_run_adds_a_row_with_no_cap(client: AsyncClient) -> None:
    score_id = await _submit(client)

    statuses = [
        (
            await client.post(
                f"/v1/scores/{score_id}/reproductions",
                json=_record(run_id=f"run-{n}"),
                headers=_as(BOB),
            )
        ).status_code
        for n in range(12)
    ]

    assert statuses == [201] * 12
    assert len(await _rows(score_id)) == 12


# --- #13 R4: the score read shows the count and the last time ---------------------------------


@pytest.mark.asyncio
async def test_score_read_shows_the_count_and_the_last_time(client: AsyncClient) -> None:
    score_id = await _submit(client)
    other = await _submit(client, spec_id="spec-2")
    for n, who in enumerate((BOB, BOB, CAROL)):
        recorded = await client.post(
            f"/v1/scores/{score_id}/reproductions",
            json=_record(run_id=f"run-{n}"),
            headers=_as(who),
        )
        assert recorded.status_code == 201, recorded.text
    await client.post(f"/v1/scores/{other}/reproductions", json=_record(), headers=_as(BOB))

    shown = await client.get(f"/v1/scores/{score_id}")

    assert shown.status_code == 200
    body = shown.json()
    assert body["reproduction_count"] == 3
    latest = max(row.reproduced_at for row in await _rows(score_id))
    assert body["last_reproduced_at"].startswith(latest.strftime("%Y-%m-%dT%H:%M:%S"))
    assert (await client.get(f"/v1/scores/{other}")).json()["reproduction_count"] == 1


@pytest.mark.asyncio
async def test_a_score_never_reproduced_reads_without_either_key(client: AsyncClient) -> None:
    # INVARIANT: an absent count reads as 0 (K8). Excluding the zero keeps the private JSONL export
    # and every PATCH or resubmit response byte-identical for a row with no reproductions.
    score_id = await _submit(client)

    body = (await client.get(f"/v1/scores/{score_id}")).json()

    assert "reproduction_count" not in body
    assert "last_reproduced_at" not in body


@pytest.mark.asyncio
async def test_a_row_with_no_reproductions_serializes_without_either_key(
    client: AsyncClient,
) -> None:
    score_id = await _submit(client)
    row = await Score.get(id=score_id)

    schema = _score_to_schema(row)

    assert schema.reproduction_count == 0
    assert "reproduction_count" not in schema.model_dump(mode="python")
    assert "last_reproduced_at" not in schema.model_dump(mode="python")
    assert "reproduction_count" not in schema.model_dump(mode="json")
    patched = await client.patch(
        f"/v1/scores/{score_id}",
        json={"paper_url": "https://arxiv.org/abs/2610.01234"},
        headers=_as(ALICE),
    )
    assert patched.status_code == 200
    assert "reproduction_count" not in patched.json()


@pytest.mark.asyncio
async def test_a_reproduced_score_serializes_both_keys(client: AsyncClient) -> None:
    score_id = await _submit(client)
    await client.post(f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB))

    body = (await client.get(f"/v1/scores/{score_id}")).json()

    assert body["reproduction_count"] == 1
    assert "last_reproduced_at" in body


@pytest.mark.asyncio
async def test_the_aggregate_is_one_count_and_one_latest_time(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    score = await Score.create(
        benchmark_id="hle",
        spec_id="spec-1",
        url4_expression="url4://x",
        score=0.5,
        total_questions=4,
        ran_with_providers=[],
    )
    store = ScoreStore()

    assert await store.reproduction_aggregate(score.id) == (0, None)
    first = await ScoreReproduction.create(score=score, reproduced_by=ALICE, run_id="a")
    second = await ScoreReproduction.create(score=score, reproduced_by=BOB, run_id="b")

    count, last = await store.reproduction_aggregate(score.id)

    assert count == 2
    assert last == max(first.reproduced_at, second.reproduced_at)


@pytest.mark.asyncio
async def test_the_count_stays_off_the_leaderboard_rows(client: AsyncClient) -> None:
    score_id = await _submit(client)
    await client.post(f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB))

    board = await client.get("/v1/leaderboard/hle")

    assert board.status_code == 200
    for entry in board.json()["entries"]:
        assert "reproduction_count" not in entry
        assert "last_reproduced_at" not in entry


@pytest.mark.asyncio
async def test_a_private_score_read_by_its_owner_shows_the_count(client: AsyncClient) -> None:
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    score_id = await _submit(client, ALICE, benchmark_id="private-x")
    await client.post(f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(ALICE))

    owner = await client.get(f"/v1/scores/{score_id}", headers=_as(ALICE))
    stranger = await client.get(f"/v1/scores/{score_id}", headers=_as(BOB))

    assert owner.json()["reproduction_count"] == 1
    assert stranger.status_code == 404
    assert "reproduction_count" not in stranger.text


# --- observability and availability -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_record_logs_the_score_id_and_status_but_no_email(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    score_id = await _submit(client)
    body = _record(run_id="run-1")

    with caplog.at_level(logging.INFO):
        await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))
        await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))

    messages = [record.getMessage() for record in caplog.records]
    recorded = [m for m in messages if "score reproduction" in m]
    assert len(recorded) == 2
    assert all(score_id in m for m in recorded)
    assert "created" in recorded[0] and "existing" in recorded[1]
    assert BOB not in " ".join(messages)


@pytest.mark.asyncio
async def test_record_store_unavailable_is_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    score_id = await _submit(client)

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise OperationalError("database is down")

    monkeypatch.setattr(Score, "get_or_none", unavailable)
    response = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}


@pytest.mark.asyncio
async def test_score_read_store_unavailable_on_the_aggregate_is_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    score_id = await _submit(client)

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise OperationalError("database is down")

    monkeypatch.setattr(ScoreStore, "reproduction_aggregate", unavailable)
    response = await client.get(f"/v1/scores/{score_id}")

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}


# --- a run_id belongs to the identity that recorded it (R18) -----------------------------


@pytest.mark.asyncio
async def test_the_same_run_id_from_a_different_identity_is_a_409_that_reveals_nothing(
    client: AsyncClient,
) -> None:
    score_id = await _submit(client)
    body = _record(run_id="run-1")
    first = await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))

    other = await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(CAROL))

    assert first.status_code == 201
    assert other.status_code == 409
    detail = other.json()["detail"]
    assert detail["code"] == "run_id_conflict"
    assert isinstance(detail["message"], str)
    # Nothing about the first row: not its id, its identity, or its time.
    for secret in (BOB, first.json()["id"], first.json()["reproduced_at"]):
        assert secret not in other.text
    assert [row.reproduced_by for row in await _rows(score_id)] == [BOB]


@pytest.mark.asyncio
async def test_the_same_run_id_from_the_same_identity_still_answers_200(
    client: AsyncClient,
) -> None:
    score_id = await _submit(client)
    body = _record(run_id="run-1")
    await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))

    again = await client.post(f"/v1/scores/{score_id}/reproductions", json=body, headers=_as(BOB))

    assert again.status_code == 200
    assert again.json()["reproduced_by"] == BOB


@pytest.mark.asyncio
async def test_the_store_refuses_a_run_id_another_identity_recorded(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="HLE")
    score = await Score.create(
        spec_id="s",
        url4_expression="url4://x",
        submitted_by=ALICE,
        score=0.75,
        total_questions=4,
        ran_with_providers=["openai"],
        benchmark_id="hle",
    )
    store = ScoreStore()
    submission = ReproductionSubmission(**_record(run_id="run-1"))
    await store.record_reproduction(
        score.id, reproduced_by=BOB, submission=submission, benchmark_id="hle", expect_private=False
    )

    with pytest.raises(ReproductionRunIdConflict):
        await store.record_reproduction(
            score.id,
            reproduced_by=CAROL,
            submission=submission,
            benchmark_id="hle",
            expect_private=False,
        )


# --- the board is re-checked INSIDE the insert (as A1's patch_metadata does) ------------


@pytest.mark.asyncio
async def test_record_refuses_a_board_that_turned_private_after_the_pre_check(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The route's own check ran against a public board and let a non-owner through; the flip lands
    # before the write. The re-check under the lock turns that into a retryable 409, with no row.
    score_id = await _submit(client)
    await Benchmark.filter(id="hle").update(visibility="private")

    async def stale(_benchmark_id: str) -> bool:
        return False

    monkeypatch.setattr("scoreboard.routes.scores.turned_private", stale)
    response = await client.post(
        f"/v1/scores/{score_id}/reproductions", json=_record(), headers=_as(BOB)
    )

    assert response.status_code == 409
    assert "visibility changed" in response.json()["detail"]
    assert await _rows(score_id) == []


@pytest.mark.asyncio
async def test_store_record_revalidates_the_board_under_the_lock(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="HLE")
    score = await Score.create(
        spec_id="s",
        url4_expression="url4://x",
        submitted_by=ALICE,
        score=0.75,
        total_questions=4,
        ran_with_providers=["openai"],
        benchmark_id="hle",
    )
    await Benchmark.filter(id="hle").update(visibility="private")

    with pytest.raises(BenchmarkVisibilityChanged):
        await ScoreStore().record_reproduction(
            score.id,
            reproduced_by=BOB,
            submission=ReproductionSubmission(**_record()),
            benchmark_id="hle",
            expect_private=False,
        )

    assert await _rows(str(score.id)) == []
