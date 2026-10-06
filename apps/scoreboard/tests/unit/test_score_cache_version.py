"""The cache version of a run on a score (E14 B4, PRD `cache-version-capture` C4, C10, C12; TDD
#16-#18).

FEATURE: OME-1307 — `cache_revision`, `reproducible` and `answer_seed` say which cache version
produced a submission and whether a replay can answer every call of it. They are stored as sent,
read back, never part of the recipe hash, and FILL-ONLY on a same-owner resubmit.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections.abc import AsyncGenerator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore, _content_hash

REPO_APP = Path(__file__).resolve().parents[2]
ALICE = "alice@example.test"
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
    }
    payload.update(overrides)
    return payload


def _submission(**extra: Any) -> ScoreSubmission:
    # The cache-version fields are only passed when given, so a CHAR-style call runs on any schema.
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id="spec-1",
        url4_expression="url4://benchmark/hle/spec-1",
        submitted_by=ALICE,
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openai"],
        run_cost_usd=Decimal("1.000000"),
        run_cost_status="complete",
        **extra,
    )


@pytest_asyncio.fixture
async def disabled_client(tortoise_db: None) -> AsyncGenerator[AsyncClient, None]:
    app: FastAPI = create_app(
        Settings.model_validate({"database_url": "sqlite://:memory:", "cors_origins": []})
    )
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


# --- #16 C4: POST stores the three fields and GET returns them ---------------------------------


@pytest.mark.asyncio
async def test_post_stores_and_get_returns_cache_version_fields(
    disabled_client: AsyncClient,
) -> None:
    created = await disabled_client.post(
        "/v1/scores",
        json=_payload(reproducible="complete", cache_revision=LABEL, answer_seed=42),
    )

    assert created.status_code == 201, created.text
    for body in (
        created.json(),
        (await disabled_client.get(f"/v1/scores/{created.json()['id']}")).json(),
    ):
        assert body["reproducible"] == "complete"
        assert body["cache_revision"] == LABEL
        assert body["answer_seed"] == 42
    stored = await Score.get(id=created.json()["id"])
    assert (stored.reproducible, stored.cache_revision, stored.answer_seed) == (
        "complete",
        LABEL,
        42,
    )


@pytest.mark.asyncio
async def test_a_score_without_cache_version_omits_the_keys(disabled_client: AsyncClient) -> None:
    # INVARIANT: excluded when absent, so no legacy row gains `"reproducible": null` in the private
    # JSONL export whose bytes authorise a purge (the same reason `paper_url` is excluded).
    created = await disabled_client.post("/v1/scores", json=_payload())

    assert created.status_code == 201, created.text
    for key in ("cache_revision", "reproducible", "answer_seed"):
        assert key not in created.json()
        assert key not in (await disabled_client.get(f"/v1/scores/{created.json()['id']}")).json()


@pytest.mark.asyncio
async def test_a_zero_answer_seed_and_a_partial_run_without_a_label_are_stored(
    disabled_client: AsyncClient,
) -> None:
    # `0` is a real seed (not "absent"), and a partial or empty run legitimately has no label.
    created = await disabled_client.post(
        "/v1/scores", json=_payload(reproducible="partial", answer_seed=0)
    )

    assert created.status_code == 201, created.text
    assert created.json()["answer_seed"] == 0
    assert created.json()["reproducible"] == "partial"
    assert "cache_revision" not in created.json()


@pytest.mark.asyncio
async def test_the_cache_version_never_enters_the_recipe_hash() -> None:
    # I3: dedup does not change.
    bare = _content_hash(_submission())
    full = _content_hash(_submission(reproducible="complete", cache_revision=LABEL, answer_seed=1))

    assert bare == full


# --- #17 C10: a bad label or status pairing is a 422 -------------------------------------------

BAD_FIELDS = [
    pytest.param({"cache_revision": LABEL}, "cache_revision", id="label-without-status"),
    pytest.param({"reproducible": "yes"}, "reproducible", id="unknown-status"),
    pytest.param({"reproducible": "Complete"}, "reproducible", id="status-case"),
    pytest.param({"reproducible": ""}, "reproducible", id="empty-status"),
    *[
        pytest.param(
            {"reproducible": "complete", "cache_revision": label},
            "cache_revision",
            id=f"label-{label!r}",
        )
        for label in (
            "cr-0123456789a",  # 11 hex
            "cr-0123456789abc",  # 13 hex
            "cr-0123456789AB",  # upper-case hex
            "cr-0123456789ag",  # not hex
            "CR-0123456789ab",
            "0123456789ab",
            "cr-0123456789ab\n",
            " cr-0123456789ab",
            "",
        )
    ],
    pytest.param(
        {"reproducible": "complete", "answer_seed": 2**31}, "answer_seed", id="seed-too-big"
    ),
    pytest.param(
        {"reproducible": "complete", "answer_seed": -(2**31) - 1},
        "answer_seed",
        id="seed-too-small",
    ),
    pytest.param({"answer_seed": "abc"}, "answer_seed", id="seed-not-an-int"),
]


@pytest.mark.parametrize(("fields", "field"), BAD_FIELDS)
@pytest.mark.asyncio
async def test_post_rejects_a_bad_label_or_status_pairing(
    disabled_client: AsyncClient, fields: dict[str, Any], field: str
) -> None:
    response = await disabled_client.post("/v1/scores", json=_payload(**fields))

    assert response.status_code == 422, fields
    errors = response.json()["detail"]
    # The field must be KNOWN and then refused; `extra_forbidden` would be a false green.
    assert all(error["type"] != "extra_forbidden" for error in errors)
    assert any(error["loc"][:2] == ["body", field] or error["loc"] == ["body"] for error in errors)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"reproducible": "complete"}, id="complete-no-label"),
        pytest.param({"reproducible": "partial"}, id="partial-no-label"),
        pytest.param({"reproducible": "partial", "cache_revision": LABEL}, id="partial-with-label"),
        pytest.param({"answer_seed": -(2**31)}, id="min-seed-alone"),
        pytest.param({"answer_seed": 2**31 - 1}, id="max-seed-alone"),
        pytest.param({}, id="nothing"),
    ],
)
def test_submission_accepts_a_coherent_cache_version(fields: dict[str, Any]) -> None:
    submission = _submission(**fields)

    for name, value in fields.items():
        assert getattr(submission, name) == value


def test_a_label_without_a_status_is_refused_by_the_model() -> None:
    with pytest.raises(ValidationError, match="reproducible"):
        _submission(cache_revision=LABEL)


# --- #18 C12: a resubmit fills NULL cache-version fields and never replaces a set one ----------


async def _store_then_resubmit(first: dict[str, Any], again: dict[str, Any]) -> Score:
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    store = ScoreStore()
    created, was_created = await store.submit(_submission(**first))
    assert was_created is True
    replayed, was_created = await store.submit(_submission(**again))
    assert was_created is False
    assert replayed.id == created.id
    return await Score.get(id=created.id)


def _held(row: Score) -> tuple[str | None, str | None, int | None]:
    return (row.reproducible, row.cache_revision, row.answer_seed)


@pytest.mark.asyncio
async def test_resubmit_fills_a_null_cache_version(tortoise_db: None) -> None:
    row = await _store_then_resubmit(
        {}, {"reproducible": "complete", "cache_revision": LABEL, "answer_seed": 7}
    )

    assert _held(row) == ("complete", LABEL, 7)
    # Not an enriching field: the frontier reads none of them, so the row is not re-dated, and a
    # cache-version fill is not a metadata edit either.
    assert row.enriched_at is None
    assert row.metadata_updated_at is None
    assert await ScoreMetadataEvent.filter(score_id=row.id).count() == 0


@pytest.mark.asyncio
async def test_resubmit_never_replaces_a_set_cache_version(tortoise_db: None) -> None:
    row = await _store_then_resubmit(
        {"reproducible": "complete", "cache_revision": LABEL, "answer_seed": 7},
        {"reproducible": "partial", "cache_revision": OTHER_LABEL, "answer_seed": 9},
    )

    assert _held(row) == ("complete", LABEL, 7)


@pytest.mark.asyncio
async def test_resubmit_without_the_fields_cannot_erase_them(tortoise_db: None) -> None:
    row = await _store_then_resubmit(
        {"reproducible": "complete", "cache_revision": LABEL, "answer_seed": 7}, {}
    )

    assert _held(row) == ("complete", LABEL, 7)


@pytest.mark.asyncio
async def test_the_label_and_the_status_are_filled_together_or_not_at_all(
    tortoise_db: None,
) -> None:
    # A row that already holds a status (even `partial`, with no label) is NOT given a label by a
    # replay: the pair describes ONE execution. Filling the label alone would pair run A's status
    # with run B's cache version.
    row = await _store_then_resubmit(
        {"reproducible": "partial"}, {"reproducible": "complete", "cache_revision": LABEL}
    )

    assert _held(row) == ("partial", None, None)


@pytest.mark.asyncio
async def test_resubmit_fills_the_seed_alone_when_the_pair_is_already_set(
    tortoise_db: None,
) -> None:
    row = await _store_then_resubmit(
        {"reproducible": "complete", "cache_revision": LABEL},
        {"reproducible": "partial", "cache_revision": OTHER_LABEL, "answer_seed": 5},
    )

    assert _held(row) == ("complete", LABEL, 5)


@pytest.mark.asyncio
async def test_resubmit_fills_the_pair_alone_when_the_seed_is_already_set(
    tortoise_db: None,
) -> None:
    row = await _store_then_resubmit(
        {"answer_seed": 3},
        {"reproducible": "complete", "cache_revision": LABEL, "answer_seed": 8},
    )

    assert _held(row) == ("complete", LABEL, 3)


@pytest.mark.asyncio
async def test_a_zero_seed_is_a_set_value_that_a_resubmit_keeps(tortoise_db: None) -> None:
    # The sentinel for "unfilled" is NULL, not falsy: `0` is a real seed.
    row = await _store_then_resubmit({"answer_seed": 0}, {"answer_seed": 4})

    assert row.answer_seed == 0


@pytest.mark.asyncio
async def test_the_resubmit_response_reports_what_the_row_holds(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    store = ScoreStore()
    await store.submit(_submission(reproducible="complete", cache_revision=LABEL, answer_seed=7))

    replayed, _ = await store.submit(
        _submission(reproducible="partial", cache_revision=OTHER_LABEL, answer_seed=9)
    )

    assert (replayed.reproducible, replayed.cache_revision, replayed.answer_seed) == (
        "complete",
        LABEL,
        7,
    )


# --- migration 0020 applies to a populated database ---------------------------------------------
# WHY the real runner (the 0008, 0018 and 0019 tests' reason): every other test builds its schema
# with `generate_schemas` on an empty database, so the deploy path is untested by construction.


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


def test_cache_version_migration_applies_to_a_populated_database(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = f"sqlite://{database}"

    # 1. Stop at 0019, so the score below predates the new columns as a deployed row does.
    before = _migrate(url, "0019_score_metadata")
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

    # 2. Apply 0020 on top of the populated table.
    after = _migrate(url)
    assert after.returncode == 0, after.stderr

    # 3. The three columns are nullable and the old row reads NULL ("unknown"), and the
    #    reproductions table exists with the contracted columns, a cascading score FK and a unique
    #    (score_id, run_id).
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    scores = _columns(connection, "scores")
    for name in ("cache_revision", "reproducible", "answer_seed"):
        assert scores[name][3] == 0, name
    assert connection.execute(
        "SELECT cache_revision, reproducible, answer_seed FROM scores"
    ).fetchone() == (None, None, None)
    reproductions = _columns(connection, "score_reproductions")
    assert set(reproductions) == {
        "id",
        "score_id",
        "reproduced_by",
        "reproduced_at",
        "run_id",
        "cache_revision",
        "client_version",
    }
    insert = (
        "INSERT INTO score_reproductions (id, score_id, reproduced_by, reproduced_at, run_id)"
        " VALUES (?, '11111111-1111-1111-1111-111111111111', 'a@x.test', '2026-01-02', 'run-1')"
    )
    connection.execute(insert, ("r1",))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(insert, ("r2",))
    connection.execute("DELETE FROM scores")
    assert connection.execute("SELECT COUNT(*) FROM score_reproductions").fetchone() == (0,)
    connection.close()
