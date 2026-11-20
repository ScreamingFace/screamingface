"""Backfilled client ids do not establish revisions on unregistered boards."""

import sqlite3
from pathlib import Path

from tests.unit.test_migration_0022_baseline_metadata import _migrate
from tests.unit.test_migration_0024_benchmark_revisions import _score


def test_backfill_skips_unregistered_boards_even_with_client_revision(tmp_path: Path) -> None:
    database = tmp_path / "unregistered.sqlite3"
    _migrate(database, "0023_baseline_history")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) "
            "VALUES ('legacy', 'Legacy', '2026-10-01 00:00:00')"
        )
        _score(
            connection,
            benchmark="legacy",
            revision="invented",
            total=1,
            submitted_at="2026-11-01 00:00:00",
        )
    _migrate(database, "0024_benchmark_revisions")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM benchmark_revisions").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM scores").fetchone() == (1,)
