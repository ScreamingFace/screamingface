from __future__ import annotations

import sqlite3
from uuid import uuid4

from tests.unit.test_migration_0022_baseline_metadata import _migrate


def test_history_migration_preserves_populated_baseline_without_fabricating_versions(tmp_path):
    database = tmp_path / "history.sqlite3"
    _migrate(database, "0022_baseline_metadata")
    row_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
            ("demo", "Demo", "2026-11-01 12:00:00"),
        )
        connection.execute(
            "INSERT INTO baselines "
            "(id, benchmark_id, model_name, score, source, imported_at, attached_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row_id, "demo", "Model", 0.8, "paper", "2026-11-01 12:00:00", "private-editor"),
        )
    _migrate(database, "0023_baseline_history")
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT id, score, attached_by, observation_revision, "
            "observation_updated_at FROM baselines"
        ).fetchone()
        assert row == (row_id, 0.8, "private-editor", 0, None)
        assert connection.execute("SELECT COUNT(*) FROM baseline_revisions").fetchone() == (0,)
