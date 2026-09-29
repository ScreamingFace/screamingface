"""E14 (OME-1307) migrations 0017-0019 on real SQLite files: columns, tables, indexes, backfill."""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from scoreboard.scores.models.partial_indexes import PARTIAL_UNIQUE_INDEX_SQL

REPO_APP = Path(__file__).resolve().parents[2]
TO_0016 = "0016_score_enriched_at"
TO_0018 = "0018_e14_registry_and_results_tables"
NEW_TABLES = {
    "system",
    "system_revision",
    "reported_result",
    "score_metadata_event",
    "cache_version_publication",
}


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


def _migrated(database: Path, target: str | None = None) -> str:
    url = f"sqlite://{database}"
    result = _migrate(url, target)
    assert result.returncode == 0, result.stdout + result.stderr
    return url


def _migrated_to_legacy_head(database: Path) -> str:
    """Migrate to 0016 the way production holds it: every pre-E14 migration applied.

    AIDEV-NOTE: `0004_add_run_cost_usd` is a leaf that no later migration depends on, so an
    explicit target of 0016 skips it. A production database has it applied, and the 0019 backfill
    copies `run_cost_usd`, so the fixture applies it too.
    """
    url = _migrated(database, TO_0016)
    _migrated(database, "0004_add_run_cost_usd")
    return url


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _insert_benchmark(connection: sqlite3.Connection, benchmark_id: str) -> None:
    connection.execute(
        """INSERT INTO benchmarks (id, display_name, visibility, created_at)
           VALUES (?, ?, 'public', '2026-01-01 00:00:00')""",
        (benchmark_id, benchmark_id.upper()),
    )


def _insert_score(
    connection: sqlite3.Connection,
    benchmark_id: str,
    *,
    score_id: str | None = None,
    metadata: str | None = None,
    submitted_at: str = "2026-02-01 00:00:00",
    score: float = 0.5,
    run_cost_usd: str | None = None,
    submitted_by: str | None = "owner@example.com",
    extra: dict[str, object] | None = None,
) -> str:
    identifier = score_id or str(uuid.uuid4())
    values: dict[str, object] = {
        "id": identifier,
        "version": 1,
        "spec_id": "spec",
        "url4_expression": "url4://x",
        "submitted_by": submitted_by,
        "submitted_at": submitted_at,
        "total_questions": 10,
        "correct_questions": 5,
        "ran_with_providers": "[]",
        "metadata": metadata,
        "benchmark_id": benchmark_id,
        "verified_by_screamingface": 0,
        "score": score,
        "run_cost_usd": run_cost_usd,
        **(extra or {}),
    }
    columns = ", ".join(f'"{name}"' for name in values)
    marks = ", ".join("?" for _ in values)
    connection.execute(f"INSERT INTO scores ({columns}) VALUES ({marks})", tuple(values.values()))
    return identifier


def _seed_legacy(database: Path) -> list[str]:
    """Two benchmarks and three scores, written with only the 0016 columns."""
    connection = sqlite3.connect(database)
    _insert_benchmark(connection, "alpha")
    _insert_benchmark(connection, "beta")
    ids = [
        _insert_score(connection, "alpha", score=0.25, run_cost_usd="1.500000"),
        _insert_score(connection, "alpha", score=0.75, submitted_by=None),
        _insert_score(connection, "beta", score=0.5, run_cost_usd="0.010000"),
    ]
    connection.commit()
    connection.close()
    return ids


