"""Route tests for the E14a metadata edit: `PATCH /v1/scores/{id}` and its history.

FEATURE: OME-1307 (E14a) — MD-1, MD-3 to MD-10, MD-13 to MD-18 (PRD `prd/edit-metadata.md` §7).

Main-path tests run in `cloudflare_headers` mode, the production mode (D5). Each flow has exactly
one test for the `disabled` dev/local fallback: MD-4a (PATCH) and MD-17a (history).
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
from scoreboard.routes.dependencies import PRIVATE_CACHE_HEADERS
from scoreboard.routes.scores import SCORE_NOT_FOUND_DETAIL, UNTRUSTED_PEER_DETAIL
from scoreboard.scores import metadata_store
from scoreboard.scores.models import Benchmark, ReportedResult, Score, ScoreMetadataEvent

pytestmark = pytest.mark.asyncio

ANA = "ana@x.org"
BRUNO = "bruno@y.org"
CAROL = "carol@z.org"
PUBLIC_BOARD = "hle"
PRIVATE_BOARD = "secret"


def as_user(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": PUBLIC_BOARD,
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.75,
        "total_questions": 4,
        "correct_questions": 3,
        "ran_with_providers": ["openai"],
        "run_cost_usd": "1.250000",
        "run_cost_status": "complete",
    }
    payload.update(overrides)
    return payload


async def _create_boards() -> None:
    await Benchmark.create(id=PUBLIC_BOARD, display_name="Humanity's Last Exam")
    await Benchmark.create(id=PRIVATE_BOARD, display_name="Secret", visibility="private")


@pytest_asyncio.fixture
async def cf_app(tortoise_db: None, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # WHY FORWARDED_ALLOW_IPS is pinned: unset, uvicorn's default "127.0.0.1" is the SAME address
    # as allowed_networks below, and create_app refuses that overlap. ASGITransport reports the
    # peer 127.0.0.1, so allowed_networks must contain it and FORWARDED_ALLOW_IPS must not.
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
    await _create_boards()
    return app


@pytest_asyncio.fixture
async def cf_client(cf_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=cf_app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def untrusted_cf_client(cf_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    # A peer outside allowed_networks (127.0.0.1/32): the untrusted-peer 403 path.
    async with AsyncClient(
        transport=ASGITransport(app=cf_app, client=("203.0.113.5", 443)),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def score_client(tortoise_db: None) -> AsyncGenerator[AsyncClient, None]:
    """The `disabled` dev/local fallback app. Only MD-4a and MD-17a use it."""
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    await _create_boards()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _seed(
    client: AsyncClient, *, owner: str, visibility: str = "public", **overrides: Any
) -> dict[str, Any]:
    board = PRIVATE_BOARD if visibility == "private" else PUBLIC_BOARD
    response = await client.post(
        "/v1/scores",
        json=_payload(benchmark_id=board, **overrides),
        headers=as_user(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _patch(
    client: AsyncClient,
    score_id: str | UUID,
    body: Any,
    *,
    revision: int | str | None = 1,
    caller: str | None = ANA,
    if_match: str | None = None,
) -> Any:
    headers = as_user(caller) if caller is not None else {}
    if if_match is not None:
        headers["If-Match"] = if_match
    elif revision is not None:
        headers["If-Match"] = f'"{revision}"'
    return await client.patch(f"/v1/scores/{score_id}", json=body, headers=headers)


async def _events(score_id: str | UUID) -> list[ScoreMetadataEvent]:
    return await ScoreMetadataEvent.filter(score_id=score_id).order_by("to_revision")


async def _direct_score(*, board: str, owner: str) -> Score:
    return await Score.create(
        benchmark_id=board,
        spec_id="direct",
        url4_expression="url4://direct",
        submitted_by=owner,
        score=0.5,
        total_questions=2,
        ran_with_providers=["openai"],
        content_hash=f"direct-{uuid4()}",
    )


async def test_md1_char_resubmit_by_another_submitter_ignores_new_authors(
    cf_client: AsyncClient,
) -> None:
    """CHAR (passes on today's code): another submitter's replay never rewrites the credit.

    OD-M1: the same-OWNER replay path (OME-1054) is a different case and stays unchanged.
    """
    first = await _seed(cf_client, owner=ANA, authors=[ANA])

    replay = await cf_client.post(
        "/v1/scores", json=_payload(authors=[BRUNO]), headers=as_user(BRUNO)
    )

    assert replay.status_code == 200
    assert replay.json()["id"] == first["id"]
    assert replay.json()["authors"] == ["ana"]
    stored = await Score.get(id=first["id"])
    assert stored.authors == [ANA]
    assert stored.submitted_by == ANA


async def test_md3_patch_by_non_owner_is_403_public_404_private_no_change(
    cf_client: AsyncClient,
) -> None:
    public = await _seed(cf_client, owner=ANA, authors=[ANA])
    private = await _seed(cf_client, owner=ANA, visibility="private", spec_id="secret-spec")

    refused = await _patch(cf_client, public["id"], {"authors": [BRUNO]}, caller=BRUNO)
    hidden = await _patch(cf_client, private["id"], {"authors": [BRUNO]}, caller=BRUNO)

    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "not_submission_owner"
    # INVARIANT (OME-894): the private refusal is the SAME 404 an unknown score gets.
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": SCORE_NOT_FOUND_DETAIL}
    for header, value in PRIVATE_CACHE_HEADERS.items():
        assert hidden.headers[header] == value
    unknown = await _patch(cf_client, uuid4(), {"authors": [BRUNO]}, caller=BRUNO)
    assert unknown.status_code == 404
    assert unknown.json() == hidden.json()
    for row_id in (public["id"], private["id"]):
        row = await Score.get(id=row_id)
        assert row.metadata_revision == 1
        assert await _events(row_id) == []
    assert (await Score.get(id=public["id"])).authors == [ANA]
    assert (await Score.get(id=private["id"])).authors is None


async def test_md4_patch_unverified_identity_401_except_disabled_mode(
    cf_client: AsyncClient, untrusted_cf_client: AsyncClient
) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    anonymous = await _patch(cf_client, seeded["id"], {"authors": [ANA]}, caller=None)
    blank = await cf_client.patch(
        f"/v1/scores/{seeded['id']}",
        json={"authors": [ANA]},
        headers={"X-User-Email": "  ", "If-Match": '"1"'},
    )
    untrusted = await _patch(untrusted_cf_client, seeded["id"], {"authors": [ANA]}, caller=ANA)
    # INVARIANT: identity is decided before the body and before If-Match are looked at.
    no_precondition = await _patch(
        cf_client, seeded["id"], {"score": 1}, caller=None, revision=None
    )

    for refused in (anonymous, blank, no_precondition):
        assert refused.status_code == 401
        assert refused.json()["detail"]["code"] == "identity_not_verified"
    assert untrusted.status_code == 403
    # INVARIANT: the peer check comes BEFORE the header read, and keeps its plain string.
    assert untrusted.json() == {"detail": UNTRUSTED_PEER_DETAIL}
    assert (await Score.get(id=seeded["id"])).metadata_revision == 1
    assert await _events(seeded["id"]) == []


async def test_md4a_disabled_fallback_public_edit_ok_actor_null_private_404(
    score_client: AsyncClient,
) -> None:
    """The ONLY `disabled`-mode test of the PATCH flow (D5): today's dev/local behaviour."""
    created = await score_client.post("/v1/scores", json=_payload(submitted_by="tester"))
    assert created.status_code == 201
    private = await _direct_score(board=PRIVATE_BOARD, owner=ANA)

    edited = await _patch(score_client, created.json()["id"], {"authors": [ANA]}, caller=None)
    hidden = await _patch(score_client, private.id, {"authors": [BRUNO]}, caller=None)
    forged = await _patch(score_client, private.id, {"authors": [BRUNO]}, caller=ANA)

    assert edited.status_code == 200
    assert edited.json()["metadata_revision"] == 2
    events = await _events(created.json()["id"])
    assert len(events) == 1
    assert events[0].actor is None
    for refused in (hidden, forged):
        assert refused.status_code == 404
        assert refused.json() == {"detail": SCORE_NOT_FOUND_DETAIL}
    assert await _events(private.id) == []


async def test_md5_patch_owner_adds_authors_bumps_revision_and_etag(
    cf_client: AsyncClient,
) -> None:
    seeded = await _seed(cf_client, owner=ANA, authors=[ANA])

    response = await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO, CAROL]})

    assert response.status_code == 200
    body = response.json()
    # Published form: the local part only, as on every other read (OME-834).
    assert body["authors"] == ["ana", "bruno", "carol"]
    assert body["metadata_revision"] == 2
    assert body["metadata_updated_at"]
    assert response.headers["ETag"] == '"2"'
    stored = await Score.get(id=seeded["id"])
    assert stored.authors == [ANA, BRUNO, CAROL]
    assert stored.metadata_revision == 2
    (event,) = await _events(seeded["id"])
    assert (event.actor, event.from_revision, event.to_revision) == (ANA, 1, 2)
    fetched = await cf_client.get(f"/v1/scores/{seeded['id']}", headers=as_user(ANA))
    assert fetched.json()["authors"] == ["ana", "bruno", "carol"]


