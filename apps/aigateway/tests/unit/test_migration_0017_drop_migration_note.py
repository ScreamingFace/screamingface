"""Migration 0017 drops the pair marker's `migration_note` column (OME-1138 close-out, L4c-2).

Replays the deployed upgrade path on SQLite: migrate to ``0016``, seed a real account, a real
Connection and a marker row, then apply ``0017`` on the populated database. The PostgreSQL half is
``tests/integration/test_migration_0017_drop_migration_note_postgres.py``.

# FEATURE: OME-1138 close-out, L4c-2 — the second of the two schema steps (spec §4.3, §9 Q1). L4a
# stopped reading and writing the note, and L4c-1 (gateway 1.0.1) stopped declaring it. An
# environment still before L4c-1 takes a rollout window the owner accepts (spec §4.3, 2026-11-16).
# INVARIANT (D1): the drop keeps one marker per `(account_id, provider)`, enforced by the database.
# Tortoise's SQLite `RemoveField` rebuilds the table and loses `unique_together` (spec §4.3), so
# these tests pin every index and constraint of the table, not just the column list.
# INVARIANT: the upgrade refuses while a `quarantined` or noted row exists, and changes nothing.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from importlib import import_module
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
_TABLE = "provider_credential_slots"
_COLUMN = "migration_note"
_PREVIOUS = "0016_forget_migration_note"
_MIGRATION = "0017_drop_migration_note"
_COLUMNS_AFTER = {
    "id",
    "provider",
    "generation",
    "migration_state",
    "updated_at",
    "account_id",
    "effective_connection_id",
}


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def _columns(db: Path) -> dict[str, tuple[str, int, object, int]]:
    with _connect(db) as conn:
        rows = conn.execute(f"pragma table_info({_TABLE})").fetchall()
    return {
        row["name"]: (row["type"], row["notnull"], row["dflt_value"], row["pk"]) for row in rows
    }


def _indexes(db: Path) -> set[tuple[str, int, str, tuple[str, ...]]]:
    """Every index on the table, SQLite's own uniqueness autoindex included."""
    with _connect(db) as conn:
        found = set()
        for index in conn.execute(f"pragma index_list({_TABLE})").fetchall():
            columns = conn.execute(f"pragma index_info('{index['name']}')").fetchall()
            found.add(
                (
                    index["name"],
                    index["unique"],
                    index["origin"],
                    tuple(column["name"] for column in columns),
                )
            )
    return found


def _foreign_keys(db: Path) -> set[tuple[str, str, str, str]]:
    with _connect(db) as conn:
        rows = conn.execute(f"pragma foreign_key_list({_TABLE})").fetchall()
    return {(row["table"], row["from"], row["to"], row["on_delete"]) for row in rows}


def _other_schema_objects(db: Path) -> set[tuple[str, str, str, str | None]]:
    """Every schema object but the marker table's own definition, which the drop must change."""
    with _connect(db) as conn:
        rows = conn.execute("select type, name, tbl_name, sql from sqlite_master").fetchall()
    return {
        (row["type"], row["name"], row["tbl_name"], row["sql"])
        for row in rows
        if not (row["type"] == "table" and row["name"] == _TABLE)
    }


def _seed(db: Path, *, state: str = "migrated", note: str | None = None) -> tuple[str, str]:
    """A real account, a real Connection and the pair's marker — the populated-database replay."""
    account_id, connection_id = str(uuid.uuid4()), str(uuid.uuid4())
    with _connect(db) as conn:
        conn.execute(
            "insert into accounts (id, username, password_hash, created_at, is_active)"
            " values (?, 'u1', 'x', current_timestamp, 1)",
            (account_id,),
        )
        conn.execute(
            "insert into oauth_connections"
            " (id, provider, label, status, credential_locator, created_at, account_id)"
            " values (?, 'anthropic', 'work', 'active', '{}', current_timestamp, ?)",
            (connection_id, account_id),
        )
        conn.execute(
            f"insert into {_TABLE} (id, provider, generation, migration_state, {_COLUMN},"
            " updated_at, account_id, effective_connection_id)"
            " values (?, 'anthropic', 2, ?, ?, current_timestamp, ?, ?)",
            (str(uuid.uuid4()), state, note, account_id, connection_id),
        )
    return account_id, connection_id


def _markers(db: Path) -> list[tuple[str, str, int, str, str | None]]:
    with _connect(db) as conn:
        rows = conn.execute(
            f"select account_id, provider, generation, migration_state, effective_connection_id"
            f" from {_TABLE}"
        ).fetchall()
    return [tuple(row) for row in rows]


@pytest.fixture
def at_0016(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "populated-0016.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate", "models", _PREVIOUS)
    return db, url


