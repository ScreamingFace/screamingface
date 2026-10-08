"""Migration 0014 creates the frozen-copy tables and matches the models (OME-1307, design §3)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
_PREVIOUS = "0013_credential_operational_outcomes"
_MIGRATION = "0014_frozen_copies"


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def migrated(tmp_path: Path) -> Path:
    db = tmp_path / "migrated.sqlite3"
    _tortoise(f"sqlite://{db}", "migrate")
    return db


def _columns(db: Path, table: str) -> dict[str, tuple[str, int]]:
    with sqlite3.connect(db) as conn:
        return {row[1]: (row[2], row[3]) for row in conn.execute(f"pragma table_info({table})")}


def test_0014_depends_on_the_latest_prior_migration() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_0014_creates_both_tables_with_the_design_columns(migrated: Path) -> None:
    copies = _columns(migrated, "frozen_copies")
    entries = _columns(migrated, "frozen_copy_entries")

    assert set(copies) == {"id", "account_id", "status", "entries", "created_at", "sealed_at"}
    assert set(entries) == {
        "id",
        "frozen_copy_id",
        "kind",
        "request_digest",
        "request_json",
        "response_json",
        "status_code",
        "created_at",
    }
    # `sealed_at` is the only nullable column of frozen_copies (NULL until sealed).
    assert [name for name, (_, notnull) in copies.items() if not notnull] == ["sealed_at"]


def test_0014_indexes_the_replay_lookup(migrated: Path) -> None:
    with sqlite3.connect(migrated) as conn:
        indexed = [
            [row[2] for row in conn.execute(f"pragma index_info({index[1]})")]
            for index in conn.execute("pragma index_list(frozen_copy_entries)")
        ]
    assert ["frozen_copy_id", "kind", "request_digest", "created_at"] in indexed


def test_0014_cascades_from_account_to_copy_to_entry(migrated: Path) -> None:
    with sqlite3.connect(migrated) as conn:
        copy_fks = {
            row[2]: row[6] for row in conn.execute("pragma foreign_key_list(frozen_copies)")
        }
        entry_fks = {
            row[2]: row[6] for row in conn.execute("pragma foreign_key_list(frozen_copy_entries)")
        }
    assert copy_fks == {"accounts": "CASCADE"}
    assert entry_fks == {"frozen_copies": "CASCADE"}


def test_0014_downgrade_drops_both_tables(tmp_path: Path) -> None:
    db = tmp_path / "downgrade.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate")
    _tortoise(url, "downgrade", "models", _PREVIOUS)

    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master")}
    assert "frozen_copies" not in tables
    assert "frozen_copy_entries" not in tables


def test_autodetector_proposes_no_frozen_copy_change() -> None:
    """Model and migration describe the same schema: `makemigrations` must stay silent.

    Runs out of process because the autodetector needs its own `Tortoise.init` and the unit
    suite shares one global Tortoise registry (same reason as test_migration_populated_db).
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
        [sys.executable, "-c", script], cwd=APP_DIR, check=True, capture_output=True, text=True
    )
    proposed = json.loads(result.stdout.strip().splitlines()[-1])
    assert [op for op in proposed if "FrozenCopy" in op] == []