async def test_md5_patch_paper_url_alone_leaves_authors_untouched(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA, authors=[ANA, BRUNO])

    response = await _patch(cf_client, seeded["id"], {"paper_url": "https://doi.org/10.1234/abc"})

    assert response.status_code == 200
    assert response.json()["paper_url"] == "https://doi.org/10.1234/abc"
    assert (await Score.get(id=seeded["id"])).authors == [ANA, BRUNO]


async def test_md6_concurrent_patches_one_wins_one_412(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    results = await asyncio.gather(
        _patch(cf_client, seeded["id"], {"paper_url": "https://x.org/one"}),
        _patch(cf_client, seeded["id"], {"paper_url": "https://x.org/two"}),
    )

    assert sorted(response.status_code for response in results) == [200, 412]
    assert (await Score.get(id=seeded["id"])).metadata_revision == 2
    assert len(await _events(seeded["id"])) == 1


async def test_md7_stale_if_match_412_with_current_state(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA, authors=[ANA])
    assert (await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]}, revision=1)).is_success
    assert (
        await _patch(cf_client, seeded["id"], {"paper_url": "https://x.org/p"}, revision=2)
    ).is_success

    stale = await _patch(cf_client, seeded["id"], {"authors": [CAROL]}, revision=2)

    assert stale.status_code == 412
    detail = stale.json()["detail"]
    assert detail["code"] == "metadata_revision_conflict"
    # OD-M4: the current state is in the published (local-part) form.
    assert detail["current"] == {
        "metadata_revision": 3,
        "authors": ["ana", "bruno"],
        "paper_url": "https://x.org/p",
    }
    assert (await Score.get(id=seeded["id"])).authors == [ANA, BRUNO]
    assert len(await _events(seeded["id"])) == 2


