import sqlite3
from uuid import uuid4

from tests.unit.test_migration_0022_baseline_metadata import _migrate


def test_populated_migration_preserves_result_and_leaves_health_unknown(tmp_path):
    database = tmp_path / "health.sqlite3"
    _migrate(database, "0024_benchmark_revisions")
    row_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
            ("demo", "Demo", "2026-11-01 12:00:00"),
        )
        connection.execute(
            "INSERT INTO baselines (id, benchmark_id, model_name, score, source, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row_id, "demo", "Model", 0.8, "paper", "2026-11-01 12:00:00"),
        )
    _migrate(database, "0025_external_source_health")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id, score FROM baselines").fetchone() == (row_id, 0.8)
        assert connection.execute("SELECT COUNT(*) FROM external_source_health").fetchone() == (0,)
        connection.execute(
            "INSERT INTO external_source_health (source_key, source_url, available, checked_at) "
            "VALUES (?, ?, ?, ?)",
            ("a" * 64, "https://example.org/", False, "2026-11-11 10:00:00"),
        )
        assert connection.execute(
            "SELECT available, last_available_at FROM external_source_health"
        ).fetchone() == (0, None)


def test_source_health_upgrade_preserves_benchmark_revision_history(tmp_path):
    database = tmp_path / "revision-health.sqlite3"
    _migrate(database, "0024_benchmark_revisions")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at, revision, case_count) "
            "VALUES ('demo', 'Demo', '2026-11-01 12:00:00', 'current', 100)"
        )
        connection.execute(
            "INSERT INTO benchmark_revisions (benchmark_id, revision, first_seen_at, "
            "first_seen_inferred, case_count, case_count_inferred) "
            "VALUES ('demo', 'old', '2026-10-01 12:00:00', 1, 90, 1)"
        )
    _migrate(database, "0025_external_source_health")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT revision, first_seen_at, case_count, case_count_inferred "
            "FROM benchmark_revisions WHERE benchmark_id = 'demo'"
        ).fetchall() == [("old", "2026-10-01 12:00:00", 90, 1)]
        assert connection.execute("SELECT COUNT(*) FROM external_source_health").fetchone() == (0,)
