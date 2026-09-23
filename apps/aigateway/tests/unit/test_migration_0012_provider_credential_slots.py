"""Migration 0012 creates the pair authority marker table (OME-1208, Stage B S1).

Replays the deployed upgrade path on SQLite: migrate to ``0011``, seed a real account and a real
Connection, then apply ``0012`` on the populated database.

UPGRADE is one ``CREATE TABLE provider_credential_slots`` plus its indexes: no existing table is
touched or rebuilt, so nothing that 0009–0011 went out of their way to protect is at risk.
DOWNGRADE drops exactly that table. The autodetector must stay silent afterwards, so a later
``makemigrations`` never re-proposes the model (the drift the 0009 and 0011 suites also pin).

# INVARIANT (card v4 Stage B Target, D1): one marker per `(account_id, provider)` is enforced by
# the DATABASE (a unique index), with a conventional single primary key — Tortoise 1.1.8 has no
# partial unique index and no composite primary key. The marker follows its account (CASCADE) and
# lets go of a deleted Connection (SET NULL) rather than blocking the delete.
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
_TABLE = "provider_credential_slots"
_PREVIOUS = "0011_cache_entry_metadata"
_MIGRATION = "0012_provider_credential_slots"
_MODELS_MODULE = "aigateway.core.provider_access.models"
_EXPECTED_COLUMNS = {
    "id",
    "provider",
    "generation",
    "migration_state",
    "migration_note",
    "updated_at",
    "account_id",
    "effective_connection_id",
}
_NULLABLE = {"migration_note", "effective_connection_id"}


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


def _columns(db: Path) -> dict[str, sqlite3.Row]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"]: row for row in conn.execute(f"pragma table_info({_TABLE})")}


def _unique_indexes(db: Path) -> list[tuple[str, ...]]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        found: list[tuple[str, ...]] = []
        for index in conn.execute(f"pragma index_list({_TABLE})").fetchall():
            if not index["unique"]:
                continue
            columns = conn.execute(f"pragma index_info({index['name']})").fetchall()
            found.append(tuple(column["name"] for column in columns))
    return found


def _foreign_keys(db: Path) -> set[tuple[str, str, str]]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"pragma foreign_key_list({_TABLE})").fetchall()
    return {(row["table"], row["from"], row["on_delete"]) for row in rows}


def _schema_objects(db: Path) -> set[tuple[str, str, str]]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "select type, name, tbl_name from sqlite_master where name not like 'sqlite_%'"
        ).fetchall()
    return {(row[0], row[1], row[2]) for row in rows}


def _seed_account_and_connection(db: Path) -> None:
    """Real rows for both tables the marker references — the populated-database replay."""
    account_id = str(uuid.uuid4())
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into accounts (id, username, password_hash, created_at, is_active)"
            " values (?, 'u1', 'x', current_timestamp, 1)",
            (account_id,),
        )
        conn.execute(
            "insert into oauth_connections"
            " (id, provider, label, status, credential_locator, created_at, account_id)"
            " values (?, 'anthropic', 'work', 'active', '{}', current_timestamp, ?)",
            (str(uuid.uuid4()), account_id),
        )


@pytest.fixture
def populated_0011(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "populated-0011.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate", "models", _PREVIOUS)
    _seed_account_and_connection(db)
    return db, url


def test_0012_creates_the_marker_table_on_a_populated_database(
    populated_0011: tuple[Path, str],
) -> None:
    db, url = populated_0011
    assert _TABLE not in _tables(db)

    _tortoise(url, "migrate")

    columns = _columns(db)
    assert set(columns) == _EXPECTED_COLUMNS
    for name, column in columns.items():
        assert bool(column["notnull"]) == (name not in _NULLABLE), name


def test_0012_enforces_one_marker_per_pair(populated_0011: tuple[Path, str]) -> None:
    db, url = populated_0011
    _tortoise(url, "migrate")

    # The primary key's own automatic index aside, exactly one uniqueness rule: the pair.
    assert [cols for cols in _unique_indexes(db) if cols != ("id",)] == [("account_id", "provider")]


def test_0012_follows_its_account_and_lets_go_of_a_deleted_connection(
    populated_0011: tuple[Path, str],
) -> None:
    db, url = populated_0011
    _tortoise(url, "migrate")

    assert _foreign_keys(db) == {
        ("accounts", "account_id", "CASCADE"),
        ("oauth_connections", "effective_connection_id", "SET NULL"),
    }


def test_0012_rerun_is_a_noop(populated_0011: tuple[Path, str]) -> None:
    _, url = populated_0011
    _tortoise(url, "migrate")

    rerun = _tortoise(url, "migrate")

    assert "No migrations to apply" in rerun.stdout


def test_0012_downgrade_drops_only_the_marker_table(populated_0011: tuple[Path, str]) -> None:
    db, url = populated_0011
    _tortoise(url, "migrate")
    with_marker = _schema_objects(db)
    assert any(tbl_name == _TABLE for _, _, tbl_name in with_marker)

    _tortoise(url, "downgrade", "models", _PREVIOUS)

    assert _TABLE not in _tables(db)
    assert _schema_objects(db) == {obj for obj in with_marker if obj[2] != _TABLE}, (
        "downgrade touched an object outside the marker table"
    )


def test_0012_depends_on_0011() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_the_marker_model_is_registered_with_the_orm() -> None:
    # WHY: `generate_schemas` (tests, local dev) and the autodetector both read this list; a model
    # the migration creates but the ORM does not know would drift on the very next run.
    assert _MODELS_MODULE in TORTOISE_CONFIG["apps"]["models"]["models"]


def test_autodetector_proposes_no_marker_change() -> None:
    """The projected state after 0012 equals the declared model — no phantom pending change.

    Runs out of process because the autodetector needs its own ``Tortoise.init`` and the unit suite
    shares one global registry.
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

    marker_ops = [op for op in proposed if "ProviderCredentialSlot" in op or _TABLE in op]
    assert marker_ops == [], (
        f"autodetector proposes {marker_ops} — migration 0012 and the model disagree, so a future "
        "`makemigrations` would propose the marker table again"
    )