@pytest.mark.parametrize("if_match", ["0", '"0"', '"01"', 'W/"2"', "2", '"abc"', '"12345678901"'])
async def test_md7_malformed_if_match_is_a_conflict_with_current_state(
    cf_client: AsyncClient, if_match: str
) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    response = await _patch(
        cf_client, seeded["id"], {"paper_url": "https://x.org/p"}, if_match=if_match
    )

    assert response.status_code == 412
    assert response.json()["detail"]["current"]["metadata_revision"] == 1
    assert (await Score.get(id=seeded["id"])).paper_url is None


@pytest.mark.parametrize("if_match", [None, "*", "", "  "])
async def test_md8_missing_if_match_428(cf_client: AsyncClient, if_match: str | None) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    response = await _patch(
        cf_client,
        seeded["id"],
        {"authors": [ANA, BRUNO]},
        revision=None,
        if_match=if_match,
    )

    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "precondition_required"
    assert (await Score.get(id=seeded["id"])).metadata_revision == 1


async def test_md9_edit_does_not_change_content_hash_score_or_rank(
    cf_client: AsyncClient,
) -> None:
    seeded = await _seed(cf_client, owner=ANA, authors=[ANA])
    await _seed(cf_client, owner=BRUNO, spec_id="spec-2", score=0.5)

    def _ranks(board: dict[str, Any]) -> list[tuple[int, str, float]]:
        return [(row["rank"], row["spec_id"], row["score"]) for row in board["entries"]]

    before_row = await Score.get(id=seeded["id"])
    before_board = (await cf_client.get(f"/v1/leaderboard/{PUBLIC_BOARD}")).json()

    response = await _patch(
        cf_client,
        seeded["id"],
        {"authors": [ANA, BRUNO], "paper_url": "https://arxiv.org/abs/2609.01234"},
    )

    assert response.status_code == 200
    after_row = await Score.get(id=seeded["id"])
    assert (after_row.content_hash, after_row.score, after_row.spec_id) == (
        before_row.content_hash,
        before_row.score,
        before_row.spec_id,
    )
    after_board = (await cf_client.get(f"/v1/leaderboard/{PUBLIC_BOARD}")).json()
    assert _ranks(after_board) == _ranks(before_board)
    # MD-D5: the edit does show on the board, with the published authors and the link.
    edited = next(row for row in after_board["entries"] if row["spec_id"] == "spec-1")
    assert edited["authors"] == ["ana", "bruno"]
    assert edited["paper_url"] == "https://arxiv.org/abs/2609.01234"


