"""Migration 0008 must apply to a database that already holds benchmarks.

WHY this test shells out to the real migration runner instead of asserting on the operations
list: the defect it guards against is invisible at the Python level. `fields.CharField(default=
"public")` looks correct in the migration file — the default is ORM-side only, and the SQL Tortoise
emits for a non-nullable AddField carries no database default, so a populated table rejects it.
Every other test in this suite builds its schema with `generate_schemas` on an empty database, so
the migration path is untested by construction. This one closes that gap for the deploy path
(found in review of PR #719).
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


def test_visibility_migration_applies_to_a_populated_database(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = f"sqlite://{database}"

    # 1. Stop at 0007, so the benchmark below predates the visibility column exactly as a
    #    deployed database's rows do.
    to_0007 = _migrate(url, "0007_benchmark_focus")
    assert to_0007.returncode == 0, to_0007.stderr

    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
        ("hle", "Humanity's Last Exam", "2026-01-01 00:00:00"),
    )
    connection.commit()
    connection.close()

    # 2. THE assertion: 0008 applies to that populated table. A single non-nullable AddField
    #    fails here with "Cannot add a NOT NULL column with default value NULL".
    applied = _migrate(url)

    assert applied.returncode == 0, applied.stdout + applied.stderr

    connection = sqlite3.connect(database)
    stored = connection.execute("SELECT visibility FROM benchmarks WHERE id = 'hle'").fetchone()
    connection.close()

    # INVARIANT: a benchmark that predates the column reads as public. It was world-readable
    # before, so `public` states what was already true rather than inventing a posture.
    assert stored is not None
    assert stored[0] == "public"
