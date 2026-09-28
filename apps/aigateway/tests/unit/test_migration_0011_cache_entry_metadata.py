"""Migration 0011 appends the nullable cache-entry metadata column (A3, ERD §5.1).

Replays the deployed upgrade path on SQLite: migrate to ``0010``, seed a real cache row, apply
``0011``, then prove the column is last, nullable, defaultless, that the row survived untouched
with NULL metadata, and that the table was NOT rebuilt.

The last point is the migration's whole risk. ``0010`` shows the failure mode: SQLite cannot
``ALTER COLUMN``, so that operation rebuilt the table and silently stripped every standalone
index. A nullable ``ADD COLUMN`` with no default needs no rebuild on either dialect, so this
migration needs no index-restore workaround — and ``test_0011_does_not_rebuild_the_sqlite_table``
is what makes that claim checkable instead of assumed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import ModuleType

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
_TABLE = "request_cache_entries"
_COLUMN = "metadata_json"


def _migrate(database_url: str, *target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tortoise",
            "-c",
            "aigateway.db.TORTOISE_CONFIG",
            "migrate",
            *target,
        ],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _downgrade(database_url: str, migration: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tortoise",
            "-c",
            "aigateway.db.TORTOISE_CONFIG",
            "downgrade",
            "models",
            migration,
        ],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _columns(db: Path) -> dict[str, sqlite3.Row]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"]: row for row in conn.execute(f"pragma table_info({_TABLE})")}


def _column_order(db: Path) -> tuple[str, ...]:
    with sqlite3.connect(db) as conn:
        return tuple(row[1] for row in conn.execute(f"pragma table_info({_TABLE})"))


def _indexes(db: Path) -> dict[str, str | None]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "select name, sql from sqlite_master where type = 'index' and tbl_name = ?",
            (_TABLE,),
        ).fetchall()
    return {name: sql for name, sql in rows}


def _rootpage(db: Path) -> int:
    """The table's b-tree root. A SQLite rebuild (CREATE/INSERT/DROP/RENAME) moves it."""
    with sqlite3.connect(db) as conn:
        found = conn.execute(
            "select rootpage from sqlite_master where type = 'table' and name = ?", (_TABLE,)
        ).fetchone()
    assert found is not None, f"{_TABLE} is absent"
    return int(found[0])


def _seed_row(db: Path) -> str:
    """One row in the 0010 shape — no metadata column exists yet."""
    payload = json.dumps({"id": "cmpl-0010", "choices": []}, separators=(",", ":"))
    key_hash = "a" * 64
    with sqlite3.connect(db) as conn:
        conn.execute(
            f"insert into {_TABLE} (id, key_hash, prompt_hash, provider, model, response_json,"
            " response_size_bytes, created_at, updated_at, expires_at, hit_count, last_hit_at)"
            " values (?, ?, ?, 'openrouter', 'openrouter/anthropic/claude-fable-5', ?, ?,"
            " ?, ?, NULL, 3, ?)",
            (
                str(uuid.uuid4()),
                key_hash,
                "p" * 64,
                payload,
                len(payload),
                (datetime.now(UTC) - timedelta(hours=2)).isoformat(sep=" "),
                (datetime.now(UTC) - timedelta(hours=1)).isoformat(sep=" "),
                (datetime.now(UTC) - timedelta(minutes=30)).isoformat(sep=" "),
            ),
        )
    return key_hash


def _read_row(db: Path, key_hash: str) -> dict[str, object]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        found = conn.execute(f"select * from {_TABLE} where key_hash = ?", (key_hash,)).fetchone()
    assert found is not None, "the seeded row did not survive the migration"
    return dict(found)


@pytest.fixture
def populated_0010(tmp_path: Path) -> tuple[Path, str, str]:
    db = tmp_path / "populated-0010.sqlite3"
    url = f"sqlite://{db}"
    _migrate(url, "models", "0010_simplify_request_cache")
    key_hash = _seed_row(db)
    assert _COLUMN not in _columns(db)
    return db, url, key_hash


def test_0011_appends_a_nullable_metadata_column_without_a_default(
    populated_0010: tuple[Path, str, str],
) -> None:
    db, url, _key = populated_0010

    _migrate(url)

    columns = _columns(db)
    assert _COLUMN in columns
    assert _column_order(db)[-1] == _COLUMN, "the column must be appended last, not inserted"
    assert columns[_COLUMN]["notnull"] == 0
    assert columns[_COLUMN]["dflt_value"] is None
    assert columns[_COLUMN]["type"].upper() == "TEXT"


def test_0011_leaves_an_existing_row_intact_with_unknown_metadata(
    populated_0010: tuple[Path, str, str],
) -> None:
    db, url, key_hash = populated_0010
    before = _read_row(db, key_hash)

    _migrate(url)

    after = _read_row(db, key_hash)
    for column, expected in before.items():
        assert after[column] == expected, f"{column} changed across migration 0011"
    # ERD E7: NULL means unknown. No backfill, and never a zero-shaped block.
    assert after[_COLUMN] is None


def test_0011_does_not_rebuild_the_sqlite_table(
    populated_0010: tuple[Path, str, str],
) -> None:
    db, url, _key = populated_0010
    root_before = _rootpage(db)
    indexes_before = _indexes(db)

    _migrate(url)

    assert _rootpage(db) == root_before, (
        "the table b-tree moved — a nullable ADD COLUMN must not rebuild it, and a rebuild "
        "would drop the standalone indexes"
    )
    assert _indexes(db) == indexes_before