async def test_md10_history_event_written_in_same_transaction(
    cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed(cf_client, owner=ANA, authors=[ANA])

    async def _fail(*args: object, **kwargs: object) -> None:
        raise OperationalError("event insert failed")

    monkeypatch.setattr(ScoreMetadataEvent, "create", _fail)

    response = await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]})

    assert response.status_code == 503
    stored = await Score.get(id=seeded["id"])
    # INVARIANT (MD-D3): the failed event insert rolled the row update back with it.
    assert stored.metadata_revision == 1
    assert stored.authors == [ANA]
    assert stored.metadata_updated_at is None


async def test_md13_patch_null_clears_paper_url_and_resets_authors_default(
    cf_client: AsyncClient,
) -> None:
    seeded = await _seed(
        cf_client, owner=ANA, authors=[ANA, BRUNO], paper_url="https://arxiv.org/abs/1"
    )

    cleared = await _patch(cf_client, seeded["id"], {"paper_url": None}, revision=1)
    fetched = await cf_client.get(f"/v1/scores/{seeded['id']}", headers=as_user(ANA))
    assert cleared.status_code == 200
    assert "paper_url" not in fetched.json()
    assert fetched.json()["authors"] == ["ana", "bruno"]

    reset = await _patch(cf_client, seeded["id"], {"authors": None}, revision=2)
    board = (await cf_client.get(f"/v1/leaderboard/{PUBLIC_BOARD}")).json()
    assert reset.status_code == 200
    # NULL again: the reads that derive a credit line show [submitted_by], in the published form.
    # WHY not `GET /v1/scores/{id}`: it returns the stored value as it is (`authors: null`), and
    # this unit does not change it.
    assert reset.json()["authors"] == ["ana"]
    assert board["entries"][0]["authors"] == ["ana"]
    assert (await Score.get(id=seeded["id"])).authors is None


