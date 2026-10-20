"""Author and paper metadata through the API: submit, PATCH, same-owner resubmit, the edit log,
the public read and the staff export (spec sections 2 to 4).

FEATURE: a submitter attaches `authors_metadata` and `paper_metadata` to a score and edits them
through the existing owner-only paths. Every check compares parsed JSON or model fields.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.export_private_submissions import collect_submissions, format_jsonl
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent

pytestmark = pytest.mark.asyncio

ALICE = "alice@example.test"
BOB = "bob@lab.test"
CAROL = "carol@example.test"
PAPER = "https://arxiv.org/abs/2610.01234"
OTHER_PAPER = "https://doi.org/10.1000/xyz"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.75,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


async def _post(http: AsyncClient, owner: str = ALICE, **overrides: Any) -> Any:
    return await http.post("/v1/scores", json=_payload(**overrides), headers=_as(owner))


async def _submit(http: AsyncClient, owner: str = ALICE, **overrides: Any) -> str:
    created = await _post(http, owner, **overrides)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _error_locs(response: Any) -> list[list[Any]]:
    return [error["loc"] for error in response.json()["detail"]]


async def _events(score_id: str) -> list[ScoreMetadataEvent]:
    return await ScoreMetadataEvent.filter(score_id=score_id).order_by("edited_at")


# --- submit -------------------------------------------------------------------------------------


async def test_submit_stores_both_objects_with_the_url_in_paper_url(client: AsyncClient) -> None:
    score_id = await _submit(
        client,
        authors=[ALICE, BOB],
        authors_metadata={BOB: {"full_name": "Bo", "orcid": "0000"}},
        paper_metadata={"title": "A study", "url": PAPER, "pages": 12},
    )

    stored = await Score.get(id=score_id)
    assert stored.authors_metadata == {BOB: {"full_name": "Bo", "orcid": "0000"}}
    assert stored.paper_metadata == {"title": "A study", "pages": 12}
    assert stored.paper_url == PAPER


async def test_a_url_alone_in_paper_metadata_stores_an_empty_object(client: AsyncClient) -> None:
    score_id = await _submit(client, paper_metadata={"url": PAPER})

    stored = await Score.get(id=score_id)
    assert (stored.paper_metadata, stored.paper_url) == ({}, PAPER)
    read = (await client.get(f"/v1/scores/{score_id}")).json()
    assert read["paper_metadata"] == {"url": PAPER}


async def test_submit_with_a_key_outside_the_authors_is_422_naming_it(client: AsyncClient) -> None:
    response = await _post(
        client, authors=[ALICE], authors_metadata={ALICE: {}, CAROL: {"full_name": "C"}}
    )

    assert response.status_code == 422
    assert _error_locs(response) == [["body", "authors_metadata", CAROL]]
    assert await Score.all().count() == 0


async def test_submit_without_authors_matches_the_submitter(client: AsyncClient) -> None:
    # Owner, 2026-10-15 (c): with no `authors`, the credit line is [submitted_by].
    score_id = await _submit(client, authors_metadata={ALICE: {"full_name": "Alice"}})
    refused = await _post(
        client, spec_id="spec-2", authors_metadata={CAROL: {"full_name": "Carol"}}
    )

    assert (await Score.get(id=score_id)).authors_metadata == {ALICE: {"full_name": "Alice"}}
    assert refused.status_code == 422
    assert _error_locs(refused) == [["body", "authors_metadata", CAROL]]


async def test_submit_with_bad_values_reports_each_problem(client: AsyncClient) -> None:
    response = await _post(
        client,
        authors=[ALICE],
        authors_metadata={ALICE: {"full_name": "n" * 201}},
        paper_metadata={"title": 3, "venue": ["x"]},
    )

    assert response.status_code == 422
    assert sorted(_error_locs(response)) == sorted(
        [
            ["body", "authors_metadata", ALICE, "full_name"],
            ["body", "paper_metadata", "title"],
            ["body", "paper_metadata", "venue"],
        ]
    )


# --- public read and staff export ---------------------------------------------------------------


async def test_public_read_masks_keys_and_the_export_keeps_them(client: AsyncClient) -> None:
    score_id = await _submit(
        client,
        authors=[ALICE, BOB],
        authors_metadata={ALICE: {"full_name": "Alice A"}, BOB: {"institution": "Lab"}},
        paper_metadata={"title": "A study", "url": PAPER},
    )

    public = (await client.get(f"/v1/scores/{score_id}")).json()
    exported = json.loads(format_jsonl(await collect_submissions("hle")))

    assert public["authors_metadata"] == {
        "alice": {"full_name": "Alice A"},
        "bob": {"institution": "Lab"},
    }
    assert public["paper_metadata"] == {"title": "A study", "url": PAPER}
    assert exported["authors_metadata"] == {
        ALICE: {"full_name": "Alice A"},
        BOB: {"institution": "Lab"},
    }
    assert exported["paper_metadata"] == {"title": "A study", "url": PAPER}


async def test_a_score_without_metadata_reads_and_exports_without_either_key(
    client: AsyncClient,
) -> None:
    score_id = await _submit(client, paper_url=PAPER)

    public = (await client.get(f"/v1/scores/{score_id}")).json()
    exported = json.loads(format_jsonl(await collect_submissions("hle")))

    for body in (public, exported):
        assert "authors_metadata" not in body
        assert "paper_metadata" not in body
        assert body["paper_url"] == PAPER


# --- PATCH ---------------------------------------------------------------------------------------


async def test_patch_replaces_the_whole_object_and_logs_before_and_after(
    client: AsyncClient,
) -> None:
    score_id = await _submit(
        client,
        authors=[ALICE, BOB],
        authors_metadata={ALICE: {"full_name": "Alice", "orcid": "1"}},
        paper_metadata={"title": "Old", "url": PAPER},
    )

    response = await client.patch(
        f"/v1/scores/{score_id}",
        json={
            "authors_metadata": {BOB: {"full_name": "Bo"}},
            "paper_metadata": {"title": "New", "url": OTHER_PAPER},
        },
        headers=_as(ALICE),
    )

    assert response.status_code == 200, response.text
    stored = await Score.get(id=score_id)
    assert stored.authors_metadata == {BOB: {"full_name": "Bo"}}
    assert (stored.paper_metadata, stored.paper_url) == ({"title": "New"}, OTHER_PAPER)
    [event] = await _events(score_id)
    assert event.source == "patch"
    assert event.old_authors_metadata == {ALICE: {"full_name": "Alice", "orcid": "1"}}
    assert event.new_authors_metadata == {BOB: {"full_name": "Bo"}}
    assert (event.old_paper_metadata, event.new_paper_metadata) == (
        {"title": "Old"},
        {"title": "New"},
    )
    assert (event.old_paper_url, event.new_paper_url) == (PAPER, OTHER_PAPER)


async def test_patch_paper_metadata_without_url_clears_the_link(client: AsyncClient) -> None:
    score_id = await _submit(client, paper_metadata={"title": "T", "url": PAPER})

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_metadata": {"title": "T"}}, headers=_as(ALICE)
    )

    assert response.status_code == 200, response.text
    stored = await Score.get(id=score_id)
    assert (stored.paper_metadata, stored.paper_url) == ({"title": "T"}, None)


async def test_patch_null_clears_both_objects_and_the_link(client: AsyncClient) -> None:
    score_id = await _submit(
        client,
        authors_metadata={ALICE: {"full_name": "Alice"}},
        paper_metadata={"title": "T", "url": PAPER},
    )

    response = await client.patch(
        f"/v1/scores/{score_id}",
        json={"authors_metadata": None, "paper_metadata": None},
        headers=_as(ALICE),
    )

    assert response.status_code == 200, response.text
    stored = await Score.get(id=score_id)
    assert (stored.authors_metadata, stored.paper_metadata, stored.paper_url) == (None, None, None)
    body = response.json()
    assert "authors_metadata" not in body and "paper_metadata" not in body


async def test_patch_leaves_an_absent_object_unchanged(client: AsyncClient) -> None:
    score_id = await _submit(
        client,
        authors_metadata={ALICE: {"full_name": "Alice"}},
        paper_metadata={"title": "T"},
    )

    await client.patch(f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(ALICE))

    stored = await Score.get(id=score_id)
    assert stored.authors_metadata == {ALICE: {"full_name": "Alice"}}
    assert (stored.paper_metadata, stored.paper_url) == ({"title": "T"}, PAPER)


async def test_patch_removing_an_author_drops_their_entry_in_the_same_edit(
    client: AsyncClient,
) -> None:
    score_id = await _submit(
        client,
        authors=[ALICE, BOB],
        authors_metadata={ALICE: {"full_name": "Alice"}, BOB: {"full_name": "Bo"}},
    )

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"authors": [ALICE]}, headers=_as(ALICE)
    )

    assert response.status_code == 200, response.text
    stored = await Score.get(id=score_id)
    assert stored.authors_metadata == {ALICE: {"full_name": "Alice"}}
    [event] = await _events(score_id)
    assert (event.old_authors, event.new_authors) == ([ALICE, BOB], [ALICE])
    assert event.old_authors_metadata == {ALICE: {"full_name": "Alice"}, BOB: {"full_name": "Bo"}}
    assert event.new_authors_metadata == {ALICE: {"full_name": "Alice"}}


async def test_patch_metadata_for_an_author_not_credited_is_422(client: AsyncClient) -> None:
    score_id = await _submit(client, authors=[ALICE])

    response = await client.patch(
        f"/v1/scores/{score_id}",
        json={"authors_metadata": {CAROL: {"full_name": "C"}}},
        headers=_as(ALICE),
    )

    assert response.status_code == 422
    assert _error_locs(response) == [["body", "authors_metadata", CAROL]]
    assert (await Score.get(id=score_id)).authors_metadata is None
    assert await _events(score_id) == []


async def test_patch_new_authors_and_their_metadata_together(client: AsyncClient) -> None:
    score_id = await _submit(client, authors=[ALICE])

    response = await client.patch(
        f"/v1/scores/{score_id}",
        json={"authors": [ALICE, CAROL], "authors_metadata": {CAROL: {"full_name": "C"}}},
        headers=_as(ALICE),
    )

    assert response.status_code == 200, response.text
    assert (await Score.get(id=score_id)).authors_metadata == {CAROL: {"full_name": "C"}}


async def test_patch_that_changes_nothing_writes_no_event(client: AsyncClient) -> None:
    score_id = await _submit(client, paper_metadata={"title": "T"})

    response = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_metadata": {"title": "T"}}, headers=_as(ALICE)
    )

    assert response.status_code == 200
    assert await _events(score_id) == []


# --- same-owner resubmit -----------------------------------------------------------------------


async def test_resubmit_replaces_metadata_and_logs_a_resubmit_event(client: AsyncClient) -> None:
    score_id = await _submit(client, authors=[ALICE], paper_metadata={"title": "Old"})

    replay = await _post(
        client,
        authors=[ALICE],
        authors_metadata={ALICE: {"full_name": "Alice"}},
        paper_metadata={"title": "New", "url": PAPER},
    )

    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == score_id
    stored = await Score.get(id=score_id)
    assert stored.authors_metadata == {ALICE: {"full_name": "Alice"}}
    assert (stored.paper_metadata, stored.paper_url) == ({"title": "New"}, PAPER)
    [event] = await _events(score_id)
    assert event.source == "resubmit"
    assert (event.old_paper_metadata, event.new_paper_metadata) == (
        {"title": "Old"},
        {"title": "New"},
    )


async def test_resubmit_without_the_objects_keeps_them(client: AsyncClient) -> None:
    score_id = await _submit(
        client, authors_metadata={ALICE: {"full_name": "Alice"}}, paper_metadata={"title": "T"}
    )

    replay = await _post(client)

    assert replay.status_code == 200
    stored = await Score.get(id=score_id)
    assert stored.authors_metadata == {ALICE: {"full_name": "Alice"}}
    assert stored.paper_metadata == {"title": "T"}


async def test_resubmit_removing_an_author_drops_their_entry(client: AsyncClient) -> None:
    score_id = await _submit(
        client,
        authors=[ALICE, BOB],
        authors_metadata={ALICE: {"full_name": "Alice"}, BOB: {"full_name": "Bo"}},
    )

    replay = await _post(client, authors=[ALICE])

    assert replay.status_code == 200
    assert (await Score.get(id=score_id)).authors_metadata == {ALICE: {"full_name": "Alice"}}


async def test_resubmit_matches_against_the_stored_authors(client: AsyncClient) -> None:
    # Owner, 2026-10-15 (c): a resubmit without `authors` keeps the stored credit line, and the
    # keys are matched against it under the row lock.
    score_id = await _submit(client, authors=[ALICE, BOB])

    accepted = await _post(client, authors_metadata={BOB: {"full_name": "Bo"}})
    refused = await _post(client, authors_metadata={CAROL: {"full_name": "C"}})

    assert accepted.status_code == 200, accepted.text
    assert refused.status_code == 422
    assert _error_locs(refused) == [["body", "authors_metadata", CAROL]]
    assert (await Score.get(id=score_id)).authors_metadata == {BOB: {"full_name": "Bo"}}


async def test_resubmit_explicit_null_preserves_objects_and_paper_link(client: AsyncClient) -> None:
    # INVARIANT: owner 2026-10-19 — null in a resubmission is not a request to delete credits.
    created = await _post(
        client,
        authors_metadata={ALICE: {"full_name": "Alice"}},
        paper_metadata={"title": "T", "url": PAPER},
    )
    assert created.status_code == 201, created.text
    initial = created.json()
    replay = await _post(client, authors_metadata=None, paper_metadata=None, paper_url=None)
    assert replay.status_code == 200, replay.text
    read = await client.get(f"/v1/scores/{initial['id']}")
    assert read.status_code == 200, read.text
    for response in (replay.json(), read.json()):
        for field in ("id", "authors_metadata", "paper_metadata", "paper_url"):
            assert response[field] == initial[field]
        assert "metadata_updated_at" not in response