def test_0011_is_idempotent(populated_0010: tuple[Path, str, str]) -> None:
    _db, url, _key = populated_0010

    _migrate(url)
    rerun = _migrate(url)

    assert "No migrations to apply" in rerun.stdout


def test_0011_downgrade_drops_the_metadata_column_and_keeps_the_row(
    populated_0010: tuple[Path, str, str],
) -> None:
    db, url, key_hash = populated_0010
    _migrate(url)

    _downgrade(url, "0010_simplify_request_cache")

    assert _COLUMN not in _columns(db)
    assert _read_row(db, key_hash)["hit_count"] == 3


def test_0011_downgrade_keeps_the_standalone_indexes(
    populated_0010: tuple[Path, str, str],
) -> None:
    # SQLite's DROP COLUMN rebuilds the table and recreates no standalone indexes, so a bare
    # RemoveField would silently leave every local database doing full scans on key_hash. The
    # column is unindexed: the index set must be IDENTICAL across the round trip.
    db, url, _key = populated_0010
    _migrate(url)
    indexes_before = _indexes(db)

    _downgrade(url, "0010_simplify_request_cache")

    assert _indexes(db) == indexes_before


# --- Finding 2 — the migration must not queue for the table lock -------------------------------


def _migration_0011() -> ModuleType:
    """The migration module.

    Loaded through `import_module` because `0011_cache_entry_metadata` starts with a digit, so
    it is not a valid identifier and `from aigateway.migrations import ...` cannot name it.
    """
    return import_module("aigateway.migrations.0011_cache_entry_metadata")


def test_the_migration_is_atomic_so_a_crash_mid_downgrade_cannot_half_apply() -> None:
    """Non-atomic would run the downgrade's reverse operations in separate transactions — a
    crash between `AddField`'s reverse (drops the column, rebuilds the SQLite table)
    and the index-restore step would then leave the database with both the column AND the
    indexes gone, with nothing to roll it back. Atomic keeps the whole migration one unit."""
    assert _migration_0011().Migration.atomic is True


def test_the_postgres_ddl_runs_under_a_bounded_lock_timeout() -> None:
    """ADD COLUMN needs ACCESS EXCLUSIVE; WAITING for it is what queues every later reader."""
    module = _migration_0011()

    assert 0 < module._LOCK_TIMEOUT_MS <= 5_000
    assert "lock_timeout" in module._SET_LOCK_TIMEOUT_SQL


def test_the_lock_timeout_is_scoped_to_the_migration_transaction_not_the_session() -> None:
    """`SET LOCAL`, not plain `SET` — a session-wide `SET` would leak the timeout into whatever
    runs next on the same connection once the migration's (atomic) transaction commits."""
    assert "SET LOCAL" in _migration_0011()._SET_LOCK_TIMEOUT_SQL


def test_0011_still_applies_cleanly_on_sqlite_under_the_bounded_lock_change(
    populated_0010: tuple[Path, str, str],
) -> None:
    """SQLite never executes the lock-timeout SQL, but the migration must still run end to end."""
    db, url, _key = populated_0010

    _migrate(url)

    assert _COLUMN in _columns(db)


# --- Finding 1 — a stale metadata block must be impossible, whatever binary writes -------------


def test_the_trigger_fires_only_when_the_response_changes_without_its_block() -> None:
    """The WHEN clause is the whole design: it keeps the hot path out of the function body."""
    sql = _migration_0011()._CREATE_TRIGGER_SQL

    assert "BEFORE UPDATE" in sql
    assert "NEW.response_json IS DISTINCT FROM OLD.response_json" in sql
    assert "NEW.metadata_json IS NOT DISTINCT FROM OLD.metadata_json" in sql


def test_the_reverse_drops_the_trigger_and_its_function() -> None:
    """A rollback leaving a trigger that references a dropped column breaks every write."""
    sql = _migration_0011()._DROP_TRIGGER_SQL

    assert "DROP TRIGGER" in sql
    assert "DROP FUNCTION" in sql


def test_the_trigger_is_installed_on_postgres_only() -> None:
    """SQLite is local single-binary development; the rolling-upgrade hazard cannot arise there."""
    module = _migration_0011()

    assert module._LOCKING_DIALECTS == frozenset({"postgres"})


# --- Finding I1 (review round 2) — the hot path must skip the trigger, not just its body -------


def test_the_trigger_is_scoped_to_response_json_so_a_hit_count_bump_never_considers_it() -> None:
    """`UPDATE OF response_json` is decided from the statement's SET list, before any row or WHEN
    clause is looked at. Without this column list, a `hit_count`/`last_hit_at`-only UPDATE (the
    cache-hit hot path) would still evaluate the WHEN clause on every hit — and on two equal,
    likely out-of-line TOASTed `response_json` values, that comparison pays for a TOAST fetch, two
    pglz decompressions and a full `memcmp`, only to conclude "unchanged". The column list, not
    the WHEN clause, is what keeps the hot path out of the trigger machinery entirely.
    """
    sql = _migration_0011()._CREATE_TRIGGER_SQL

    assert "BEFORE UPDATE OF response_json" in sql
