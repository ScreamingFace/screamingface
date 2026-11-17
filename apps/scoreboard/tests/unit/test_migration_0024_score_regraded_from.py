from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.test_migration_0022_baseline_metadata import _migrate

_INSERT_SCORE = (
    "INSERT INTO scores (id, version, spec_id, url4_expression, submitted_at, score, "
    "total_questions, ran_with_providers, verified_by_screamingface, benchmark_id, "
    "regraded_from_id) VALUES (?, 1, 'spec-1', 'url4://x', '2026-11-01 12:00:00', 0.5, 4, "
    "'[\"openai\"]', 1, 'demo', ?)"
)


def _seed_legacy_score(database: Path) -> str:
    """Migrate to 0023 and store one ordinary score from before the re-grade columns."""
    _migrate(database, "0023_baseline_history")
    row_id: str = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
            ("demo", "Demo", "2026-11-01 12:00:00"),
        )
        connection.execute(
            "INSERT INTO scores (id, version, spec_id, url4_expression, submitted_at, score, "
            "total_questions, ran_with_providers, verified_by_screamingface, benchmark_id) "
            "VALUES (?, 1, 'spec-1', 'url4://x', '2026-11-01 12:00:00', 0.5, 4, '[\"openai\"]', "
            "1, 'demo')",
            (row_id,),
        )
    return row_id


def test_regrade_migration_keeps_existing_scores_as_ordinary_rows(tmp_path: Path) -> None:
    # WHY: nothing was ever re-graded before 0024, so every existing row must read as an ordinary
    # submission (both columns NULL), and no backfill may invent a link.
    database: Path = tmp_path / "regrade.sqlite3"
    row_id: str = _seed_legacy_score(database)

    _migrate(database, "0024_score_regraded_from")

    with sqlite3.connect(database) as connection:
        row: tuple[object, ...] | None = connection.execute(
            "SELECT id, score, regraded_from_id, regraded_by FROM scores"
        ).fetchone()
    assert row == (row_id, 0.5, None, None)


def test_regrade_migration_allows_one_regrade_per_source_and_many_ordinary_rows(
    tmp_path: Path,
) -> None:
    # INVARIANT (OME-1909): the unique index lets NULL repeat (every ordinary row) and refuses a
    # second row naming the same source.
    database: Path = tmp_path / "regrade.sqlite3"
    source_id: str = _seed_legacy_score(database)
    _migrate(database, "0024_score_regraded_from")

    with sqlite3.connect(database) as connection:
        connection.execute(_INSERT_SCORE, (str(uuid4()), None))
        connection.execute(_INSERT_SCORE, (str(uuid4()), source_id))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(_INSERT_SCORE, (str(uuid4()), source_id))
