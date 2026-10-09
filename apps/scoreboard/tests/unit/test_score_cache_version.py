"""The frozen copy of a run on a score (E14 B4, PRD `cache-version-capture` C4, C10, C12; TDD
#16-#18, reworked for the frozen-copy design, spec 02 section 6).

FEATURE: OME-1307 — `frozen_copy_id`, `capture_status` and `answer_seed` say which frozen copy
holds a submission's run and whether it holds every call of it. They are stored as sent,
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
COPY_ID = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"
OTHER_COPY_ID = "ffeeddcc-bbaa-4998-8776-655443322110"


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
    # The frozen-copy fields are only passed when given, so a CHAR-style call runs on any schema.
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
async def test_post_stores_and_get_returns_frozen_copy_fields(
    disabled_client: AsyncClient,
) -> None:
    created = await disabled_client.post(
        "/v1/scores",
        json=_payload(capture_status="complete", frozen_copy_id=COPY_ID, answer_seed=42),
    )

    assert created.status_code == 201, created.text
    for body in (
        created.json(),
        (await disabled_client.get(f"/v1/scores/{created.json()['id']}")).json(),
    ):
        assert body["capture_status"] == "complete"
        assert body["frozen_copy_id"] == COPY_ID
        assert body["answer_seed"] == 42
    stored = await Score.get(id=created.json()["id"])
    assert (stored.capture_status, stored.frozen_copy_id, stored.answer_seed) == (
        "complete",
        COPY_ID,
        42,
    )


@pytest.mark.asyncio
async def test_a_score_without_a_frozen_copy_omits_the_keys(disabled_client: AsyncClient) -> None:
    # INVARIANT: excluded when absent, so no legacy row gains `"capture_status": null` in the
    # private JSONL export whose bytes authorise a purge (the same reason `paper_url` is excluded).
    created = await disabled_client.post("/v1/scores", json=_payload())

    assert created.status_code == 201, created.text
    for key in ("frozen_copy_id", "capture_status", "answer_seed"):
        assert key not in created.json()
        assert key not in (await disabled_client.get(f"/v1/scores/{created.json()['id']}")).json()


@pytest.mark.asyncio
async def test_a_zero_answer_seed_and_a_partial_run_without_a_copy_id_are_stored(
    disabled_client: AsyncClient,
) -> None:
    # `0` is a real seed (not "absent"), and a partial run that failed to open its copy has no id.
    created = await disabled_client.post(
        "/v1/scores", json=_payload(capture_status="partial", answer_seed=0)
    )

    assert created.status_code == 201, created.text
    assert created.json()["answer_seed"] == 0
    assert created.json()["capture_status"] == "partial"
    assert "frozen_copy_id" not in created.json()


@pytest.mark.asyncio
async def test_a_copy_id_is_stored_in_lower_case_canonical_form(
    disabled_client: AsyncClient,
) -> None:
    # `UUID(...)` is the check and `str(...)` the stored form: the same copy in upper case is the
    # same value, so the reproduction route can compare ids as plain strings.
    created = await disabled_client.post(
        "/v1/scores", json=_payload(capture_status="complete", frozen_copy_id=COPY_ID.upper())
    )

    assert created.status_code == 201, created.text
    assert created.json()["frozen_copy_id"] == COPY_ID
    assert (await Score.get(id=created.json()["id"])).frozen_copy_id == COPY_ID


@pytest.mark.asyncio
async def test_the_frozen_copy_never_enters_the_recipe_hash() -> None:
    # I3: dedup does not change.
    bare = _content_hash(_submission())
    full = _content_hash(
        _submission(capture_status="complete", frozen_copy_id=COPY_ID, answer_seed=1)
    )

    assert bare == full


# --- #17 C10: a bad copy id or status pairing is a 422 -------------------------------------------

BAD_FIELDS = [
    pytest.param({"frozen_copy_id": COPY_ID}, "frozen_copy_id", id="copy-id-without-status"),
    pytest.param({"capture_status": "yes"}, "capture_status", id="unknown-status"),
    pytest.param({"capture_status": "Complete"}, "capture_status", id="status-case"),
    pytest.param({"capture_status": ""}, "capture_status", id="empty-status"),
    *[
        pytest.param(
            {"capture_status": "complete", "frozen_copy_id": copy_id},
            "frozen_copy_id",
            id=f"copy-id-{copy_id!r}",
        )
        for copy_id in (
            "cr-0123456789ab",  # the cache-revision label this field replaced
            "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5",  # one hex digit short
            "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b0",  # one hex digit long
            "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5g",  # not hex
            COPY_ID + "\n",
            " " + COPY_ID,
            "",
        )
    ],
    pytest.param(
        {"capture_status": "complete", "answer_seed": 2**31}, "answer_seed", id="seed-too-big"
    ),
    pytest.param(
        {"capture_status": "complete", "answer_seed": -(2**31) - 1},
        "answer_seed",
        id="seed-too-small",
    ),
    pytest.param({"answer_seed": "abc"}, "answer_seed", id="seed-not-an-int"),
]


@pytest.mark.parametrize(("fields", "field"), BAD_FIELDS)
@pytest.mark.asyncio
async def test_post_rejects_a_bad_copy_id_or_status_pairing(
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
        pytest.param({"capture_status": "complete"}, id="complete-no-copy-id"),
        pytest.param({"capture_status": "partial"}, id="partial-no-copy-id"),
        pytest.param(
            {"capture_status": "partial", "frozen_copy_id": COPY_ID}, id="partial-with-copy-id"
        ),
        pytest.param({"answer_seed": -(2**31)}, id="min-seed-alone"),
        pytest.param({"answer_seed": 2**31 - 1}, id="max-seed-alone"),
        pytest.param({}, id="nothing"),
    ],
)
def test_submission_accepts_a_coherent_frozen_copy(fields: dict[str, Any]) -> None:
    submission = _submission(**fields)

    for name, value in fields.items():
        assert getattr(submission, name) == value


def test_a_copy_id_without_a_status_is_refused_by_the_model() -> None:
    with pytest.raises(ValidationError, match="capture_status"):
        _submission(frozen_copy_id=COPY_ID)


# --- #18 C12: a resubmit fills NULL frozen-copy fields and never replaces a set one ------------


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
    return (row.capture_status, row.frozen_copy_id, row.answer_seed)


@pytest.mark.asyncio
async def test_resubmit_fills_a_null_frozen_copy(tortoise_db: None) -> None:
    row = await _store_then_resubmit(
        {}, {"capture_status": "complete", "frozen_copy_id": COPY_ID, "answer_seed": 7}
    )

    assert _held(row) == ("complete", COPY_ID, 7)
    # Not an enriching field: the frontier reads none of them, so the row is not re-dated, and a
    # frozen-copy fill is not a metadata edit either.
    assert row.enriched_at is None
    assert row.metadata_updated_at is None
    assert await ScoreMetadataEvent.filter(score_id=row.id).count() == 0


@pytest.mark.asyncio
async def test_resubmit_never_replaces_a_set_frozen_copy(tortoise_db: None) -> None:
    row = await _store_then_resubmit(
        {"capture_status": "complete", "frozen_copy_id": COPY_ID, "answer_seed": 7},
        {"capture_status": "partial", "frozen_copy_id": OTHER_COPY_ID, "answer_seed": 9},
    )

    assert _held(row) == ("complete", COPY_ID, 7)


@pytest.mark.asyncio
async def test_resubmit_without_the_fields_cannot_erase_them(tortoise_db: None) -> None:
    row = await _store_then_resubmit(
        {"capture_status": "complete", "frozen_copy_id": COPY_ID, "answer_seed": 7}, {}
    )

    assert _held(row) == ("complete", COPY_ID, 7)


@pytest.mark.asyncio
async def test_the_copy_id_and_the_status_are_filled_together_or_not_at_all(
    tortoise_db: None,
) -> None:
    # A row that already holds a status (even `partial`, with no copy id) is NOT given a copy id by
    # a replay: the pair describes ONE execution. Filling the copy id alone would pair run A's
    # status with run B's frozen copy.
    row = await _store_then_resubmit(
        {"capture_status": "partial"}, {"capture_status": "complete", "frozen_copy_id": COPY_ID}
    )

    assert _held(row) == ("partial", None, None)


@pytest.mark.asyncio
async def test_resubmit_fills_the_seed_alone_when_the_pair_is_already_set(
    tortoise_db: None,
) -> None:
    row = await _store_then_resubmit(
        {"capture_status": "complete", "frozen_copy_id": COPY_ID},
        {"capture_status": "partial", "frozen_copy_id": OTHER_COPY_ID, "answer_seed": 5},
    )

    assert _held(row) == ("complete", COPY_ID, 5)


@pytest.mark.asyncio
async def test_resubmit_fills_the_pair_alone_when_the_seed_is_already_set(
    tortoise_db: None,
) -> None:
    row = await _store_then_resubmit(
        {"answer_seed": 3},
        {"capture_status": "complete", "frozen_copy_id": COPY_ID, "answer_seed": 8},
    )

    assert _held(row) == ("complete", COPY_ID, 3)


@pytest.mark.asyncio
async def test_a_zero_seed_is_a_set_value_that_a_resubmit_keeps(tortoise_db: None) -> None:
    # The sentinel for "unfilled" is NULL, not falsy: `0` is a real seed.
    row = await _store_then_resubmit({"answer_seed": 0}, {"answer_seed": 4})

    assert row.answer_seed == 0


@pytest.mark.asyncio
async def test_the_resubmit_response_reports_what_the_row_holds(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    store = ScoreStore()
    await store.submit(
        _submission(capture_status="complete", frozen_copy_id=COPY_ID, answer_seed=7)
    )

    replayed, _ = await store.submit(
        _submission(capture_status="partial", frozen_copy_id=OTHER_COPY_ID, answer_seed=9)
    )

    assert (replayed.capture_status, replayed.frozen_copy_id, replayed.answer_seed) == (
        "complete",
        COPY_ID,
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


def test_frozen_copy_migration_applies_to_a_populated_database(tmp_path: Path) -> None:
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
    for name in ("frozen_copy_id", "capture_status", "answer_seed"):
        assert scores[name][3] == 0, name
    assert scores["frozen_copy_id"][2] == "VARCHAR(36)"
    assert connection.execute(
        "SELECT frozen_copy_id, capture_status, answer_seed FROM scores"
    ).fetchone() == (None, None, None)
    reproductions = _columns(connection, "score_reproductions")
    assert set(reproductions) == {
        "id",
        "score_id",
        "reproduced_by",
        "reproduced_at",
        "run_id",
        "frozen_copy_id",
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