def test_sch9_an_insert_from_old_code_gets_database_defaults(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    _migrated(database)

    connection = sqlite3.connect(database)
    score_columns = _columns(connection, "scores")
    # INVARIANT: an old pod omits the new columns on INSERT during a rolling rollout; the database
    # default is what keeps the NOT NULL columns valid.
    assert {
        "metadata_revision",
        "paper_url",
        "metadata_updated_at",
        "system_revision_id",
    } <= score_columns
    assert "redistributable" in _columns(connection, "benchmarks")

    _insert_benchmark(connection, "old-code")
    score_id = _insert_score(connection, "old-code")
    connection.commit()
    revision = connection.execute(
        "SELECT metadata_revision FROM scores WHERE id = ?", (score_id,)
    ).fetchone()
    redistributable = connection.execute(
        "SELECT redistributable FROM benchmarks WHERE id = 'old-code'"
    ).fetchone()
    connection.close()

    assert revision == (1,)
    assert redistributable == (0,)


def test_sch1_migrations_apply_to_a_populated_sqlite_database(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = _migrated_to_legacy_head(database)
    _seed_legacy(database)

    applied = _migrate(url)
    assert applied.returncode == 0, applied.stdout + applied.stderr

    connection = sqlite3.connect(database)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    legacy = connection.execute("SELECT metadata_revision, paper_url FROM scores").fetchall()
    result_columns = _columns(connection, "reported_result")
    result_indexes = connection.execute('PRAGMA index_list("reported_result")').fetchall()
    leading = {
        connection.execute(f'PRAGMA index_info("{index[1]}")').fetchone()[2]
        for index in result_indexes
    }
    connection.close()

    assert NEW_TABLES <= tables
    assert legacy == [(1, None)] * 3
    # INVARIANT: the columns carry the erd.md section 2.2 names, and the `(score, submitted_at)`
    # index sits on the real column, not on the attribute name `head_id`.
    assert {"score_id", "replayed_from_result_id", "pinned_baseline_result_id"} <= result_columns
    assert not {"head_id", "replayed_from_id", "pinned_baseline_id"} & result_columns
    assert "score_id" in leading


def test_sch2_backfill_creates_one_original_result_per_score(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    _migrated_to_legacy_head(database)
    score_ids = _seed_legacy(database)
    _migrated(database)

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    scores = {row["id"]: row for row in connection.execute("SELECT * FROM scores")}
    results = list(connection.execute("SELECT * FROM reported_result"))
    connection.close()

    assert len(results) == len(score_ids) == 3
    for result in results:
        head = scores[result["score_id"]]
        assert result["id"] == result["score_id"]
        assert result["is_original"] == 1
        assert result["reporter"] == head["submitted_by"]
        assert result["score"] == head["score"]
        assert result["total_questions"] == head["total_questions"]
        assert result["run_cost_usd"] == head["run_cost_usd"]
        assert result["submitted_at"] == head["submitted_at"]


def test_sch3_backfill_is_idempotent_and_skips_a_head_with_an_original(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = _migrated_to_legacy_head(database)
    score_a, score_b, score_c = _seed_legacy(database)
    _migrate(url, TO_0018)

    existing = str(uuid.uuid4())
    connection = sqlite3.connect(database)
    connection.execute(
        """INSERT INTO reported_result
           (id, score_id, is_original, score, total_questions, submitted_at)
           VALUES (?, ?, 1, 0.25, 10, '2026-02-01 00:00:00')""",
        (existing, score_a),
    )
    connection.commit()
    connection.close()

    applied = _migrate(url)
    assert applied.returncode == 0, applied.stdout + applied.stderr

    def _originals() -> dict[str, list[str]]:
        conn = sqlite3.connect(database)
        rows = conn.execute("SELECT score_id, id FROM reported_result WHERE is_original").fetchall()
        conn.close()
        grouped: dict[str, list[str]] = {}
        for score_id, result_id in rows:
            grouped.setdefault(score_id, []).append(result_id)
        return grouped

    first = _originals()
    assert first[score_a] == [existing]
    assert first[score_b] == [score_b]
    assert first[score_c] == [score_c]

    back = _migrate(url, TO_0018)
    assert back.returncode == 0, back.stdout + back.stderr
    forward = _migrate(url)
    assert forward.returncode == 0, forward.stdout + forward.stderr
    assert _originals() == first


def test_sch4_backfill_run_id_rules(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    _migrated_to_legacy_head(database)

    connection = sqlite3.connect(database)
    _insert_benchmark(connection, "alpha")
    cases = {
        "first": json.dumps({"run_id": "r-1"}),
        "duplicate": json.dumps({"run_id": "r-1"}),
        "non_string": json.dumps({"run_id": 7}),
        "blank": json.dumps({"run_id": " "}),
        "padded": json.dumps({"run_id": " r-2 "}),
        "too_long": json.dumps({"run_id": "x" * 129}),
        "empty": json.dumps({}),
        "null": None,
        "malformed": "{not json",
    }
    ids: dict[str, str] = {}
    for offset, (name, metadata) in enumerate(cases.items()):
        ids[name] = _insert_score(
            connection,
            "alpha",
            metadata=metadata,
            submitted_at=f"2026-03-01 00:00:{offset:02d}",
        )
    connection.commit()
    connection.close()

    _migrated(database)

    connection = sqlite3.connect(database)
    run_ids = dict(connection.execute("SELECT score_id, run_id FROM reported_result"))
    connection.close()

    # INVARIANT: run_id is UNIQUE, so only the first score per value may carry it.
    assert run_ids[ids["first"]] == "r-1"
    assert [name for name, score_id in ids.items() if run_ids[score_id] is not None] == ["first"]


def test_sch5_one_original_result_per_score_is_enforced(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    _migrated(database)

    connection = sqlite3.connect(database)
    _insert_benchmark(connection, "alpha")
    score_id = _insert_score(connection, "alpha")

    def _result(is_original: int) -> None:
        connection.execute(
            """INSERT INTO reported_result
               (id, score_id, is_original, score, total_questions, submitted_at)
               VALUES (?, ?, ?, 0.5, 10, '2026-02-01 00:00:00')""",
            (str(uuid.uuid4()), score_id, is_original),
        )

    _result(1)
    with pytest.raises(sqlite3.IntegrityError):
        _result(1)
    _result(0)
    connection.close()


def test_sch6_one_public_head_per_system_revision_is_enforced(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    _migrated(database)

    connection = sqlite3.connect(database)
    _insert_benchmark(connection, "alpha")
    system_id, revision_id = str(uuid.uuid4()), str(uuid.uuid4())
    connection.execute(
        """INSERT INTO system (id, name, owner, created_at)
           VALUES (?, 'sys', 'o@example.com', '2026-01-01 00:00:00')""",
        (system_id,),
    )
    connection.execute(
        """INSERT INTO system_revision
           (id, revision, fingerprint, candidate_url4, declared_by, created_at, system_id)
           VALUES (?, 1, 'f' , 'url4://c', 'o@example.com', '2026-01-01 00:00:00', ?)""",
        (revision_id, system_id),
    )

    def _head(system_revision_id: str | None) -> None:
        _insert_score(
            connection,
            "alpha",
            extra={"benchmark_revision": "r1", "system_revision_id": system_revision_id},
        )

    _head(revision_id)
    with pytest.raises(sqlite3.IntegrityError):
        _head(revision_id)
    _head(None)
    _head(None)
    connection.close()


def test_sch7_partial_index_ddl_matches_the_migration() -> None:
    migration = importlib.import_module(f"scoreboard.scores.migrations.{TO_0018}")
    # WHY only the single-statement ops: the column renames ride in a RunSQL tuple of their own.
    statements = [
        operation.sql
        for operation in migration.Migration.operations
        if type(operation).__name__ == "RunSQL" and isinstance(operation.sql, str)
    ]

    assert statements == list(PARTIAL_UNIQUE_INDEX_SQL)
    assert all(statements)


def test_sch1b_migrations_reverse_and_reapply_cleanly(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = _migrated_to_legacy_head(database)
    _seed_legacy(database)
    _migrated(database)

    # WHY 0017 and not 0016: reversing an `AddField` on SQLite rebuilds `scores`, and the DROP fails
    # on a populated database (a Tortoise limit that 0016 shares). 0018 and 0019 are the E14 steps
    # that carry hand-written reverse SQL.
    back = _migrate(url, "0017_e14_score_metadata_columns")
    assert back.returncode == 0, back.stdout + back.stderr
    connection = sqlite3.connect(database)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    connection.close()
    assert not NEW_TABLES & tables

    forward = _migrate(url)
    assert forward.returncode == 0, forward.stdout + forward.stderr
    connection = sqlite3.connect(database)
    originals = connection.execute("SELECT COUNT(*) FROM reported_result").fetchone()
    connection.close()
    assert originals == (3,)