async def test_md14_patch_immutable_field_422(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    single = await _patch(cf_client, seeded["id"], {"score": 1})
    mixed = await _patch(
        cf_client,
        seeded["id"],
        {"url4_expression": "x", "submitted_by": BRUNO, "paper_url": "https://x.org"},
    )

    for response, fields in ((single, ["score"]), (mixed, ["submitted_by", "url4_expression"])):
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "field_not_editable"
        assert response.json()["detail"]["fields"] == fields
    stored = await Score.get(id=seeded["id"])
    assert (stored.metadata_revision, stored.paper_url, stored.score) == (1, None, 0.75)
    assert await _events(seeded["id"]) == []


async def test_md15_idempotent_resend_same_values_200_no_event(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA)
    body = {"authors": [ANA, BRUNO], "paper_url": "https://x.org/p"}
    first = await _patch(cf_client, seeded["id"], body, revision=1)
    assert first.json()["metadata_revision"] == 2

    resend = await _patch(cf_client, seeded["id"], body, revision=1)

    assert resend.status_code == 200
    assert resend.json()["metadata_revision"] == 2
    assert resend.headers["ETag"] == '"2"'
    assert len(await _events(seeded["id"])) == 1


@pytest.mark.parametrize("body", [{}, {"authors": None}, {"paper_url": None}])
async def test_md15_empty_or_unchanged_patch_is_a_200_no_op(
    cf_client: AsyncClient, body: dict[str, Any]
) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    response = await _patch(cf_client, seeded["id"], body, revision=1)

    assert response.status_code == 200
    assert response.json()["metadata_revision"] == 1
    assert await _events(seeded["id"]) == []


async def test_md15_a_case_change_of_an_author_is_an_edit(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA, authors=["Ana@x.org"])

    response = await _patch(cf_client, seeded["id"], {"authors": ["ana@x.org"]})

    assert response.json()["metadata_revision"] == 2
    assert (await Score.get(id=seeded["id"])).authors == ["ana@x.org"]


async def test_md16_submit_accepts_paper_url(cf_client: AsyncClient) -> None:
    created = await cf_client.post(
        "/v1/scores",
        json=_payload(paper_url="https://arxiv.org/abs/2609.01234"),
        headers=as_user(ANA),
    )
    rejected = await cf_client.post(
        "/v1/scores",
        json=_payload(spec_id="spec-bad", paper_url="javascript:alert(1)"),
        headers=as_user(ANA),
    )

    assert created.status_code == 201
    fetched = await cf_client.get(f"/v1/scores/{created.json()['id']}", headers=as_user(ANA))
    assert fetched.json()["paper_url"] == "https://arxiv.org/abs/2609.01234"
    assert fetched.json()["metadata_revision"] == 1
    assert rejected.status_code == 422


async def test_md16_paper_url_is_not_part_of_the_recipe_identity(cf_client: AsyncClient) -> None:
    """INVARIANT (I-S3): metadata is not identity, so it never splits or rewrites a row."""
    first = await _seed(cf_client, owner=ANA, paper_url="https://x.org/one")

    again = await cf_client.post(
        "/v1/scores", json=_payload(paper_url="https://x.org/two"), headers=as_user(ANA)
    )

    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert (await Score.get(id=first["id"])).paper_url == "https://x.org/one"


async def test_md16_a_row_without_paper_url_keeps_its_read_shape(cf_client: AsyncClient) -> None:
    """`paper_url` is absent, never null, so existing board and history payloads keep their keys."""
    seeded = await _seed(cf_client, owner=ANA)

    board = (await cf_client.get(f"/v1/leaderboard/{PUBLIC_BOARD}")).json()
    history = (await cf_client.get(f"/v1/leaderboard/{PUBLIC_BOARD}/spec-1/history")).json()

    assert seeded["metadata_revision"] == 1
    assert "paper_url" not in seeded
    assert "paper_url" not in board["entries"][0]
    assert "paper_url" not in history["submissions"][0]


async def test_md16_board_and_history_show_a_set_paper_url(cf_client: AsyncClient) -> None:
    await _seed(cf_client, owner=ANA, paper_url="https://arxiv.org/abs/2609.01234")

    board = (await cf_client.get(f"/v1/leaderboard/{PUBLIC_BOARD}")).json()
    history = (await cf_client.get(f"/v1/leaderboard/{PUBLIC_BOARD}/spec-1/history")).json()

    assert board["entries"][0]["paper_url"] == "https://arxiv.org/abs/2609.01234"
    assert history["submissions"][0]["paper_url"] == "https://arxiv.org/abs/2609.01234"


async def test_md17_metadata_history_lists_newest_first_paged(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA, authors=[ANA])
    url = f"/v1/scores/{seeded['id']}/metadata-history"
    assert (await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]}, revision=1)).is_success
    assert (
        await _patch(cf_client, seeded["id"], {"paper_url": "https://x.org/p"}, revision=2)
    ).is_success
    assert (await _patch(cf_client, seeded["id"], {"paper_url": None}, revision=3)).is_success

    first = await cf_client.get(url, params={"limit": 2}, headers=as_user(ANA))
    second = await cf_client.get(url, params={"limit": 2, "cursor": "3"}, headers=as_user(ANA))

    assert first.status_code == 200
    page = first.json()
    assert [event["to_revision"] for event in page["events"]] == [4, 3]
    assert page["next_cursor"] == "3"
    newest = page["events"][0]
    assert (newest["actor"], newest["from_revision"]) == ("ana", 3)
    assert newest["at"]
    assert newest["before"] == {"authors": ["ana", "bruno"], "paper_url": "https://x.org/p"}
    assert newest["after"] == {"authors": ["ana", "bruno"], "paper_url": None}
    assert page["events"][1]["before"] == {"authors": ["ana", "bruno"], "paper_url": None}
    assert page["events"][1]["after"] == {
        "authors": ["ana", "bruno"],
        "paper_url": "https://x.org/p",
    }
    rest = second.json()
    assert [event["to_revision"] for event in rest["events"]] == [2]
    assert rest["next_cursor"] is None
    assert rest["events"][0]["before"] == {"authors": ["ana"], "paper_url": None}


