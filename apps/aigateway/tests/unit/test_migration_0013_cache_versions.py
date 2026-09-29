"""Migration 0013 creates the five E14 cache-version tables (OME-1307, GW-capture).

Replays the deployed upgrade path on SQLite: migrate to ``0012``, seed a real account, then apply
``0013`` on the populated database. UPGRADE is five ``CREATE TABLE`` plus their indexes and touches
no existing table. DOWNGRADE drops exactly those five tables. The autodetector must stay silent
about them afterwards, so a later ``makemigrations`` never proposes them again.

# INVARIANT (erd.md 3.1-3.4, plan OD-2): ``cache_capture_entry.key_hash`` is NULLABLE, because a
# streaming call has a capture row and no key. One frozen version exists per
# ``(owner_account_id, trace_id)``, enforced by the database.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from importlib import import_module
from pathlib import Path

import pytest

from aigateway.db import TORTOISE_CONFIG

APP_DIR = Path(__file__).resolve().parents[2]
_PREVIOUS = "0012_provider_credential_slots"
_MIGRATION = "0013_cache_versions"
_MODELS_MODULE = "aigateway.core.cache_versions.models"
_EXPECTED_COLUMNS = {
    "request_cache_prompt": {"key_hash", "request_json", "created_at"},
    "cache_capture_entry": {
        "ordinal",
        "account_id",
        "trace_id",
        "key_hash",
        "outcome",
        "response_json",
        "created_at",
    },
    "cache_version": {
        "id",
        "owner_account_id",
        "trace_id",
        "status",
        "entry_count",
        "call_count",
        "missing_count",
        "coverage_status",
        "archive_sha256",
        "archive_key",
        "created_at",
    },
    "cache_version_blob": {
        "sha256",
        "request_json",
        "response_json",
        "metadata_json",
        "size_bytes",
    },
    "cache_version_entry": {"id", "version_id", "key_hash", "blob_id", "first_ordinal"},
}
_NULLABLE = {
    "cache_capture_entry": {"key_hash", "response_json"},
    "cache_version_blob": {"metadata_json"},
}
_TABLES = set(_EXPECTED_COLUMNS)


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute("select name from sqlite_master where type = 'table'").fetchall()
    return {row[0] for row in rows}


def _columns(db: Path, table: str) -> dict[str, sqlite3.Row]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"]: row for row in conn.execute(f"pragma table_info({table})")}


def _unique_indexes(db: Path, table: str) -> list[tuple[str, ...]]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        found: list[tuple[str, ...]] = []
        for index in conn.execute(f"pragma index_list({table})").fetchall():
            if not index["unique"]:
                continue
            columns = conn.execute(f"pragma index_info({index['name']})").fetchall()
            found.append(tuple(column["name"] for column in columns))
    return found


def _foreign_keys(db: Path, table: str) -> set[tuple[str, str, str]]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"pragma foreign_key_list({table})").fetchall()
    return {(row["table"], row["from"], row["on_delete"]) for row in rows}


def _schema_objects(db: Path) -> set[tuple[str, str, str]]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "select type, name, tbl_name from sqlite_master where name not like 'sqlite_%'"
        ).fetchall()
    return {(row[0], row[1], row[2]) for row in rows}


def _seed_account(db: Path) -> None:
    """A real row in an existing table: the populated-database replay."""
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into accounts (id, username, password_hash, created_at, is_active)"
            " values (?, 'u1', 'x', current_timestamp, 1)",
            (str(uuid.uuid4()),),
        )


@pytest.fixture
def populated_0012(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "populated-0012.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate", "models", _PREVIOUS)
    _seed_account(db)
    return db, url


def test_0013_creates_the_five_tables_on_a_populated_database(
    populated_0012: tuple[Path, str],
) -> None:
    db, url = populated_0012
    assert not (_TABLES & _tables(db))

    _tortoise(url, "migrate")

    assert _TABLES <= _tables(db)
    for table, expected in _EXPECTED_COLUMNS.items():
        columns = _columns(db, table)
        assert set(columns) == expected, table
        for name, column in columns.items():
            assert bool(column["notnull"]) == (name not in _NULLABLE.get(table, set())), (
                table,
                name,
            )
    assert _foreign_keys(db, "cache_version_entry") == {
        ("cache_version", "version_id", "RESTRICT"),
        ("cache_version_blob", "blob_id", "RESTRICT"),
    }
    assert (
        "version_id",
        "key_hash",
        "blob_id",
    ) in _unique_indexes(db, "cache_version_entry")
    assert _columns(db, "request_cache_prompt")["key_hash"]["pk"] == 1
    assert _columns(db, "cache_capture_entry")["ordinal"]["pk"] == 1


def test_0013_capture_key_hash_is_nullable(populated_0012: tuple[Path, str]) -> None:
    db, url = populated_0012
    _tortoise(url, "migrate")

    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into cache_capture_entry (account_id, trace_id, key_hash, outcome, created_at)"
            " values ('a', ?, NULL, 'bypass', current_timestamp)",
            ("a" * 32,),
        )
        count = conn.execute(
            "select count(*) from cache_capture_entry where key_hash is null"
        ).fetchone()[0]

    assert count == 1


def test_0013_version_is_unique_per_owner_and_trace(populated_0012: tuple[Path, str]) -> None:
    db, url = populated_0012
    _tortoise(url, "migrate")
    insert = (
        "insert into cache_version (id, owner_account_id, trace_id, status, entry_count,"
        " call_count, missing_count, coverage_status, archive_sha256, archive_key, created_at)"
        " values (?, ?, ?, 'frozen', 0, 0, 0, 'complete', 'h', 'k', current_timestamp)"
    )
    with sqlite3.connect(db) as conn:
        conn.execute(insert, (str(uuid.uuid4()), "owner", "t" * 32))
        conn.execute(insert, (str(uuid.uuid4()), "other-owner", "t" * 32))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, (str(uuid.uuid4()), "owner", "t" * 32))


def test_0013_downgrade_drops_only_the_five_tables(populated_0012: tuple[Path, str]) -> None:
    db, url = populated_0012
    before = _schema_objects(db)
    _tortoise(url, "migrate")
    with_tables = _schema_objects(db)
    assert {tbl for _, _, tbl in with_tables} >= _TABLES

    _tortoise(url, "downgrade", "models", _PREVIOUS)

    assert not (_TABLES & _tables(db))
    assert _schema_objects(db) == before, "downgrade touched an object outside the five tables"


def test_0013_depends_on_0012() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_the_cache_version_models_are_registered_with_the_orm() -> None:
    # WHY: `generate_schemas` (tests, local dev) and the autodetector both read this list.
    assert _MODELS_MODULE in TORTOISE_CONFIG["apps"]["models"]["models"]


def test_autodetector_proposes_no_cache_version_change() -> None:
    """The projected state after 0013 equals the declared models: no phantom pending change.

    Runs out of process because the autodetector needs its own ``Tortoise.init`` and the unit suite
    shares one global registry.

    # WHY (D8): Tortoise 1.1.8 overwrites the ``source_field`` of a foreign key with ``<attr>_id``
    # at init. A custom FK column name (``blob_sha256``) would therefore make the autodetector
    # propose ``AlterField`` on ``CacheVersionEntry`` for ever. The FK columns keep native names.
    """
    script = """
import asyncio, json
from tortoise import Tortoise
from tortoise.migrations.autodetector import MigrationAutodetector
from aigateway.db import build_tortoise_config

async def main():
    config = build_tortoise_config("sqlite://:memory:")
    await Tortoise.init(config=config, init_connections=False)
    try:
        writers = await MigrationAutodetector(Tortoise.apps, config["apps"]).changes()
        print(json.dumps([op.describe() for w in writers for op in w.operations]))
    finally:
        await Tortoise.close_connections()

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=APP_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    proposed = json.loads(result.stdout.strip().splitlines()[-1])

    version_ops = [
        op
        for op in proposed
        if any(name in op for name in ("CacheVersion", "CacheCapture", "RequestCachePrompt"))
        or any(table in op for table in _TABLES)
    ]
    assert version_ops == [], (
        f"autodetector proposes {version_ops}: migration 0013 and the models disagree, so a "
        "future `makemigrations` would propose the cache-version tables again"
    )
