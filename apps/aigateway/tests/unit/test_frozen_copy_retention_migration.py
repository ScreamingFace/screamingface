"""Migration 0018 adds the frozen copy retention columns and index
(OME-1947, spec erd.md section 5)."""

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
_PREVIOUS = "0017_drop_migration_note"
_MIGRATION = "0018_frozen_copy_retention"
_NEW_COLUMNS = ("claimed_at", "swept_at", "purged_at")


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


def _index_columns(db: Path, table: str) -> list[list[str]]:
    with sqlite3.connect(db) as conn:
        return [
            [row[2] for row in conn.execute(f"pragma index_info({index[1]})")]
            for index in conn.execute(f"pragma index_list({table})")
        ]


def test_0018_depends_on_the_latest_prior_migration() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_0018_adds_three_nullable_columns(migrated: Path) -> None:
    cols = _columns(migrated, "frozen_copies")
    for name in _NEW_COLUMNS:
        assert name in cols
        assert cols[name][1] == 0


def test_0018_indexes_status_and_purged_at(migrated: Path) -> None:
    assert ["status", "purged_at"] in _index_columns(migrated, "frozen_copies")


def test_0018_downgrade_drops_the_columns_and_the_index_only(tmp_path: Path) -> None:
    db = tmp_path / "down.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate")
    _tortoise(url, "downgrade", "models", _PREVIOUS)

    copy_columns = _columns(db, "frozen_copies")
    for name in _NEW_COLUMNS:
        assert name not in copy_columns
    assert ["status", "purged_at"] not in _index_columns(db, "frozen_copies")
    assert ["account_id"] in _index_columns(db, "frozen_copies")
    with sqlite3.connect(db) as conn:
        copy_fks = {
            row[2]: row[6] for row in conn.execute("pragma foreign_key_list(frozen_copies)")
        }
    assert copy_fks == {"accounts": "CASCADE"}
    assert ["frozen_copy_id", "seq"] in _index_columns(db, "frozen_copy_entries")
    assert set(copy_columns) == {
        "id",
        "account_id",
        "status",
        "entries",
        "entry_seq",
        "provenance",
        "created_at",
        "sealed_at",
    }


def test_0018_applies_again_after_a_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "reapply.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate")
    _tortoise(url, "downgrade", "models", _PREVIOUS)
    _tortoise(url, "migrate")

    cols = _columns(db, "frozen_copies")
    for name in _NEW_COLUMNS:
        assert name in cols
    assert ["status", "purged_at"] in _index_columns(db, "frozen_copies")


def test_autodetector_proposes_no_frozen_copy_retention_change() -> None:
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
