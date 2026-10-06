"""`PATCH /v1/scores/{id}`: the submitter edits `authors` and `paper_url` (E14 A1, PRD
`metadata-ownership` M2, M3, M6-M8, M11-M14, M17-M20; TDD #7-#15, #17).

FEATURE: OME-1307 — verified submitter only, one transaction against a locked row, one event for
each request that changes a value, and nothing at all for a request that changes none.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from tortoise import Tortoise
from tortoise.exceptions import OperationalError

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes.dependencies import MISSING_IDENTITY_DETAIL, UNTRUSTED_PEER_DETAIL
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent
from scoreboard.scores.schemas import ScoreMetadataPatch
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

ALICE = "alice@example.test"
BOB = "bob@example.test"
CAROL = "carol@example.test"
PAPER = "https://arxiv.org/abs/2610.01234"
OTHER_PAPER = "https://doi.org/10.1000/xyz"


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
    }
    payload.update(overrides)
    return payload


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


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


async def _events(score_id: str) -> list[ScoreMetadataEvent]:
    return await ScoreMetadataEvent.filter(score_id=score_id).order_by("edited_at")


# --- #7 M6: not the owner is a 403, and nothing is written ---------------------------------------


async def test_patch_by_non_owner_is_403_and_writes_nothing(client: AsyncClient) -> None:
    score_id = await _submit(client)

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(BOB)
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "not_score_owner"
    assert isinstance(response.json()["detail"]["message"], str)
    stored = await Score.get(id=score_id)
    assert stored.paper_url is None and stored.metadata_updated_at is None
    assert await _events(score_id) == []


# --- #8 M7: no identity is 401, an untrusted peer is 403 (the POST rules) -----------------------


async def test_patch_without_identity_is_401(client: AsyncClient) -> None:
    score_id = await _submit(client)

    response = await client.patch(f"/v1/scores/{score_id}", json={"paper_url": PAPER})
    blank = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers={"X-User-Email": "  "}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": MISSING_IDENTITY_DETAIL}
    assert blank.status_code == 401


async def test_patch_identity_is_checked_before_the_body(client: AsyncClient) -> None:
    # An unauthenticated caller must not learn why its payload would be refused: 401, not 422.
    score_id = await _submit(client)

    response = await client.patch(f"/v1/scores/{score_id}", json={})

    assert response.status_code == 401


async def test_patch_from_an_untrusted_peer_is_403(cloudflare_app: FastAPI) -> None:
    async with _client(cloudflare_app) as trusted:
        score_id = await _submit(trusted)
    async with _client(cloudflare_app, peer=("203.0.113.5", 443)) as untrusted:
        response = await untrusted.patch(
            f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(ALICE)
        )

    assert response.status_code == 403
    assert response.json() == {"detail": UNTRUSTED_PEER_DETAIL}
    assert (await Score.get(id=score_id)).paper_url is None


async def test_patch_in_disabled_mode_trusts_x_user_email_and_401s_without_it(
    disabled_client: AsyncClient,
) -> None:
    created = await disabled_client.post("/v1/scores", json=_payload(submitted_by="tester"))
    score_id = created.json()["id"]

    anonymous = await disabled_client.patch(f"/v1/scores/{score_id}", json={"paper_url": PAPER})
    stranger = await disabled_client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as("someone-else")
    )
    owner = await disabled_client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as("tester")
    )

    assert anonymous.status_code == 401
    assert stranger.status_code == 403
    assert owner.status_code == 200
    assert owner.json()["paper_url"] == PAPER


# --- #9 M8, M13: a missing score and a private score of another are the same 404 ----------------


async def test_patch_private_score_by_non_owner_is_404(client: AsyncClient) -> None:
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    score_id = await _submit(client, benchmark_id="private-x")

    stranger = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(BOB)
    )
    missing = await client.patch(
        f"/v1/scores/{uuid4()}", json={"paper_url": PAPER}, headers=_as(BOB)
    )
    owner = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(ALICE)
    )

    # INVARIANT: byte-identical to an unknown id, so holding a real id confirms nothing.
    assert stranger.status_code == 404
    assert stranger.json() == missing.json() == {"detail": "score not found"}
    assert stranger.headers["cache-control"] == "private, no-store"
    assert owner.status_code == 200
    assert (await Score.get(id=score_id)).paper_url == PAPER
    assert len(await _events(score_id)) == 1


async def test_patch_private_score_in_disabled_mode_fails_closed(
    disabled_client: AsyncClient,
) -> None:
    # `X-User-Email` is an unverified claim in this mode, and a private board is inert until
    # identity is real (the same rule as `read_identity`): even the claimed owner gets a 404.
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    row = await Score.create(
        spec_id="s",
        url4_expression="url4://x",
        submitted_by="tester",
        score=0.5,
        total_questions=4,
        ran_with_providers=["openai"],
        benchmark_id="private-x",
    )

    response = await disabled_client.patch(
        f"/v1/scores/{row.id}", json={"paper_url": PAPER}, headers=_as("tester")
    )

    assert response.status_code == 404
    assert (await Score.get(id=row.id)).paper_url is None


async def test_patch_of_a_row_stored_with_free_text_is_refused_to_everyone(
    client: AsyncClient,
) -> None:
    # M20: a row stored in `disabled` mode carries free text as `submitted_by`. In
    # cloudflare_headers mode only a verified identity EQUAL to that text may edit it; no email
    # equals "tester", so in practice nobody can.
    row = await Score.create(
        spec_id="s",
        url4_expression="url4://x",
        submitted_by="tester",
        score=0.5,
        total_questions=4,
        ran_with_providers=["openai"],
        benchmark_id="hle",
    )

    response = await client.patch(
        f"/v1/scores/{row.id}", json={"paper_url": PAPER}, headers=_as(ALICE)
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "not_score_owner"


# --- #10 M2: PATCH paper_url updates the row, dates it, and logs exactly one event ---------------


async def test_patch_paper_url_updates_row_sets_metadata_updated_at_and_logs_one_event(
    client: AsyncClient,
) -> None:
    score_id = await _submit(client)

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(ALICE)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == score_id
    assert body["paper_url"] == PAPER
    assert body["metadata_updated_at"]
    stored = await Score.get(id=score_id)
    assert stored.paper_url == PAPER
    assert stored.metadata_updated_at is not None
    (event,) = await _events(score_id)
    assert event.source == "patch"
    assert event.edited_by == ALICE
    assert (event.old_paper_url, event.new_paper_url) == (None, PAPER)
    # A field the request did not change has equal old and new values (here: NULL authors).
    assert (event.old_authors, event.new_authors) == (None, None)


# --- #11 M3, M11: authors are replaced with the SAME validation as POST --------------------------


async def test_patch_authors_replaces_the_list_exactly(client: AsyncClient) -> None:
    score_id = await _submit(client, authors=[ALICE])
    new_authors = [ALICE, BOB, CAROL]

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"authors": new_authors}, headers=_as(ALICE)
    )

    assert response.status_code == 200, response.text
    # The read DTO publishes local parts only (OME-834); the stored list is the exact one sent.
    assert response.json()["authors"] == ["alice", "bob", "carol"]
    assert (await Score.get(id=score_id)).authors == new_authors
    (event,) = await _events(score_id)
    assert (event.old_authors, event.new_authors) == ([ALICE], new_authors)
    assert (event.old_paper_url, event.new_paper_url) == (None, None)


BAD_AUTHORS = [
    pytest.param([], id="empty"),
    pytest.param([f"author-{index}@example.test" for index in range(11)], id="eleven-distinct"),
    pytest.param(["not-an-email"], id="not-email-like"),
    pytest.param(["alice@@example.test"], id="double-at"),
    pytest.param([f"{'a' * 242}@example.test"] * 17, id="over-4096-bytes"),
]


@pytest.mark.parametrize("authors", BAD_AUTHORS)
async def test_patch_rejects_invalid_authors_like_post(
    client: AsyncClient, authors: list[str]
) -> None:
    score_id = await _submit(client, authors=[ALICE])

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"authors": authors}, headers=_as(ALICE)
    )

    assert response.status_code == 422
    assert (await Score.get(id=score_id)).authors == [ALICE]
    assert await _events(score_id) == []


async def test_patch_rejects_an_invalid_paper_url(client: AsyncClient) -> None:
    score_id = await _submit(client)

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": "javascript:alert(1)"}, headers=_as(ALICE)
    )

    assert response.status_code == 422
    assert (await Score.get(id=score_id)).paper_url is None


# --- #12 M18: a PATCH that changes nothing writes nothing ----------------------------------------


async def test_patch_unchanged_values_writes_no_event(client: AsyncClient) -> None:
    score_id = await _submit(client, authors=[ALICE], paper_url=PAPER)

    first = await client.patch(
        f"/v1/scores/{score_id}",
        json={"paper_url": PAPER, "authors": [ALICE]},
        headers=_as(ALICE),
    )

    assert first.status_code == 200
    assert (await _events(score_id)) == []
    assert (await Score.get(id=score_id)).metadata_updated_at is None

    # ...and a retry after a REAL change (a lost response) is a no-op: same stamp, one event.
    changed = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": OTHER_PAPER}, headers=_as(ALICE)
    )
    stamp = (await Score.get(id=score_id)).metadata_updated_at
    retry = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": OTHER_PAPER}, headers=_as(ALICE)
    )

    assert changed.status_code == retry.status_code == 200
    assert retry.json() == changed.json()
    assert (await Score.get(id=score_id)).metadata_updated_at == stamp
    assert len(await _events(score_id)) == 1


# --- #13 M17: absent is "unchanged", paper_url null clears, authors null is a 422 ---------------


async def test_patch_null_paper_url_clears_the_link_and_logs_it(client: AsyncClient) -> None:
    score_id = await _submit(client, authors=[ALICE], paper_url=PAPER)

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": None}, headers=_as(ALICE)
    )

    assert response.status_code == 200, response.text
    assert "paper_url" not in response.json()
    stored = await Score.get(id=score_id)
    assert stored.paper_url is None
    assert stored.authors == [ALICE]  # absent key: unchanged
    (event,) = await _events(score_id)
    assert (event.old_paper_url, event.new_paper_url) == (PAPER, None)
    assert event.old_authors == event.new_authors == [ALICE]


async def test_patch_null_authors_is_422(client: AsyncClient) -> None:
    score_id = await _submit(client, authors=[ALICE])

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"authors": None}, headers=_as(ALICE)
    )

    assert response.status_code == 422
    assert (await Score.get(id=score_id)).authors == [ALICE]


def test_metadata_patch_tells_an_absent_key_from_null() -> None:
    absent = ScoreMetadataPatch.model_validate({"authors": [ALICE]})
    cleared = ScoreMetadataPatch.model_validate({"paper_url": None})

    assert absent.model_fields_set == {"authors"}
    assert cleared.model_fields_set == {"paper_url"} and cleared.paper_url is None
    with pytest.raises(ValidationError):
        ScoreMetadataPatch.model_validate({"authors": None})


# --- #14 M12: an empty body or an unknown field is a 422 -----------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty"),
        pytest.param({"score": 1.0}, id="unknown-only"),
        pytest.param({"paper_url": PAPER, "submitted_by": BOB}, id="known-plus-unknown"),
        pytest.param({"metadata": {"a": 1}}, id="metadata-is-not-editable"),
    ],
)
async def test_patch_unknown_or_empty_body_is_422(
    client: AsyncClient, body: dict[str, Any]
) -> None:
    score_id = await _submit(client)

    response = await client.patch(f"/v1/scores/{score_id}", json=body, headers=_as(ALICE))

    assert response.status_code == 422
    assert await _events(score_id) == []


async def test_patch_a_non_object_body_is_422(client: AsyncClient) -> None:
    score_id = await _submit(client)

    response = await client.patch(f"/v1/scores/{score_id}", json=[PAPER], headers=_as(ALICE))

    assert response.status_code == 422


# --- #15 M14: parallel PATCHes both apply, and the log chains without a gap ----------------------


async def test_concurrent_patches_chain_old_new_values(client: AsyncClient) -> None:
    score_id = await _submit(client, paper_url=PAPER)
    links = [f"https://example.org/paper/{index}" for index in range(6)]

    responses = await asyncio.gather(
        *(
            client.patch(f"/v1/scores/{score_id}", json={"paper_url": link}, headers=_as(ALICE))
            for link in links
        )
    )

    assert [response.status_code for response in responses] == [200] * len(links)
    events = await _events(score_id)
    assert len(events) == len(links)
    # Every event starts where the previous one ended, from the original value to the stored one.
    assert events[0].old_paper_url == PAPER
    for earlier, later in zip(events, events[1:], strict=False):
        assert later.old_paper_url == earlier.new_paper_url
    assert events[-1].new_paper_url == (await Score.get(id=score_id)).paper_url
    assert {event.new_paper_url for event in events} == set(links)


async def test_the_metadata_row_read_really_locks_the_row() -> None:
    """The PATCH re-read must emit `FOR UPDATE` on PostgreSQL, or the event chain can fork.

    Same reasoning as `test_the_replay_row_read_really_locks_the_row`: SQLite does not implement
    the lock, so a behavioural test cannot hold it; rendering the query on the dialect that does is
    the available check.
    """
    await Tortoise.init(
        db_url="asyncpg://user:pass@127.0.0.1:1/unused",
        modules={"models": ["scoreboard.scores.models"]},
        _create_db=False,
    )
    try:
        # The query PRODUCTION runs, not one this test builds.
        locked = ScoreStore().metadata_row_query(uuid4()).sql()
    finally:
        await Tortoise.close_connections()

    assert "FOR UPDATE" in locked.upper(), f"the PATCH re-read lost its lock: {locked}"


# --- #17 M19: editing does not move the frontier -------------------------------------------------


async def test_patch_does_not_touch_enriched_at_or_ranking(client: AsyncClient) -> None:
    low = await _submit(client, ALICE, spec_id="low", score=0.5, url4_expression="url4://low")
    await _submit(client, BOB, spec_id="high", score=0.9, url4_expression="url4://high")
    await Score.filter(id=low).update(enriched_at=(await Score.get(id=low)).submitted_at)
    before_row = await Score.get(id=low)
    before_board = (await client.get("/v1/leaderboard/hle")).json()

    response = await client.patch(
        f"/v1/scores/{low}",
        json={"paper_url": PAPER, "authors": [ALICE, CAROL]},
        headers=_as(ALICE),
    )

    assert response.status_code == 200, response.text
    after_row = await Score.get(id=low)
    for column in ("enriched_at", "content_hash", "score", "run_cost_usd", "submitted_at"):
        assert getattr(after_row, column) == getattr(before_row, column), column
    after_board = (await client.get("/v1/leaderboard/hle")).json()

    def ranked(board: dict[str, Any]) -> list[tuple[Any, ...]]:
        return [(entry["spec_id"], entry["score"], entry["rank"]) for entry in board["entries"]]

    assert ranked(after_board) == ranked(before_board)
    assert [entry[0] for entry in ranked(after_board)] == ["high", "low"]


# --- observability: log the score id and field NAMES, never the email values --------------------


async def test_patch_logs_the_score_id_and_changed_field_names_but_no_emails(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    score_id = await _submit(client)

    with caplog.at_level(logging.INFO):
        await client.patch(
            f"/v1/scores/{score_id}",
            json={"paper_url": PAPER, "authors": [ALICE, BOB]},
            headers=_as(ALICE),
        )

    text = " ".join(record.getMessage() for record in caplog.records)
    assert score_id in text and "paper_url" in text and "authors" in text
    assert ALICE not in text and BOB not in text


# --- an unavailable store is a 503, like the other score routes ----------------------------------


async def test_patch_store_unavailable_is_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    score_id = await _submit(client)

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise OperationalError("database is down")

    monkeypatch.setattr(Score, "get_or_none", unavailable)
    response = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(ALICE)
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "score store unavailable"}
