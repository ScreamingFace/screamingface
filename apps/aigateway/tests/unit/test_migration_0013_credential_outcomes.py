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
_PREVIOUS = "0012_provider_credential_slots"
_MIGRATION = "0013_credential_operational_outcomes"
_FIELDS = {
    "credential_revision": 1,
    "next_dispatch_sequence": 0,
    "last_outcome_sequence": 0,
    "last_operational_outcome": None,
    "last_outcome_at": None,
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


@pytest.fixture
def populated_0012(tmp_path: Path) -> tuple[Path, str]:
    db = tmp_path / "populated-0012.sqlite3"
    url = f"sqlite://{db}"
    _tortoise(url, "migrate", "models", _PREVIOUS)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into credential_blobs"
            " (id, service, account, value, created_at, updated_at)"
            " values (?, 'aigateway:openrouter:test', 'default', 'ciphertext',"
            " current_timestamp, current_timestamp)",
            (str(uuid.uuid4()),),
        )
    return db, url


def test_0013_adds_a_clean_register_without_rewriting_the_blob(
    populated_0012: tuple[Path, str],
) -> None:
    db, url = populated_0012
    _tortoise(url, "migrate")

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from credential_blobs").fetchone()

    assert row is not None
    assert row["value"] == "ciphertext"
    assert {name: row[name] for name in _FIELDS} == _FIELDS


def test_0013_depends_on_the_pair_authority_migration() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")
    assert migration.Migration.dependencies == [("models", _PREVIOUS)]


def test_0013_downgrade_preserves_the_blob(populated_0012: tuple[Path, str]) -> None:
    db, url = populated_0012
    _tortoise(url, "migrate")
    _tortoise(url, "downgrade", "models", _PREVIOUS)

    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(credential_blobs)")}
        value = conn.execute("select value from credential_blobs").fetchone()
        indexed_columns = {
            column[2]
            for index in conn.execute("pragma index_list(credential_blobs)")
            for column in conn.execute(f"pragma index_info({index[1]})")
        }

    assert not set(_FIELDS) & columns
    assert value == ("ciphertext",)
    assert {"service", "account"} <= indexed_columns

    with sqlite3.connect(db) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into credential_blobs"
            " (id, service, account, value, created_at, updated_at)"
            " values (?, 'aigateway:openrouter:test', 'default', 'duplicate',"
            " current_timestamp, current_timestamp)",
            (str(uuid.uuid4()),),
        )

    _tortoise(url, "migrate")
    with sqlite3.connect(db) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "insert into credential_blobs"
            " (id, service, account, value, created_at, updated_at)"
            " values (?, 'aigateway:openrouter:test', 'default', 'duplicate',"
            " current_timestamp, current_timestamp)",
            (str(uuid.uuid4()),),
        )


def test_0013_installs_a_postgres_guard_for_pre_0013_writers() -> None:
    migration = import_module(f"aigateway.migrations.{_MIGRATION}")

    assert "BEFORE UPDATE OF value" in migration._CREATE_REVISION_GUARD_SQL
    assert (
        "NEW.credential_revision IS NOT DISTINCT FROM OLD.credential_revision"
        in migration._CREATE_REVISION_GUARD_SQL
    )
    assert migration.Migration.operations[-1].code is migration._install_revision_guard


def test_0013_preserves_pre_0013_sqlite_writer_rowcount(
    populated_0012: tuple[Path, str],
) -> None:
    _, url = populated_0012
    _tortoise(url, "migrate")

    # INVARIANT: legacy ORMStore.mutate treats any count other than one as a CAS conflict.
    script = """
import asyncio
from tortoise import Tortoise, connections
from aigateway.db import TORTOISE_CONFIG

async def main():
    await Tortoise.init(config=TORTOISE_CONFIG)
    try:
        updated, _ = await connections.get("default").execute_query(
            "update credential_blobs set value = 'old-writer-replacement'"
        )
        print(updated)
    finally:
        await Tortoise.close_connections()

asyncio.run(main())
"""
    update = subprocess.run(
        [sys.executable, "-c", script],
        cwd=APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": url},
        check=True,
        capture_output=True,
        text=True,
    )

    assert update.stdout.strip() == "1"
