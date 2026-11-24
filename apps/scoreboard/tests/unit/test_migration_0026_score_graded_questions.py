from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from tests.unit.test_migration_0022_baseline_metadata import _migrate


def test_graded_count_migration_leaves_existing_scores_without_a_count(tmp_path: Path) -> None:
    # WHY: no row stored before 0026 ever reported how many of its Cases were graded. NULL means
    # "not reported"; a backfill to the total would claim every old run graded all its Cases, and
    # a backfill to 0 would claim none did.
    database: Path = tmp_path / "graded.sqlite3"
    _migrate(database, "0025_score_regraded_from")
    row_id: str = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) VALUES (?, ?, ?)",
            ("demo", "Demo", "2026-11-01 12:00:00"),
        )
        connection.execute(
            "INSERT INTO scores (id, version, spec_id, url4_expression, submitted_at, score, "
            "total_questions, ran_with_providers, verified_by_screamingface, benchmark_id) "
            "VALUES (?, 1, 'spec-1', 'url4://x', '2026-11-01 12:00:00', 0.5, 525, '[\"openai\"]', "
            "1, 'demo')",
            (row_id,),
        )

    _migrate(database, "0026_score_graded_questions")

    with sqlite3.connect(database) as connection:
        row: tuple[object, ...] | None = connection.execute(
            "SELECT id, score, total_questions, graded_questions FROM scores"
        ).fetchone()
    assert row == (row_id, 0.5, 525, None)