async def test_md17_history_of_a_public_score_is_readable_by_anyone(
    cf_client: AsyncClient,
) -> None:
    seeded = await _seed(cf_client, owner=ANA)
    assert (await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]})).is_success
    url = f"/v1/scores/{seeded['id']}/metadata-history"

    response = await cf_client.get(url)

    assert response.status_code == 200
    assert len(response.json()["events"]) == 1
    assert "Cache-Control" not in response.headers


async def test_md17_history_of_a_private_score_belongs_to_its_owner(
    cf_client: AsyncClient,
) -> None:
    seeded = await _seed(cf_client, owner=ANA, visibility="private")
    assert (await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]})).is_success
    url = f"/v1/scores/{seeded['id']}/metadata-history"

    other = await cf_client.get(url, headers=as_user(BRUNO))
    anonymous = await cf_client.get(url)
    owner = await cf_client.get(url, headers=as_user(ANA))
    unknown = await cf_client.get(f"/v1/scores/{uuid4()}/metadata-history", headers=as_user(BRUNO))

    for refused in (other, anonymous):
        assert refused.status_code == 404
        assert refused.json() == {"detail": SCORE_NOT_FOUND_DETAIL}
        for header, value in PRIVATE_CACHE_HEADERS.items():
            assert refused.headers[header] == value
    assert unknown.status_code == 404
    assert unknown.json() == other.json()
    assert owner.status_code == 200
    assert len(owner.json()["events"]) == 1
    assert owner.headers["Cache-Control"] == PRIVATE_CACHE_HEADERS["Cache-Control"]


@pytest.mark.parametrize("cursor", ["0", "01", "abc", "-1", "12345678901", ""])
async def test_md17_history_rejects_a_malformed_cursor(cf_client: AsyncClient, cursor: str) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    response = await cf_client.get(
        f"/v1/scores/{seeded['id']}/metadata-history",
        params={"cursor": cursor},
        headers=as_user(ANA),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_cursor"


async def test_md17_history_of_an_unedited_score_is_empty(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    response = await cf_client.get(f"/v1/scores/{seeded['id']}/metadata-history")

    assert response.json() == {"events": [], "next_cursor": None}


async def test_md17a_disabled_fallback_history_public_readable_private_404(
    score_client: AsyncClient,
) -> None:
    """The ONLY `disabled`-mode test of the history flow (D5)."""
    created = await score_client.post("/v1/scores", json=_payload(submitted_by="tester"))
    private = await _direct_score(board=PRIVATE_BOARD, owner=ANA)

    public = await score_client.get(f"/v1/scores/{created.json()['id']}/metadata-history")
    anonymous = await score_client.get(f"/v1/scores/{private.id}/metadata-history")
    forged = await score_client.get(
        f"/v1/scores/{private.id}/metadata-history", headers=as_user(ANA)
    )

    assert public.status_code == 200
    # `ReadIdentity` ignores a header in `disabled` mode, so a forged owner reads nothing.
    for refused in (anonymous, forged):
        assert refused.status_code == 404
        assert refused.json() == {"detail": SCORE_NOT_FOUND_DETAIL}


async def test_md18_reporter_of_cluster_cannot_edit_head(cf_client: AsyncClient) -> None:
    seeded = await _seed(cf_client, owner=ANA)
    head = await Score.get(id=seeded["id"])
    await ReportedResult.create(
        head=head,
        is_original=False,
        reporter=BRUNO,
        score=0.7,
        total_questions=4,
    )

    reporter = await _patch(cf_client, seeded["id"], {"authors": [BRUNO]}, caller=BRUNO)
    owner = await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]}, caller=ANA)

    assert reporter.status_code == 403
    assert reporter.json()["detail"]["code"] == "not_submission_owner"
    assert owner.status_code == 200
    assert (await Score.get(id=seeded["id"])).authors == [ANA, BRUNO]


