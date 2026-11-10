from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

APP = Path(__file__).resolve().parents[2]


def _migrate(database: Path, target: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tortoise",
            "-c",
            "scoreboard.db.TORTOISE_CONFIG",
            "migrate",
            "models",
            target,
        ],
        cwd=APP,
        env={
            "PATH": "/usr/bin:/bin",
            "SCOREBOARD_DATABASE_URL": f"sqlite://{database}",
            "PYTHONPATH": str(APP / "src"),
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_metadata_migration_preserves_existing_baseline_without_inventing_facts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    _migrate(database, "0021_score_metadata_objects")
    row_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
            ("demo", "Demo", "2026-10-01 12:00:00"),
        )
        connection.execute(
            "INSERT INTO baselines (id, benchmark_id, model_name, score, source, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row_id, "demo", "Model", 0.75, "paper", "2026-10-02 12:00:00"),
        )
    _migrate(database, "0022_baseline_metadata")
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT id, score, imported_at, metric_name, observed_at, attached_by, "
            "last_imported_at FROM baselines"
        ).fetchone()
    assert row == (row_id, 0.75, "2026-10-02 12:00:00", None, None, None, None)
