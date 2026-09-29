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
# The `scores` columns the 0019 backfill copies unchanged (`reporter` and `id` are checked apart).
COPIED_COLUMNS = (
    "score",
    "total_questions",
    "correct_questions",
    "run_cost_usd",
    "run_cost_status",
    "cache_saved_cost_usd",
    "models",
    "ran_with_providers",
    "client_name",
    "client_version",
    "client_platform",
    "submitted_at",
)
# The `reported_result` columns an original from the backfill must leave NULL (no run_id in the
# seeded metadata; no replay, cache or trace data exists for a legacy score).
UNSET_COLUMNS = (
    "run_id",
    "trace_id",
    "answer_seed",
    "replayed_from_result_id",
    "pinned_baseline_result_id",
    "cache_version_id",
    "cache_version_sha256",
    "cache_entry_count",
    "cache_call_count",
    "cache_coverage_status",
    "replay_hits",
    "replay_misses",
    "replay_repeated_key_collapses",
)
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


def _distinct_copied_columns(number: int) -> dict[str, object]:
    """A value per copied `scores` column that differs for every `number`, so a swap is visible."""
    return {
        "correct_questions": 3 + number,
        "run_cost_status": ("complete", "partial", "unknown")[number],
        "cache_saved_cost_usd": f"{number + 2}.250000",
        "models": json.dumps([f"model-{number}", f"alt-{number}"]),
        "ran_with_providers": json.dumps([f"provider-{number}"]),
        "client_name": f"client-{number}",
        "client_version": f"1.{number}.0",
        "client_platform": ("linux", "darwin", "windows")[number],
    }


def _seed_legacy(database: Path) -> list[str]:
    """Two benchmarks and three scores, written with only the 0016 columns.

    INVARIANT: every column the 0019 backfill copies holds a different non-NULL value on each score,
    so a dropped, NULLed or swapped column changes a compared value.
    """
    connection = sqlite3.connect(database)
    _insert_benchmark(connection, "alpha")
    _insert_benchmark(connection, "beta")
    ids = [
        _insert_score(
            connection,
            "alpha",
            score=0.25,
            run_cost_usd="1.500000",
            submitted_at="2026-02-01 00:00:01",
            extra=_distinct_copied_columns(0),
        ),
        _insert_score(
            connection,
            "alpha",
            score=0.75,
            submitted_by=None,
            run_cost_usd="2.500000",
            submitted_at="2026-02-01 00:00:02",
            extra=_distinct_copied_columns(1),
        ),
        _insert_score(
            connection,
            "beta",
            score=0.5,
            run_cost_usd="0.010000",
            submitted_at="2026-02-01 00:00:03",
            extra=_distinct_copied_columns(2),
        ),
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
    # INVARIANT (D8): the columns carry the Tortoise native names `<attr>_id`, which are also the
    # erd.md section 2.2 names, and the `(head_id, submitted_at)` index sits on the real column.
    assert {"head_id", "replayed_from_result_id", "pinned_baseline_result_id"} <= result_columns
    assert not {"score_id", "replayed_from_id", "pinned_baseline_id"} & result_columns
    assert "head_id" in leading


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
        head = scores[result["head_id"]]
        assert result["id"] == result["head_id"]
        assert result["is_original"] == 1
        assert result["reporter"] == head["submitted_by"]
        assert result["score"] == head["score"]
        assert result["total_questions"] == head["total_questions"]
        assert result["run_cost_usd"] == head["run_cost_usd"]
        assert result["submitted_at"] == head["submitted_at"]
        for column in COPIED_COLUMNS:
            assert result[column] == head[column], column
        for column in UNSET_COLUMNS:
            assert result[column] is None, column
    # WHY: the seed gives each score its own values, so a backfill that wrote one score's value
    # into every row cannot pass the per-row equality above.
    assert len({result["client_name"] for result in results}) == 3


def test_sch3_backfill_is_idempotent_and_skips_a_head_with_an_original(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    url = _migrated_to_legacy_head(database)
    score_a, score_b, score_c = _seed_legacy(database)
    _migrate(url, TO_0018)

    existing = str(uuid.uuid4())
    connection = sqlite3.connect(database)
    connection.execute(
        """INSERT INTO reported_result
           (id, head_id, is_original, score, total_questions, submitted_at)
           VALUES (?, ?, 1, 0.25, 10, '2026-02-01 00:00:00')""",
        (existing, score_a),
    )
    connection.commit()
    connection.close()

    applied = _migrate(url)
    assert applied.returncode == 0, applied.stdout + applied.stderr

    def _originals() -> dict[str, list[str]]:
        conn = sqlite3.connect(database)
        rows = conn.execute("SELECT head_id, id FROM reported_result WHERE is_original").fetchall()
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
    run_ids = dict(connection.execute("SELECT head_id, run_id FROM reported_result"))
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
               (id, head_id, is_original, score, total_questions, submitted_at)
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


def test_sch15_a_targeted_migrate_to_0019_applies_on_an_empty_database(tmp_path: Path) -> None:
    # INVARIANT: 0019 reads `scores.run_cost_usd`, which `0004_add_run_cost_usd` adds. That leaf is
    # not on the 0018 -> 0017 -> 0016 chain, so 0019 must declare it as its own dependency, or a
    # targeted migrate leaves 0017 and 0018 applied and fails on the backfill SQL.
    database = tmp_path / "scoreboard.sqlite3"

    result = _migrate(f"sqlite://{database}", "0019_e14_backfill_original_results")

    assert result.returncode == 0, result.stdout + result.stderr


def test_sch14_migration_delete_rules_of_the_result_foreign_keys(tmp_path: Path) -> None:
    # INVARIANT (D8): the delete rule of each `reported_result` FK in the MIGRATED file, not the
    # models' `generate_schemas` DDL. CASCADE lets `delete_scores` remove a head's results; NO
    # ACTION on both replay FKs blocks the delete of an original that another cluster replayed or
    # pinned as its baseline.
    database = tmp_path / "scoreboard.sqlite3"
    _migrated(database)

    connection = sqlite3.connect(database)
    rules = {
        row[3]: row[6] for row in connection.execute('PRAGMA foreign_key_list("reported_result")')
    }
    connection.close()

    assert rules == {
        "head_id": "CASCADE",
        "replayed_from_result_id": "NO ACTION",
        "pinned_baseline_result_id": "NO ACTION",
    }
