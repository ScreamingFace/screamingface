"""Migration 0016 removes `migration_note` from the migration state only (OME-1138, L4c-1).

Replays the deployed upgrade path on SQLite: migrate to ``0015``, seed a real account, a real
Connection and a marker row that still carries a note, then apply ``0016`` on the populated
database. The PostgreSQL half is
``tests/integration/test_migration_0016_forget_migration_note_postgres.py``.

# FEATURE: OME-1138 close-out, L4c in two releases (owner, 2026-11-09). Tortoise names every
# declared field in its SELECT and INSERT, so an image whose model still declares the note needs
# the column: the old Pods during a rollout, and any image a rollback returns to. This step stops
# declaring it; L4c-2's `0017` drops the column one gateway release later.
# INVARIANT: `0016` runs no SQL in either direction — every schema object and every row, the note
# included, is exactly as it was.
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

from aigateway.core.provider_access.models import ProviderCredentialSlot

APP_DIR = Path(__file__).resolve().parents[2]
_SRC = APP_DIR / "src" / "aigateway"
_TABLE = "provider_credential_slots"
_COLUMN = "migration_note"
_PREVIOUS = "0015_cache_entry_write_order"
_MIGRATION = "0016_forget_migration_note"


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _snapshot(db: Path) -> tuple[set[tuple[str, str, str, str | None]], list[tuple[object, ...]]]:
    """Every schema object outside the migration recorder, and every marker row with its note."""
    with sqlite3.connect(db) as conn:
        objects = {
            (row[0], row[1], row[2], row[3])
            for row in conn.execute("select type, name, tbl_name, sql from sqlite_master")
            if row[2] != "tortoise_migrations"
        }
        markers = conn.execute(
            f"select account_id, provider, generation, migration_state, {_COLUMN},"
            f" effective_connection_id from {_TABLE}"
        ).fetchall()
    return objects, markers


def _seed(db: Path) -> None:
    """A real account, a real Connection and a marker that still carries a note."""
    account_id, connection_id = str(uuid.uuid4()), str(uuid.uuid4())
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
            (connection_id, account_id),
        )
        conn.execute(
            f"insert into {_TABLE} (id, provider, generation, migration_state, {_COLUMN},"
            " updated_at, account_id, effective_connection_id)"
            " values (?, 'anthropic', 2, 'migrated', 'left by the retired backfill',"
            " current_timestamp, ?, ?)",
            (str(uuid.uuid4()), account_id, connection_id),
        )


@pytest.fixture
def at_0015(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "populated-0015.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate", "models", _PREVIOUS)
    _seed(db)
    return db, url


def test_0016_runs_no_sql_on_a_populated_database(at_0015: tuple[Path, str]) -> None:
    db, url = at_0015
    before = _snapshot(db)
    assert any(_COLUMN in (sql or "") for _, name, _, sql in before[0] if name == _TABLE)

    _tortoise(url, "migrate", "models", _MIGRATION)

    assert _snapshot(db) == before


def test_0016_downgrade_runs_no_sql(at_0015: tuple[Path, str]) -> None:
    db, url = at_0015
    before = _snapshot(db)
    _tortoise(url, "migrate", "models", _MIGRATION)

    _tortoise(url, "downgrade", "models", _PREVIOUS)

    assert _snapshot(db) == before


def test_0016_rerun_is_a_noop(at_0015: tuple[Path, str]) -> None:
    _, url = at_0015
    _tortoise(url, "migrate", "models", _MIGRATION)

    rerun = _tortoise(url, "migrate", "models", _MIGRATION)

    assert "No migrations to apply" in rerun.stdout


def test_0016_depends_on_0015() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_the_marker_model_has_no_note_field() -> None:
    assert _COLUMN not in ProviderCredentialSlot._meta.fields_map


def test_no_gateway_source_outside_the_migrations_names_the_column() -> None:
    # Spec §8: the column lives on only in migration history.
    naming = [
        str(path.relative_to(_SRC))
        for path in _SRC.rglob("*.py")
        if "migrations" not in path.relative_to(_SRC).parts
        and _COLUMN in path.read_text(encoding="utf-8")
    ]
    assert naming == []


def test_autodetector_proposes_no_marker_change() -> None:
    """The projected state after 0016 equals the declared model — no phantom pending change.

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
        f"autodetector proposes {marker_ops} — migration 0016 and the model disagree, so a future "
        "`makemigrations` would propose the field again"
    )