def test_0017_drops_only_the_note_column_and_keeps_the_row(at_0016: tuple[Path, str]) -> None:
    db, url = at_0016
    account_id, connection_id = _seed(db)
    before = _columns(db)

    _tortoise(url, "migrate", "models", _MIGRATION)

    after = _columns(db)
    assert set(after) == _COLUMNS_AFTER
    assert after == {name: shape for name, shape in before.items() if name != _COLUMN}
    assert _markers(db) == [(account_id, "anthropic", 2, "migrated", connection_id)]


def test_0017_keeps_every_index_constraint_and_other_object(at_0016: tuple[Path, str]) -> None:
    db, url = at_0016
    _seed(db)
    indexes, foreign_keys, others = _indexes(db), _foreign_keys(db), _other_schema_objects(db)
    assert ("account_id", "provider") in {columns for _, unique, _, columns in indexes if unique}

    _tortoise(url, "migrate", "models", _MIGRATION)

    assert _indexes(db) == indexes
    assert _foreign_keys(db) == foreign_keys
    assert foreign_keys == {
        ("accounts", "account_id", "id", "CASCADE"),
        ("oauth_connections", "effective_connection_id", "id", "SET NULL"),
    }
    assert _other_schema_objects(db) == others, "0017 touched an object outside the marker table"


def test_0017_still_refuses_a_second_marker_for_a_pair(at_0016: tuple[Path, str]) -> None:
    db, url = at_0016
    account_id, _ = _seed(db)
    _tortoise(url, "migrate", "models", _MIGRATION)

    with _connect(db) as conn, pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(
            f"insert into {_TABLE} (id, provider, generation, migration_state, updated_at,"
            " account_id) values (?, 'anthropic', 1, 'none', current_timestamp, ?)",
            (str(uuid.uuid4()), account_id),
        )


def test_0017_lets_go_of_a_deleted_connection_and_follows_its_account(
    at_0016: tuple[Path, str],
) -> None:
    db, url = at_0016
    account_id, connection_id = _seed(db)
    _tortoise(url, "migrate", "models", _MIGRATION)

    with _connect(db) as conn:
        conn.execute("delete from oauth_connections where id = ?", (connection_id,))
    assert _markers(db) == [(account_id, "anthropic", 2, "migrated", None)]

    with _connect(db) as conn:
        conn.execute("delete from accounts where id = ?", (account_id,))
    assert _markers(db) == []


@pytest.mark.parametrize(
    ("state", "note", "counts"),
    [
        ("quarantined", None, "1 quarantined and 0 noted"),
        ("none", "left by the retired backfill", "0 quarantined and 1 noted"),
        ("quarantined", "left by the retired backfill", "1 quarantined and 1 noted"),
    ],
)
def test_0017_refuses_a_quarantined_or_noted_row_and_changes_nothing(
    at_0016: tuple[Path, str], state: str, note: str | None, counts: str
) -> None:
    db, url = at_0016
    _seed(db, state=state, note=note)
    columns, markers = _columns(db), _markers(db)

    with pytest.raises(subprocess.CalledProcessError) as refused:
        _tortoise(url, "migrate", "models", _MIGRATION)

    assert counts in refused.value.stderr
    assert _columns(db) == columns
    assert _markers(db) == markers

    # The operator's settlement (DEPLOYMENT.md, before an image that includes L4a) unblocks it.
    with _connect(db) as conn:
        conn.execute(f"update {_TABLE} set migration_state = 'none', {_COLUMN} = null")
    _tortoise(url, "migrate", "models", _MIGRATION)
    assert _COLUMN not in _columns(db)


def test_0017_downgrade_re_adds_a_nullable_note_and_moves_nothing_else(
    at_0016: tuple[Path, str],
) -> None:
    db, url = at_0016
    account_id, connection_id = _seed(db)
    columns, indexes, others = _columns(db), _indexes(db), _other_schema_objects(db)
    _tortoise(url, "migrate", "models", _MIGRATION)

    _tortoise(url, "downgrade", "models", _PREVIOUS)

    assert _columns(db) == columns
    assert columns[_COLUMN][1] == 0, "the re-added note must be nullable"
    assert _indexes(db) == indexes
    assert _other_schema_objects(db) == others
    assert _markers(db) == [(account_id, "anthropic", 2, "migrated", connection_id)]


def test_0017_rerun_is_a_noop(at_0016: tuple[Path, str]) -> None:
    _, url = at_0016
    _tortoise(url, "migrate", "models", _MIGRATION)

    rerun = _tortoise(url, "migrate", "models", _MIGRATION)

    assert "No migrations to apply" in rerun.stdout


def test_0017_depends_on_0016() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]
