"""Migration 0021: author and paper metadata columns, and one score per frozen copy.

WHY shell out to the real migration runner (the 0008 test's reason): every other test builds its
schema with `generate_schemas` on an empty database, so the deploy path is untested by
construction. This one runs 0021 on a POPULATED board, including child rows that point at
`scores`: a table rebuild (what an `AlterField` to `unique=True` emits on SQLite) would drop the
table under those foreign keys, so the unique rule has to arrive as an index instead.

INVARIANT: the migration refuses a board where two scores already name the same frozen copy, with
a message naming the copy ids and the score ids, instead of a raw database error (plan, "Duplicate
copy ids", option A). Nothing in 0021 is applied when it refuses.
"""

from __future__ import annotations

import importlib
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

REPO_APP = Path(__file__).resolve().parents[2]
BEFORE = "0020_score_frozen_copy"
MIGRATION = "scoreboard.scores.migrations.0021_score_metadata_objects"
COPY_A = "11111111-1111-4111-8111-111111111111"
COPY_B = "22222222-2222-4222-8222-222222222222"


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


def _insert_score(connection: sqlite3.Connection, frozen_copy_id: str | None) -> str:
    score_id = str(uuid4())
    connection.execute(
        """INSERT INTO scores
           (id, version, spec_id, url4_expression, submitted_at, total_questions,
            ran_with_providers, benchmark_id, verified_by_screamingface, score, frozen_copy_id)
           VALUES (?, 1, ?, 'url4://x', '2026-01-01 00:00:00', 100,
                   '["openai"]', 'hle', 1, 0.5, ?)""",
        (score_id, f"spec-{score_id}", frozen_copy_id),
    )
    return score_id


def _board_at_0020(tmp_path: Path) -> tuple[Path, str]:
    database = tmp_path / "scoreboard.sqlite3"
    url = f"sqlite://{database}"
    before = _migrate(url, BEFORE)
    assert before.returncode == 0, before.stderr
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
        ("hle", "Humanity's Last Exam", "2026-01-01 00:00:00"),
    )
    connection.commit()
    connection.close()
    return database, url


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {row[1]: {"type": row[2], "notnull": row[3]} for row in rows}


def _unique_indexes(connection: sqlite3.Connection, table: str) -> list[list[str]]:
    indexes = connection.execute(f'PRAGMA index_list("{table}")').fetchall()
    unique: list[list[str]] = []
    for index in indexes:
        if index[2] == 1:
            info = connection.execute(f'PRAGMA index_info("{index[1]}")').fetchall()
            unique.append([column[2] for column in info])
    return unique


def test_0021_applies_to_a_populated_board_and_adds_every_column(tmp_path: Path) -> None:
    database, url = _board_at_0020(tmp_path)
    connection = sqlite3.connect(database)
    captured = _insert_score(connection, COPY_A)
    _insert_score(connection, None)
    _insert_score(connection, None)
    # Child rows on both tables that point at `scores`: a rebuild of `scores` fails under them.
    connection.execute(
        """INSERT INTO score_metadata_events (id, edited_by, edited_at, source, score_id)
           VALUES (?, 'alice@example.test', '2026-01-02 00:00:00', 'patch', ?)""",
        (str(uuid4()), captured),
    )
    connection.execute(
        """INSERT INTO score_reproductions (id, reproduced_by, reproduced_at, run_id, score_id)
           VALUES (?, 'bob@example.test', '2026-01-03 00:00:00', 'run-1', ?)""",
        (str(uuid4()), captured),
    )
    connection.commit()
    connection.close()

    applied = _migrate(url)

    assert applied.returncode == 0, applied.stdout + applied.stderr
    connection = sqlite3.connect(database)
    scores = _columns(connection, "scores")
    events = _columns(connection, "score_metadata_events")
    for name in ("authors_metadata", "paper_metadata"):
        assert scores[name] == {"type": "JSON", "notnull": 0}, name
    for name in (
        "old_authors_metadata",
        "new_authors_metadata",
        "old_paper_metadata",
        "new_paper_metadata",
    ):
        assert events[name] == {"type": "JSON", "notnull": 0}, name
    # No backfill: every existing row reads NULL for both new score columns.
    stored = connection.execute("SELECT authors_metadata, paper_metadata FROM scores").fetchall()
    assert stored == [(None, None)] * 3
    # The child rows survived (no table rebuild dropped them).
    assert connection.execute("SELECT count(*) FROM score_metadata_events").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM score_reproductions").fetchone() == (1,)
    assert ["frozen_copy_id"] in _unique_indexes(connection, "scores")
    connection.close()


