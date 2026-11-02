"""Migration 0015: the write-order index on ``request_cache_entries`` (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: 0015 follows 0014; it adds exactly one composite index on
``(updated_at, key_hash)`` — the order the community-cache pages are read in — without touching a
row or another index; it downgrades cleanly; and the model and the migration describe the same
schema, so ``makemigrations`` stays silent about the table.
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

APP_DIR = Path(__file__).resolve().parents[2]
_PREVIOUS = "0014_frozen_copies"
_MIGRATION = "0015_cache_entry_write_order"
_TABLE = "request_cache_entries"


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _indexes(db: Path) -> dict[str, list[str]]:
    with sqlite3.connect(db) as conn:
        return {
            index[1]: [column[2] for column in conn.execute(f"pragma index_info({index[1]})")]
            for index in conn.execute(f"pragma index_list({_TABLE})")
        }


@pytest.fixture
def populated_0014(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "populated-0014.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate", "models", _PREVIOUS)
    with sqlite3.connect(db) as conn:
        conn.execute(
            f"insert into {_TABLE} (id, key_hash, prompt_hash, provider, model, response_json,"
            " response_size_bytes, created_at, updated_at, hit_count)"
            " values (?, ?, ?, 'openrouter', 'm', '{\"ok\": true}', 12,"
            " '2026-10-01 12:00:00.000000+00:00', '2026-10-02 12:00:00.000000+00:00', 3)",
            (str(uuid.uuid4()), "a" * 64, "p" * 64),
        )
    return db, url


def test_0015_depends_on_the_frozen_copy_migration() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_0015_adds_only_the_write_order_index_and_keeps_the_rows(
    populated_0014: tuple[Path, str],
) -> None:
    db, url = populated_0014
    before = _indexes(db)

    _tortoise(url, "migrate")

    after = _indexes(db)
    added = {name: columns for name, columns in after.items() if name not in before}
    assert list(added.values()) == [["updated_at", "key_hash"]]
    assert {name: after[name] for name in before} == before
    with sqlite3.connect(db) as conn:
        row = conn.execute(f"select key_hash, hit_count, response_json from {_TABLE}").fetchone()
    assert row == ("a" * 64, 3, '{"ok": true}')


def test_0015_downgrade_drops_only_that_index(populated_0014: tuple[Path, str]) -> None:
    db, url = populated_0014
    before = _indexes(db)
    _tortoise(url, "migrate")

    _tortoise(url, "downgrade", "models", _PREVIOUS)

    assert _indexes(db) == before


def test_autodetector_proposes_no_request_cache_change() -> None:
    """Model and migration describe the same schema: `makemigrations` must stay silent.

    Out of process for the same reason as test_frozen_copy_migration: the autodetector needs
    its own `Tortoise.init`, and the unit suite shares one global registry.
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
    assert [op for op in proposed if "RequestCacheEntry" in op or _TABLE in op] == []
