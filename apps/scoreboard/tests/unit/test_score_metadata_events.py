"""The edit log of a score's authors and paper link (E14 A1, PRD `metadata-ownership` M4, M9, M15).

FEATURE: OME-1307 — one `score_metadata_events` row for each request that changes `authors` or
`paper_url`, written by a PATCH or by a same-owner resubmit. Only the owner reads it through the
API.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes.dependencies import MISSING_IDENTITY_DETAIL, UNTRUSTED_PEER_DETAIL
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent

REPO_APP = Path(__file__).resolve().parents[2]
ALICE = "alice@example.test"
BOB = "bob@example.test"
CAROL = "carol@example.test"
PAPER = "https://arxiv.org/abs/2610.01234"
OTHER_PAPER = "https://doi.org/10.1000/xyz"


def _migrate(database_url: str, target: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "tortoise", "-c", "scoreboard.db.TORTOISE_CONFIG", "migrate"]
    if target is not None:
        command += ["models", target]
    return subprocess.run(
        command,
        cwd=REPO_APP,
        env={
            "PATH": "/usr/bin:/bin",
            "SCOREBOARD_DATABASE_URL": database_url,
            "PYTHONPATH": str(REPO_APP / "src"),
        },
        capture_output=True,
        text=True,
        timeout=180,
    )


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, tuple[object, ...]]:
    return {row[1]: row for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


# --- migration 0019 applies to a populated database ---------------------------------------------
# WHY the real runner (the 0008 and 0018 tests' reason): every other test builds its schema with
# `generate_schemas` on an empty database, so the deploy path is untested by construction.


def test_metadata_migration_applies_to_a_populated_database(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = f"sqlite://{database}"

    # 1. Stop at 0018, so the score below predates the new columns as a deployed row does.
    before = _migrate(url, "0018_benchmark_provenance")
    assert before.returncode == 0, before.stderr
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
        ("hle", "HLE", "2026-01-01 00:00:00"),
    )
    connection.execute(
        "INSERT INTO scores (id, version, spec_id, url4_expression, submitted_at, score,"
        " total_questions, ran_with_providers, verified_by_screamingface, benchmark_id)"
        " VALUES (?, 1, 's', 'url4://x', '2026-01-01 00:00:00', 0.5, 4, '[]', 1, 'hle')",
        ("11111111-1111-1111-1111-111111111111",),
    )
    connection.commit()
    connection.close()

    # 2. Apply 0019 on top of the populated table.
    after = _migrate(url)
    assert after.returncode == 0, after.stderr

    # 3. Both columns are nullable and the old row reads NULL ("no paper", "never edited"), and
    #    the event table exists with the contracted columns and a score FK that cascades.
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    scores = _columns(connection, "scores")
    assert scores["paper_url"][3] == 0 and scores["metadata_updated_at"][3] == 0
    assert connection.execute("SELECT paper_url, metadata_updated_at FROM scores").fetchone() == (
        None,
        None,
    )
    events = _columns(connection, "score_metadata_events")
    assert set(events) == {
        "id",
        "score_id",
        "edited_by",
        "edited_at",
        "source",
        "old_authors",
        "new_authors",
        "old_paper_url",
        "new_paper_url",
    }
    connection.execute(
        "INSERT INTO score_metadata_events (id, score_id, edited_by, edited_at, source)"
        " VALUES ('e1', '11111111-1111-1111-1111-111111111111', 'a@x.test', '2026-01-02', 'patch')"
    )
    connection.execute("DELETE FROM scores")
    assert connection.execute("SELECT COUNT(*) FROM score_metadata_events").fetchone() == (0,)
    connection.close()


# --- the HTTP side: the same fixtures as test_score_metadata_patch.py -----------------------------


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


@pytest_asyncio.fixture
async def app(tortoise_db: None, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # Same pins as `app_with_cloudflare_auth` in test_scores_routes.py.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = create_app(
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
    return app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


async def _submit(http: AsyncClient, owner: str = ALICE, **overrides: Any) -> tuple[str, int]:
    response = await http.post("/v1/scores", json=_payload(**overrides), headers=_as(owner))
    assert response.status_code in (200, 201), response.text
    return str(response.json()["id"]), response.status_code


async def _events(score_id: str) -> list[ScoreMetadataEvent]:
    return await ScoreMetadataEvent.filter(score_id=score_id).order_by("edited_at")


# --- #16 M15: a resubmit that changes authors or paper_url logs one `resubmit` event ------------


@pytest.mark.asyncio
async def test_resubmit_change_logs_event_with_source_resubmit(client: AsyncClient) -> None:
    score_id, _ = await _submit(client, authors=[ALICE])

    again, status = await _submit(client, authors=[ALICE, BOB], paper_url=PAPER)

    assert (again, status) == (score_id, 200)
    stored = await Score.get(id=score_id)
    assert stored.authors == [ALICE, BOB] and stored.paper_url == PAPER
    assert stored.metadata_updated_at is not None
    assert stored.enriched_at is None  # display-only: it never dates the frontier
    (event,) = await _events(score_id)
    assert event.source == "resubmit"
    assert event.edited_by == ALICE
    assert (event.old_authors, event.new_authors) == ([ALICE], [ALICE, BOB])
    assert (event.old_paper_url, event.new_paper_url) == (None, PAPER)


@pytest.mark.asyncio
async def test_resubmit_reports_the_new_metadata_updated_at(client: AsyncClient) -> None:
    await _submit(client)

    response = await client.post("/v1/scores", json=_payload(paper_url=PAPER), headers=_as(ALICE))

    assert response.status_code == 200
    assert response.json()["paper_url"] == PAPER
    assert response.json()["metadata_updated_at"]


@pytest.mark.asyncio
async def test_resubmit_that_changes_nothing_writes_no_event(client: AsyncClient) -> None:
    score_id, _ = await _submit(client, authors=[ALICE], paper_url=PAPER)

    # The identical resubmit, one with only values the row already holds, and one with no
    # authors or paper_url at all (an older SDK).
    await _submit(client, authors=[ALICE], paper_url=PAPER)
    await _submit(client, paper_url=PAPER)
    await _submit(client)

    assert await _events(score_id) == []
    assert (await Score.get(id=score_id)).metadata_updated_at is None


@pytest.mark.asyncio
async def test_a_later_patch_chains_onto_a_resubmit_event(client: AsyncClient) -> None:
    score_id, _ = await _submit(client, paper_url=PAPER)
    await _submit(client, paper_url=OTHER_PAPER)

    await client.patch(f"/v1/scores/{score_id}", json={"paper_url": None}, headers=_as(ALICE))

    resubmit, patch = await _events(score_id)
    assert (resubmit.source, patch.source) == ("resubmit", "patch")
    assert patch.old_paper_url == resubmit.new_paper_url == OTHER_PAPER
    assert patch.new_paper_url is None


# --- #18 M4, M9: the events read is the owner's, newest first ------------------------------------


@pytest.mark.asyncio
async def test_events_read_owner_only_newest_first(client: AsyncClient) -> None:
    score_id, _ = await _submit(client, authors=[ALICE])
    await client.patch(f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(ALICE))
    await client.patch(
        f"/v1/scores/{score_id}", json={"authors": [ALICE, CAROL]}, headers=_as(ALICE)
    )

    owner = await client.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(ALICE))
    stranger = await client.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(BOB))

    assert owner.status_code == 200, owner.text
    body = owner.json()
    assert [event["new_authors"] for event in body] == [[ALICE, CAROL], [ALICE]]
    assert [event["new_paper_url"] for event in body] == [PAPER, PAPER]
    assert set(body[0]) == {
        "id",
        "edited_by",
        "edited_at",
        "source",
        "old_authors",
        "new_authors",
        "old_paper_url",
        "new_paper_url",
    }
    # The owner reads the FULL addresses; the public read DTO publishes local parts only.
    assert body[0]["edited_by"] == ALICE and body[0]["old_authors"] == [ALICE]
    assert body[0]["edited_at"] > body[1]["edited_at"]
    # Identity-scoped and sensitive: no shared cache may keep it.
    assert owner.headers["cache-control"] == "private, no-store"
    assert stranger.status_code == 403
    assert stranger.json()["detail"]["code"] == "not_score_owner"


@pytest.mark.asyncio
async def test_a_score_with_no_events_returns_an_empty_list(client: AsyncClient) -> None:
    score_id, _ = await _submit(client)

    response = await client.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(ALICE))

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_events_read_refusals_follow_the_post_rules(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as trusted:
        score_id, _ = await _submit(trusted)
        anonymous = await trusted.get(f"/v1/scores/{score_id}/metadata-events")
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.5", 443)), base_url="http://test"
    ) as untrusted:
        outsider = await untrusted.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(ALICE))

    assert anonymous.status_code == 401
    assert anonymous.json() == {"detail": MISSING_IDENTITY_DETAIL}
    assert outsider.status_code == 403
    assert outsider.json() == {"detail": UNTRUSTED_PEER_DETAIL}


@pytest.mark.asyncio
async def test_events_read_on_a_private_board_is_404_for_a_non_owner(client: AsyncClient) -> None:
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    score_id, _ = await _submit(client, benchmark_id="private-x")

    stranger = await client.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(BOB))
    missing = await client.get(f"/v1/scores/{uuid4()}/metadata-events", headers=_as(BOB))
    owner = await client.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(ALICE))

    assert stranger.status_code == 404
    assert stranger.json() == missing.json() == {"detail": "score not found"}
    assert owner.status_code == 200


@pytest.mark.asyncio
async def test_deleting_a_score_deletes_its_events(client: AsyncClient) -> None:
    score_id, _ = await _submit(client)
    await client.patch(f"/v1/scores/{score_id}", json={"paper_url": PAPER}, headers=_as(ALICE))
    assert len(await _events(score_id)) == 1

    await Score.filter(id=score_id).delete()

    assert await ScoreMetadataEvent.all().count() == 0


# --- design-review round -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_resubmit_writes_one_stamp_for_the_row_and_the_event(client: AsyncClient) -> None:
    score_id, _ = await _submit(client)

    await _submit(client, paper_url=PAPER)

    (event,) = await _events(score_id)
    assert event.edited_at == (await Score.get(id=score_id)).metadata_updated_at


@pytest.mark.asyncio
async def test_events_with_the_same_timestamp_have_a_stable_newest_first_order(
    client: AsyncClient,
) -> None:
    score_id, _ = await _submit(client)
    row = await Score.get(id=score_id)
    stamp = row.submitted_at
    for index in range(5):
        await ScoreMetadataEvent.create(
            score=row,
            edited_by=ALICE,
            edited_at=stamp,
            source="patch",
            new_paper_url=f"https://example.org/{index}",
        )

    first = await client.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(ALICE))
    second = await client.get(f"/v1/scores/{score_id}/metadata-events", headers=_as(ALICE))

    ids = [event["id"] for event in first.json()]
    assert ids == sorted(ids, reverse=True)
    assert first.json() == second.json()
