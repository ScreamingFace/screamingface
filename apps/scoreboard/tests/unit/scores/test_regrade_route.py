"""The re-grade of a score onto a Benchmark's bumped revision (OME-1909).

FEATURE: OME-1909 — a team member replays an old entry's pinned cache against the bumped revision
and posts the result to `POST /v1/scores/{source_id}/regrades`. The board stores it as a NEW row,
credited to the source's submitter, linked to the source, and naming who re-graded it. The source
row is never changed; it simply stops ranking once the board's revision moves on.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score

SUBMITTER = "alice@example.test"
REGRADER = "carol@example.test"
OUTSIDER = "mallory@example.test"
COPY_ID = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"
OLD_REVISION = "rev-1"
NEW_REVISION = "rev-2"


def _payload(**overrides: Any) -> dict[str, Any]:
    """A normal `ScoreSubmission` body: the source run, captured into a frozen copy."""
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "benchmark_revision": OLD_REVISION,
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.5,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
        "authors": [SUBMITTER, "bob@example.test"],
        "capture_status": "complete",
        "frozen_copy_id": COPY_ID,
        "answer_seed": 42,
    }
    payload.update(overrides)
    return payload


def _regrade(**overrides: Any) -> dict[str, Any]:
    """The re-grade body the SDK sends: the same recipe replayed at the new revision.

    It still carries the source's frozen copy and capture status, as a replay would; the route
    must ignore both, because that copy belongs to the source row.
    """
    body: dict[str, Any] = _payload(
        benchmark_revision=NEW_REVISION,
        score=0.75,
        authors=[REGRADER],
        submitted_by=REGRADER,
    )
    body.update(overrides)
    return body


def _as(email: str) -> dict[str, str]:
    """The identity header the mesh injects for `email`."""
    return {"X-User-Email": email}


async def _make_app(tortoise_db: None, **settings: object) -> FastAPI:
    """An app over the test database with the `hle` board registered at the OLD revision."""
    app = create_app(
        Settings.model_validate(
            {"database_url": "sqlite://:memory:", "cors_origins": [], **settings}
        )
    )
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam", revision=OLD_REVISION)
    await Benchmark.create(id="gpqa", display_name="GPQA", revision=NEW_REVISION)
    return app


def _client(app: FastAPI) -> AsyncClient:
    """An HTTP client whose peer (127.0.0.1) is inside the trusted network below."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def client(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    """A client on a `cloudflare_headers` app whose only re-grader is REGRADER."""
    # Same pins as `cloudflare_app` in test_score_reproductions.py: FORWARDED_ALLOW_IPS must be
    # disjoint from allowed_networks, and ASGITransport's fake peer is 127.0.0.1.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app: FastAPI = await _make_app(
        tortoise_db,
        auth_mode="cloudflare_headers",
        allowed_networks="127.0.0.1/32",
        regrade_identities=(REGRADER,),
    )
    async with _client(app) as http:
        yield http


async def _submit_source(http: AsyncClient, **overrides: Any) -> str:
    """Submit the source score as SUBMITTER, then bump the board to the new revision."""
    created: Response = await http.post(
        "/v1/scores", json=_payload(**overrides), headers=_as(SUBMITTER)
    )
    assert created.status_code == 201, created.text
    await Benchmark.filter(id="hle").update(revision=NEW_REVISION)
    return str(created.json()["id"])


async def _post_regrade(
    http: AsyncClient, source_id: str, who: str = REGRADER, **overrides: Any
) -> Response:
    """POST the re-grade of `source_id` as `who`."""
    return await http.post(
        f"/v1/scores/{source_id}/regrades", json=_regrade(**overrides), headers=_as(who)
    )


def _code(response: Response) -> str:
    """The `code` of a `{code, message}` refusal."""
    detail: dict[str, Any] = response.json()["detail"]
    return str(detail["code"])


# --- the refusals, in the order the route checks them -------------------------------------------


@pytest.mark.asyncio
async def test_a_regrade_is_refused_for_everyone_when_auth_is_disabled(tortoise_db: None) -> None:
    # WHY: in `disabled` mode the identity header is an unverified claim, so naming REGRADER would
    # be enough to re-grade anything. The route refuses before it reads the header at all.
    app: FastAPI = await _make_app(tortoise_db, regrade_identities=(REGRADER,))
    async with _client(app) as http:
        created: Response = await http.post("/v1/scores", json=_payload(submitted_by=SUBMITTER))
        assert created.status_code == 201, created.text
        await Benchmark.filter(id="hle").update(revision=NEW_REVISION)

        refused: Response = await _post_regrade(http, str(created.json()["id"]))
        headless: Response = await http.post(
            f"/v1/scores/{created.json()['id']}/regrades", json=_regrade()
        )

    assert refused.status_code == 403
    assert _code(refused) == "regrade_unavailable"
    # No header at all is the same 403, not the 401 the identity check would give.
    assert headless.status_code == 403
    assert _code(headless) == "regrade_unavailable"
    assert await Score.filter(regraded_from_id__isnull=False).count() == 0


@pytest.mark.asyncio
async def test_a_verified_identity_outside_the_regrade_list_is_refused(
    client: AsyncClient,
) -> None:
    source_id: str = await _submit_source(client)

    outsider: Response = await _post_regrade(client, source_id, who=OUTSIDER)
    # The source's own submitter is not a re-grader either: credit is not permission.
    owner: Response = await _post_regrade(client, source_id, who=SUBMITTER)

    assert outsider.status_code == 403
    assert _code(outsider) == "not_allowed"
    assert owner.status_code == 403
    assert _code(owner) == "not_allowed"


@pytest.mark.asyncio
async def test_a_regrade_of_an_unknown_score_is_404(client: AsyncClient) -> None:
    missing: Response = await _post_regrade(client, str(uuid4()))

    assert missing.status_code == 404
    assert _code(missing) == "unknown_score"


@pytest.mark.asyncio
async def test_a_source_on_a_private_board_is_the_same_404_as_an_unknown_one(
    client: AsyncClient,
) -> None:
    # INVARIANT (OME-894): a private board's scores belong to their submitter alone, and holding a
    # real id must not be confirmable. A re-grader is not that submitter.
    source_id: str = await _submit_source(client)
    await Benchmark.filter(id="hle").update(visibility="private")

    refused: Response = await _post_regrade(client, source_id)

    assert refused.status_code == 404
    assert _code(refused) == "unknown_score"


@pytest.mark.asyncio
async def test_a_regrade_onto_another_benchmark_is_422(client: AsyncClient) -> None:
    source_id: str = await _submit_source(client)

    moved: Response = await _post_regrade(client, source_id, benchmark_id="gpqa")

    assert moved.status_code == 422
    assert _code(moved) == "different_benchmark"


@pytest.mark.asyncio
async def test_a_regrade_not_at_the_registered_revision_is_409(client: AsyncClient) -> None:
    source_id: str = await _submit_source(client)

    # A revision the board does not run: the re-graded entry would never rank.
    stale: Response = await _post_regrade(client, source_id, benchmark_revision="rev-9")
    # The revision named only in `metadata`, the deployed Client's wire shape, resolves the same.
    via_metadata: Response = await _post_regrade(
        client, source_id, benchmark_revision=None, metadata={"benchmark_revision": "rev-9"}
    )

    assert stale.status_code == 409
    assert _code(stale) == "not_current_revision"
    assert via_metadata.status_code == 409
    assert _code(via_metadata) == "not_current_revision"
    assert await Score.filter(regraded_from_id__isnull=False).count() == 0


@pytest.mark.asyncio
async def test_a_regrade_at_the_sources_own_revision_is_409(client: AsyncClient) -> None:
    # The board never moved: the source still ranks, so a "re-grade" would duplicate it.
    created: Response = await client.post("/v1/scores", json=_payload(), headers=_as(SUBMITTER))
    assert created.status_code == 201, created.text

    same: Response = await _post_regrade(
        client, str(created.json()["id"]), benchmark_revision=OLD_REVISION
    )

    assert same.status_code == 409
    assert _code(same) == "not_current_revision"


@pytest.mark.asyncio
async def test_a_second_regrade_of_one_source_is_409(client: AsyncClient) -> None:
    source_id: str = await _submit_source(client)

    first: Response = await _post_regrade(client, source_id)
    # A different result, so the refusal comes from the one-re-grade rule, not recipe dedup.
    second: Response = await _post_regrade(client, source_id, score=0.25)

    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert _code(second) == "already_regraded"
    assert await Score.filter(regraded_from_id=source_id).count() == 1


@pytest.mark.asyncio
async def test_two_concurrent_regrades_of_one_source_store_exactly_one(
    client: AsyncClient,
) -> None:
    # INVARIANT: the unique index decides, not a pre-read, so two racing requests cannot both win.
    source_id: str = await _submit_source(client)

    results: list[Response] = list(
        await asyncio.gather(
            _post_regrade(client, source_id), _post_regrade(client, source_id, score=0.25)
        )
    )

    assert sorted(response.status_code for response in results) == [201, 409]
    assert await Score.filter(regraded_from_id=source_id).count() == 1


@pytest.mark.asyncio
async def test_a_regrade_whose_result_is_already_on_the_board_is_409(
    client: AsyncClient,
) -> None:
    # The submitter already re-ran the same recipe at the new revision and got the same result.
    # The recipe-identity index refuses a second copy; that is a 409, not a 503.
    source_id: str = await _submit_source(client)
    rerun: Response = await client.post(
        "/v1/scores",
        json=_payload(benchmark_revision=NEW_REVISION, score=0.75, frozen_copy_id=None),
        headers=_as(SUBMITTER),
    )
    assert rerun.status_code == 201, rerun.text

    duplicate: Response = await _post_regrade(client, source_id)

    assert duplicate.status_code == 409
    assert _code(duplicate) == "already_on_board"
    assert await Score.filter(regraded_from_id__isnull=False).count() == 0


# --- what a re-grade stores ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_regrade_is_credited_to_the_source_submitter_and_names_who_regraded_it(
    client: AsyncClient,
) -> None:
    source_id: str = await _submit_source(client, paper_url="https://arxiv.org/abs/2501.00001")
    source: Score = await Score.get(id=source_id)
    await Score.filter(id=source_id).update(verified_by_screamingface=False)

    created: Response = await _post_regrade(client, source_id)

    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    stored: Score = await Score.get(id=body["id"])
    # Credit is the source's, whatever the body claimed (it named REGRADER in both fields).
    assert stored.submitted_by == source.submitted_by == SUBMITTER
    assert stored.authors == [SUBMITTER, "bob@example.test"]
    assert stored.paper_url == "https://arxiv.org/abs/2501.00001"
    # Published masked, as every score read publishes a submitter: the email's local part.
    assert body["submitted_by"] == "alice"
    # The link and the worker.
    assert str(getattr(stored, "regraded_from_id")) == source_id
    assert stored.regraded_by == REGRADER
    assert body["regraded_from"] == source_id
    # WHY: an email, so it is published like `submitted_by`, the local part only.
    assert body["regraded_by"] == "carol"
    # The frozen copy belongs to the source (one copy, one score), so the re-grade names none.
    assert stored.frozen_copy_id is None
    assert stored.capture_status is None
    assert stored.case_digest is None
    # Copied from the source, never from the request.
    assert stored.verified_by_screamingface is False
    # The result itself is the replay's.
    assert stored.score == 0.75
    assert stored.benchmark_revision == NEW_REVISION
    # The source row is untouched.
    unchanged: Score = await Score.get(id=source_id)
    assert unchanged.frozen_copy_id == COPY_ID
    assert unchanged.score == 0.5
    assert unchanged.benchmark_revision == OLD_REVISION
    assert getattr(unchanged, "regraded_from_id") is None


@pytest.mark.asyncio
async def test_the_score_read_names_the_source_only_on_a_regraded_row(
    client: AsyncClient,
) -> None:
    source_id: str = await _submit_source(client)
    created: Response = await _post_regrade(client, source_id)
    assert created.status_code == 201, created.text

    regraded: Response = await client.get(f"/v1/public/scores/{created.json()['id']}")
    original: Response = await client.get(f"/v1/public/scores/{source_id}")

    assert regraded.status_code == 200, regraded.text
    assert regraded.json()["regraded_from"] == source_id
    assert regraded.json()["regraded_by"] == "carol"
    # Backwards compatible: an ordinary row's read gains no key at all.
    assert "regraded_from" not in original.json()
    assert "regraded_by" not in original.json()


@pytest.mark.asyncio
async def test_the_regraded_entry_ranks_under_the_new_revision_and_the_source_does_not(
    client: AsyncClient,
) -> None:
    source_id: str = await _submit_source(client)
    created: Response = await _post_regrade(client, source_id)
    assert created.status_code == 201, created.text

    board: Response = await client.get("/v1/leaderboard/hle")

    assert board.status_code == 200, board.text
    entries: list[dict[str, Any]] = board.json()["entries"]
    assert [(entry["benchmark_revision"], entry["score"]) for entry in entries] == [
        (NEW_REVISION, 0.75)
    ]
    assert entries[0]["submitted_by"] == "alice"  # the source's submitter, published masked


@pytest.mark.asyncio
async def test_deleting_the_source_keeps_the_regraded_entry_and_drops_only_the_link(
    client: AsyncClient,
) -> None:
    # WHY SET_NULL: a source deletion (the delete CLI, a purge) must neither be blocked by its
    # re-grade nor silently take the re-graded entry with it.
    source_id: str = await _submit_source(client)
    created: Response = await _post_regrade(client, source_id)
    assert created.status_code == 201, created.text

    await Score.filter(id=source_id).delete()

    survivor: Score = await Score.get(id=created.json()["id"])
    assert getattr(survivor, "regraded_from_id") is None
    assert survivor.score == 0.75


def test_regrade_identities_read_a_comma_separated_list_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCOREBOARD_REGRADE_IDENTITIES", " carol@example.test, dan@example.test ,")

    settings: Settings = Settings()

    assert settings.regrade_identities == ("carol@example.test", "dan@example.test")


def test_nobody_may_regrade_by_default() -> None:
    # Fail closed: a deployment that never set the list has no re-graders.
    assert Settings().regrade_identities == ()
