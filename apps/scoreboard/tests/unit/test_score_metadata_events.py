"""The edit log of a score's authors and paper link (E14 A1, PRD `metadata-ownership` M4, M9, M15).

FEATURE: OME-1307 — one `score_metadata_events` row for each request that changes `authors` or
`paper_url`, written by a PATCH or by a same-owner resubmit. Only the owner reads it through the
API.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_APP = Path(__file__).resolve().parents[2]


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
