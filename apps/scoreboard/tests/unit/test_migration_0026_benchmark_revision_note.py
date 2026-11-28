from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.unit.test_migration_0022_baseline_metadata import _migrate


def _seed_revision(database: Path) -> None:
    """Migrate to 0025 and store one revision record from before notes existed."""
    _migrate(database, "0025_score_regraded_from")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
            ("demo", "Demo", "2026-11-01 12:00:00"),
        )
        connection.execute(
            "INSERT INTO benchmark_revisions (benchmark_id, revision, first_seen_at, "
            "first_seen_inferred, case_count, case_count_inferred) "
            "VALUES ('demo', 'rev-1', '2026-11-01 12:00:00', 0, 100, 0)"
        )


def test_note_migration_leaves_every_existing_revision_without_a_note(tmp_path: Path) -> None:
    # WHY: no revision published before 0026 has a written reason, and NULL means "no note".
    # A backfill would invent words nobody wrote and show them to readers as the team's.
    database: Path = tmp_path / "note.sqlite3"
    _seed_revision(database)

    _migrate(database, "0026_benchmark_revision_note")

    with sqlite3.connect(database) as connection:
        row: tuple[object, ...] | None = connection.execute(
            "SELECT revision, first_seen_at, case_count, note FROM benchmark_revisions"
        ).fetchone()
    assert row is not None
    assert (row[0], row[2], row[3]) == ("rev-1", 100, None)
    assert str(row[1]).startswith("2026-11-01 12:00:00")


def test_note_migration_adds_a_column_a_revision_can_be_given_a_note_in(tmp_path: Path) -> None:
    # INVARIANT: the note is per revision row, so two revisions of one Benchmark hold two notes.
    database: Path = tmp_path / "note.sqlite3"
    _seed_revision(database)
    _migrate(database, "0026_benchmark_revision_note")
    # WHY 300 characters: about 120 is the author's target, not a limit, so the column must hold
    # a note that runs well past it.
    long_note: str = "x" * 300

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmark_revisions (benchmark_id, revision, first_seen_at, "
            "first_seen_inferred, case_count, case_count_inferred, note) "
            "VALUES ('demo', 'rev-2', '2026-11-23 12:00:00', 0, 100, 0, ?)",
            (long_note,),
        )
        notes: list[tuple[object, ...]] = connection.execute(
            "SELECT revision, note FROM benchmark_revisions ORDER BY revision"
        ).fetchall()
    assert notes == [("rev-1", None), ("rev-2", long_note)]
