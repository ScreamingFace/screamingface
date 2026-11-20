"""Migration 0026 adds the HubSpot sync queue table and touches no existing row (OME-1504).

FEATURE: the HubSpot submission sync keeps one row per score in `hubspot_sync`. The migration only
creates the table; existing scores get their rows from the job's first run, not from here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.test_migration_0022_baseline_metadata import _migrate


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def test_migration_creates_the_queue_table_and_leaves_scores_alone(tmp_path: Path) -> None:
    database = tmp_path / "hubspot.sqlite3"
    _migrate(database, "0025_score_regraded_from")
    score_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) "
            "VALUES ('mmlu_pro', 'MMLU-Pro', '2026-10-01 00:00:00')"
        )
        connection.execute(
            """INSERT INTO scores
               (id, version, spec_id, url4_expression, submitted_at, total_questions,
                ran_with_providers, benchmark_id, verified_by_screamingface, score)
               VALUES (?, 1, 'spec-a', 'url4://x', '2026-11-01 00:00:00', 10, '[]',
                       'mmlu_pro', 0, 0.5)""",
            (score_id,),
        )

    _migrate(database, "0026_hubspot_sync")

    with sqlite3.connect(database) as connection:
        assert _columns(connection, "hubspot_sync") == {
            "id",
            "score_id",
            "status",
            "reason",
            "sota_qualified",
            "attempts",
            "next_attempt_at",
            "created_at",
            "updated_at",
        }
        # INVARIANT: the migration queues nothing; the job's first run decides what to send.
        assert connection.execute("SELECT COUNT(*) FROM hubspot_sync").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM scores").fetchone() == (1,)


def test_a_score_has_at_most_one_sync_row(tmp_path: Path) -> None:
    database = tmp_path / "hubspot-unique.sqlite3"
    _migrate(database, "0026_hubspot_sync")
    score_id = str(uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) "
            "VALUES ('mmlu_pro', 'MMLU-Pro', '2026-10-01 00:00:00')"
        )
        connection.execute(
            """INSERT INTO scores
               (id, version, spec_id, url4_expression, submitted_at, total_questions,
                ran_with_providers, benchmark_id, verified_by_screamingface, score)
               VALUES (?, 1, 'spec-a', 'url4://x', '2026-11-01 00:00:00', 10, '[]',
                       'mmlu_pro', 0, 0.5)""",
            (score_id,),
        )
        insert = (
            "INSERT INTO hubspot_sync (score_id, status, attempts, created_at, updated_at) "
            "VALUES (?, 'pending', 0, '2026-11-01 00:00:00', '2026-11-01 00:00:00')"
        )
        connection.execute(insert, (score_id,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, (score_id,))
