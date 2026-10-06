"""Migration 0018 must apply to a database that already holds benchmarks and scores (OME-1455).

WHY shell out to the real migration runner (the 0008 test's reason): every other test builds
its schema with `generate_schemas` on an empty database, so the deploy path is untested by
construction. Two nullable AddFields are the safe shape (0007, 0011 precedent); this pins that
they stay that shape, on a populated table, and that the seed path can write them afterwards.
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


def test_provenance_migration_applies_to_a_populated_database(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = f"sqlite://{database}"

    # 1. Stop at 0017, so the benchmark below predates the two columns exactly as a deployed
    #    database's rows do.
    to_0017 = _migrate(url, "0017_score_cache_saved_cost_archive")
    assert to_0017.returncode == 0, to_0017.stderr

    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
        ("inspect-mmlu", "MMLU", "2026-01-01 00:00:00"),
    )
    connection.commit()
    connection.close()

    # 2. Apply 0018 on top of the populated table.
    to_head = _migrate(url)
    assert to_head.returncode == 0, to_head.stderr

    # 3. Both columns exist, are nullable, and the pre-migration row reads NULL for both:
    #    "the Engine published none", which the API serves as null and "unknown" is never
    #    invented for it here (the seed writes it on the next deploy).
    connection = sqlite3.connect(database)
    columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(benchmarks)").fetchall()
    }
    assert "provenance" in columns and columns["provenance"][3] == 0, "provenance must be nullable"
    assert "saturation" in columns and columns["saturation"][3] == 0, "saturation must be nullable"
    provenance, saturation = connection.execute(
        "SELECT provenance, saturation FROM benchmarks WHERE id = ?", ("inspect-mmlu",)
    ).fetchone()
    assert provenance is None
    assert saturation is None
    connection.close()