def test_after_0021_a_copy_names_one_score_and_null_names_many(tmp_path: Path) -> None:
    database, url = _board_at_0020(tmp_path)
    assert _migrate(url).returncode == 0

    connection = sqlite3.connect(database)
    _insert_score(connection, COPY_A)
    _insert_score(connection, None)
    _insert_score(connection, None)
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_score(connection, COPY_A)
    connection.close()


def test_0021_refuses_duplicate_copies_and_names_them(tmp_path: Path) -> None:
    database, url = _board_at_0020(tmp_path)
    connection = sqlite3.connect(database)
    first = _insert_score(connection, COPY_A)
    second = _insert_score(connection, COPY_A)
    _insert_score(connection, COPY_B)
    connection.commit()
    connection.close()

    refused = _migrate(url)

    # The refusal itself, its type and its message naming the copies and scores, is asserted on
    # the guard directly (`test_the_guard_groups_every_duplicate_copy_with_its_score_ids`); the
    # runner only reports it as text on stderr, so here the checks are the exit status and the
    # database state.
    assert refused.returncode != 0
    connection = sqlite3.connect(database)
    # Nothing of 0021 was applied: not recorded as applied, no new column, no unique index, and
    # the duplicate rows are as they were.
    applied = connection.execute("SELECT name FROM tortoise_migrations WHERE app = 'models'")
    assert "0021_score_metadata_objects" not in {row[0] for row in applied.fetchall()}
    assert "authors_metadata" not in _columns(connection, "scores")
    assert "old_authors_metadata" not in _columns(connection, "score_metadata_events")
    assert ["frozen_copy_id"] not in _unique_indexes(connection, "scores")
    stored = connection.execute(
        "SELECT id FROM scores WHERE frozen_copy_id = ? ORDER BY id", (COPY_A,)
    ).fetchall()
    assert [row[0] for row in stored] == sorted([first, second])
    connection.close()


class _FakeClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    async def execute_query_dict(self, query: str) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.rows


class _FakeEditor:
    def __init__(self, rows: list[dict[str, Any]], *, collect_sql: bool = False) -> None:
        self.client = _FakeClient(rows)
        self.collect_sql = collect_sql


@pytest.mark.asyncio
async def test_the_guard_groups_every_duplicate_copy_with_its_score_ids() -> None:
    module = importlib.import_module(MIGRATION)
    editor = _FakeEditor(
        [
            {"frozen_copy_id": COPY_B, "id": "s-3"},
            {"frozen_copy_id": COPY_A, "id": "s-2"},
            {"frozen_copy_id": COPY_A, "id": "s-1"},
            {"frozen_copy_id": COPY_B, "id": "s-4"},
        ]
    )

    with pytest.raises(module.DuplicateFrozenCopies) as raised:
        await module.refuse_duplicate_frozen_copies(None, editor)

    assert raised.value.duplicates == {COPY_A: ["s-1", "s-2"], COPY_B: ["s-3", "s-4"]}
    assert str(raised.value) == (
        "migration 0021 cannot make frozen_copy_id unique: 2 frozen copies are named by more "
        f"than one score ({COPY_A}: s-1, s-2; {COPY_B}: s-3, s-4). Ask the owner which score "
        "keeps each copy before deploying."
    )


@pytest.mark.asyncio
async def test_the_guard_passes_a_board_without_duplicates() -> None:
    module = importlib.import_module(MIGRATION)
    editor = _FakeEditor([])

    assert await module.refuse_duplicate_frozen_copies(None, editor) is None
    assert len(editor.client.queries) == 1


@pytest.mark.asyncio
async def test_the_guard_reads_nothing_when_only_collecting_sql() -> None:
    # `tortoise sqlmigrate` renders the migration without a database; the guard must not query.
    module = importlib.import_module(MIGRATION)
    editor = _FakeEditor([{"frozen_copy_id": COPY_A, "id": "s-1"}], collect_sql=True)

    assert await module.refuse_duplicate_frozen_copies(None, editor) is None
    assert editor.client.queries == []
