"""Migration 0019 adds the clock start `retention_from` and stamps the sealed copies
(OME-1947, spec erd.md section 5, prd/copy-sweep.md S-33)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import uuid4

APP_DIR = Path(__file__).resolve().parents[2]
_PREVIOUS = "0018_frozen_copy_retention"
_MIGRATION = "0019_frozen_copy_retention_clock"
_READ_SCRIPT = """
import asyncio, json, sys
from tortoise import Tortoise
from aigateway.db import build_tortoise_config

async def main():
    await Tortoise.init(config=build_tortoise_config(sys.argv[1]), _enable_global_fallback=True)
    try:
        from aigateway.core.frozen_copy.models import FrozenCopy
        rows = []
        for copy in await FrozenCopy.all():
            value = copy.retention_from
            rows.append({"id": str(copy.id), "status": copy.status,
                         "value": None if value is None else value.isoformat(),
                         "aware": value is not None and value.tzinfo is not None})
        print(json.dumps(rows))
    finally:
        await Tortoise.close_connections()

asyncio.run(main())
"""


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _columns(db: Path, table: str) -> dict[str, tuple[str, int]]:
    with sqlite3.connect(db) as conn:
        return {row[1]: (row[2], row[3]) for row in conn.execute(f"pragma table_info({table})")}


def _index_columns(db: Path, table: str) -> list[list[str]]:
    with sqlite3.connect(db) as conn:
        return [
            [row[2] for row in conn.execute(f"pragma index_info({index[1]})")]
            for index in conn.execute(f"pragma index_list({table})")
        ]


def _read_through_model(database_url: str) -> dict[str, dict[str, object]]:
    result = subprocess.run(
        [sys.executable, "-c", _READ_SCRIPT, database_url],
        cwd=APP_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(result.stdout.strip().splitlines()[-1])
    return {row["id"]: row for row in rows}


def _seed(db: Path) -> tuple[str, str, str]:
    account_id = str(uuid4())
    sealed_a, sealed_b, open_c = str(uuid4()), str(uuid4()), str(uuid4())
    created = "2026-01-01 00:00:00+00:00"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into accounts (id, username, password_hash, created_at, is_active)"
            " values (?, 'u1', 'x', current_timestamp, 1)",
            (account_id,),
        )
        for copy_id, status, sealed_at in (
            (sealed_a, "sealed", "2026-01-02 00:00:00+00:00"),
            (sealed_b, "sealed", "2026-01-03 00:00:00+00:00"),
            (open_c, "open", None),
        ):
            conn.execute(
                "insert into frozen_copies"
                " (id, account_id, status, entries, entry_seq, created_at, sealed_at)"
                " values (?, ?, ?, 0, 0, ?, ?)",
                (copy_id, account_id, status, created, sealed_at),
            )
    return sealed_a, sealed_b, open_c


def test_0019_depends_on_0018() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_0019_stamps_each_sealed_copy_with_one_aware_utc_time(tmp_path: Path) -> None:
    db = tmp_path / "stamp.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate")
    _tortoise(url, "downgrade", "models", _PREVIOUS)
    sealed_a, sealed_b, open_c = _seed(db)
    started = datetime.now(UTC)
    _tortoise(url, "migrate")
    ended = datetime.now(UTC)

    assert _columns(db, "frozen_copies")["retention_from"][1] == 0
    with sqlite3.connect(db) as conn:
        raw = dict(conn.execute("select id, retention_from from frozen_copies").fetchall())
    assert raw[open_c] is None
    assert raw[sealed_a] is not None
    assert raw[sealed_a] == raw[sealed_b]
    assert raw[sealed_a].endswith("+00:00")

    rows = _read_through_model(url)
    assert rows[sealed_a]["aware"] is True
    assert rows[sealed_b]["aware"] is True
    value = rows[sealed_a]["value"]
    assert isinstance(value, str)
    assert rows[sealed_b]["value"] == value
    assert started <= datetime.fromisoformat(value) <= ended
    assert rows[open_c]["value"] is None


def test_0019_downgrade_drops_only_retention_from(tmp_path: Path) -> None:
    db = tmp_path / "down.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate")
    _tortoise(url, "downgrade", "models", _PREVIOUS)

    columns = _columns(db, "frozen_copies")
    assert "retention_from" not in columns
    for name in ("claimed_at", "swept_at", "purged_at"):
        assert name in columns
    assert ["status", "purged_at"] in _index_columns(db, "frozen_copies")
    assert ["account_id"] in _index_columns(db, "frozen_copies")
    with sqlite3.connect(db) as conn:
        copy_fks = {
            row[2]: row[6] for row in conn.execute("pragma foreign_key_list(frozen_copies)")
        }
    assert copy_fks == {"accounts": "CASCADE"}


def test_autodetector_proposes_no_retention_clock_change() -> None:
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
