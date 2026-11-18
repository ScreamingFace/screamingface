"""Migration 0024 backfills every revision a board has already seen (OME-1708).

FEATURE: the revision selector needs each past revision's first-seen date and Case count. Neither
was ever stored, so the migration infers them from the results under each revision: the earliest
submission is the first-seen date, and the largest question count is the Case count (a run never
covers more Cases than its revision has; a partial `limit=n` run reports fewer, and failed Cases
still count). Every inferred value is marked inferred; the registered revision keeps its
Engine-given count.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from tests.unit.test_migration_0022_baseline_metadata import _migrate


def _score(
    connection: sqlite3.Connection,
    *,
    benchmark: str,
    revision: str | None,
    total: int,
    submitted_at: str,
) -> None:
    connection.execute(
        """INSERT INTO scores
           (id, version, spec_id, url4_expression, submitted_at, total_questions,
            ran_with_providers, benchmark_id, verified_by_screamingface, score, benchmark_revision)
           VALUES (?, 1, ?, 'url4://x', ?, ?, '[]', ?, 0, 0.5, ?)""",
        (str(uuid4()), f"spec-{uuid4()}", submitted_at, total, benchmark, revision),
    )


def test_backfill_infers_each_past_revision_and_keeps_the_registered_count(tmp_path: Path) -> None:
    database = tmp_path / "revisions.sqlite3"
    _migrate(database, "0023_baseline_history")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at, revision, case_count) "
            "VALUES ('mmlu_pro', 'MMLU-Pro', '2026-10-01 00:00:00', 'rev-new', 12032)"
        )
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at) "
            "VALUES ('hle', 'HLE', '2026-08-01 00:00:00')"
        )
        # The old revision: two full runs (one with failures still reports 12032) and a smoke run.
        _score(
            connection,
            benchmark="mmlu_pro",
            revision="rev-old",
            total=12032,
            submitted_at="2026-10-12 10:00:00",
        )
        _score(
            connection,
            benchmark="mmlu_pro",
            revision="rev-old",
            total=200,
            submitted_at="2026-10-09 09:00:00",
        )
        _score(
            connection,
            benchmark="mmlu_pro",
            revision="rev-old",
            total=12032,
            submitted_at="2026-11-02 10:00:00",
        )
        # The registered revision: one smoke run only; its Engine count must still win.
        _score(
            connection,
            benchmark="mmlu_pro",
            revision="rev-new",
            total=100,
            submitted_at="2026-11-17 12:00:00",
        )
        # A legacy board with no revision anywhere: nothing to record.
        _score(
            connection,
            benchmark="hle",
            revision=None,
            total=3000,
            submitted_at="2026-08-02 00:00:00",
        )

    _migrate(database, "0024_benchmark_revisions")

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT benchmark_id, revision, first_seen_at, first_seen_inferred, "
            "case_count, case_count_inferred FROM benchmark_revisions "
            "ORDER BY benchmark_id, first_seen_at"
        ).fetchall()

    assert rows == [
        ("mmlu_pro", "rev-old", "2026-10-09 09:00:00", 1, 12032, 1),
        ("mmlu_pro", "rev-new", "2026-11-17 12:00:00", 1, 12032, 0),
    ]


def test_a_registered_revision_with_no_results_is_still_recorded(tmp_path: Path) -> None:
    # WHY: right after a bump the new revision has no results yet, and the selector must still
    # list it as Latest (the agreed empty-Latest state).
    database = tmp_path / "fresh.sqlite3"
    _migrate(database, "0023_baseline_history")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at, revision, case_count) "
            "VALUES ('ifeval', 'IFEval', '2026-10-01 00:00:00', 'rev-a', 541)"
        )

    _migrate(database, "0024_benchmark_revisions")

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT benchmark_id, revision, first_seen_at, first_seen_inferred, "
            "case_count, case_count_inferred FROM benchmark_revisions"
        ).fetchall()

    assert rows == [("ifeval", "rev-a", "2026-10-01 00:00:00", 1, 541, 0)]


def test_an_empty_latest_is_never_dated_before_an_older_revision(tmp_path: Path) -> None:
    # WHY: a board created at R1 and bumped to an empty R2 would otherwise date Latest by the
    # board's creation (1 Aug), before R1's first run (2 Aug). first_seen_at never moves once
    # written, so the selector would show "since about 1 Aug" above "about 2 Aug" for good.
    database = tmp_path / "bumped.sqlite3"
    _migrate(database, "0023_baseline_history")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO benchmarks (id, display_name, created_at, revision, case_count) "
            "VALUES ('ifeval', 'IFEval', '2026-08-01 00:00:00', 'rev-2', 541)"
        )
        for submitted_at in ("2026-08-02 00:00:00", "2026-09-15 00:00:00"):
            _score(
                connection,
                benchmark="ifeval",
                revision="rev-1",
                total=541,
                submitted_at=submitted_at,
            )

    _migrate(database, "0024_benchmark_revisions")

    with sqlite3.connect(database) as connection:
        latest = connection.execute(
            "SELECT first_seen_at, first_seen_inferred FROM benchmark_revisions "
            "WHERE benchmark_id = 'ifeval' AND revision = 'rev-2'"
        ).fetchone()

    # The newest other revision's first sighting is the tightest lower bound the data has.
    assert latest == ("2026-08-02 00:00:00", 1)