async def test_md_invalid_values_422_invalid_metadata_with_submit_messages(
    cf_client: AsyncClient,
) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    bad_url = await _patch(cf_client, seeded["id"], {"paper_url": "javascript:alert(1)"})
    bad_authors = await _patch(
        cf_client, seeded["id"], {"authors": [f"p{i}@x.org" for i in range(11)]}
    )
    empty_authors = await _patch(cf_client, seeded["id"], {"authors": []})
    bad_email = await _patch(cf_client, seeded["id"], {"authors": ["nope"]})

    for response in (bad_url, bad_authors, empty_authors, bad_email):
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_metadata"
    assert bad_url.json()["detail"]["errors"] == [
        {"field": "paper_url", "message": "paper_url must be an absolute http or https URL"}
    ]
    assert bad_authors.json()["detail"]["errors"] == [
        {"field": "authors", "message": "authors must credit at most 10 distinct people"}
    ]
    assert empty_authors.json()["detail"]["errors"][0]["field"] == "authors"
    assert bad_email.json()["detail"]["errors"][0]["field"] == "authors"
    assert (await Score.get(id=seeded["id"])).metadata_revision == 1
    assert await _events(seeded["id"]) == []


async def test_md_a_legacy_row_at_revision_one_is_editable(cf_client: AsyncClient) -> None:
    legacy = await _direct_score(board=PUBLIC_BOARD, owner=ANA)

    response = await _patch(cf_client, legacy.id, {"authors": [ANA, BRUNO]})

    assert response.status_code == 200
    assert response.json()["metadata_revision"] == 2


async def test_md_edit_logs_counts_and_never_emails(
    cf_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    seeded = await _seed(cf_client, owner=ANA)

    with caplog.at_level(logging.INFO):
        response = await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]})

    assert response.status_code == 200
    (record,) = [r for r in caplog.records if r.getMessage() == "score metadata edited"]
    assert getattr(record, "author_count") == 2
    assert getattr(record, "actor_is_owner") is True
    assert getattr(record, "score_id") == seeded["id"]
    assert "@" not in caplog.text


@pytest.mark.parametrize("caller", [None, BRUNO])
async def test_md17_history_of_a_board_that_turns_private_mid_read_is_the_plain_404(
    cf_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caller: str | None
) -> None:
    """INVARIANT (OME-894): the visibility decided first is re-checked before a public answer.

    The board flips to private right after the store reads its visibility and before the events
    query. Without the re-check the anonymous caller gets the edit history (raw-derived authors and
    actor) of a board that is private by the time it answers.
    """
    seeded = await _seed(cf_client, owner=ANA)
    assert (await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]})).is_success
    real_get_or_none = Benchmark.get_or_none

    async def flip_after_the_read(*args: Any, **kwargs: Any) -> Benchmark | None:
        board = await real_get_or_none(*args, **kwargs)
        await Benchmark.filter(id=PUBLIC_BOARD).update(visibility="private")
        return board

    monkeypatch.setattr(metadata_store.Benchmark, "get_or_none", flip_after_the_read)
    headers = as_user(caller) if caller is not None else {}

    response = await cf_client.get(f"/v1/scores/{seeded['id']}/metadata-history", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": SCORE_NOT_FOUND_DETAIL}
    for header, value in PRIVATE_CACHE_HEADERS.items():
        assert response.headers[header] == value


async def test_md17_history_of_a_public_score_is_cacheable_for_an_identified_reader(
    cf_client: AsyncClient,
) -> None:
    """The private cache policy follows the real visibility, not whether a caller is known."""
    seeded = await _seed(cf_client, owner=ANA)
    assert (await _patch(cf_client, seeded["id"], {"authors": [ANA, BRUNO]})).is_success

    response = await cf_client.get(
        f"/v1/scores/{seeded['id']}/metadata-history", headers=as_user(BRUNO)
    )

    assert response.status_code == 200
    assert "Cache-Control" not in response.headers
