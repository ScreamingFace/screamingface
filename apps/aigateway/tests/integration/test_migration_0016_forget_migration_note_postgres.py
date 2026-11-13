"""PostgreSQL evidence for migration 0016, the state-only removal of `migration_note` (L4c-1).

The hosted gateway is Postgres, so the property the unit suite pins on SQLite
(``tests/unit/test_migration_0016_forget_migration_note.py``) is pinned on the deployed dialect
too: on a populated database ``0016`` runs no SQL in either direction, so the column an older
image's model still names stays where it was, with its rows.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_TABLE = "provider_credential_slots"
_PREVIOUS = "0015_cache_entry_write_order"
_MIGRATION = "0016_forget_migration_note"


@pytest.fixture(scope="module")
def postgres_server() -> Generator[PostgresContainer, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        yield postgres


def _database_url(postgres: PostgresContainer, dbname: str) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/{dbname}"
    )


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=_APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


async def _populated_at_0015(postgres: PostgresContainer) -> str:
    dbname = f"m0016_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(_database_url(postgres, postgres.dbname))
    try:
        await admin.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await admin.close()
    database_url = _database_url(postgres, dbname)
    _tortoise(database_url, "migrate", "models", _PREVIOUS)
    account_id, connection_id = uuid.uuid4(), uuid.uuid4()
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            "insert into accounts (id, username, password_hash, created_at, is_active)"
            " values ($1, 'u1', 'x', now(), true)",
            account_id,
        )
        await conn.execute(
            "insert into oauth_connections"
            " (id, provider, label, status, credential_locator, created_at, account_id)"
            " values ($1, 'anthropic', 'work', 'active', '{}'::jsonb, now(), $2)",
            connection_id,
            account_id,
        )
        await conn.execute(
            f"insert into {_TABLE} (id, provider, generation, migration_state, migration_note,"
            " updated_at, account_id, effective_connection_id)"
            " values ($1, 'anthropic', 2, 'migrated', 'left by the retired backfill', now(),"
            " $2, $3)",
            uuid.uuid4(),
            account_id,
            connection_id,
        )
    finally:
        await conn.close()
    return database_url


async def _shape(database_url: str) -> dict[str, Any]:
    """The marker table's columns, indexes and constraints, plus its rows with the note."""
    conn = await asyncpg.connect(database_url)
    try:
        columns = {
            tuple(row)
            for row in await conn.fetch(
                "select column_name, data_type, character_maximum_length, is_nullable,"
                " column_default from information_schema.columns where table_name = $1",
                _TABLE,
            )
        }
        indexes = {
            tuple(row)
            for row in await conn.fetch(
                "select indexname, indexdef from pg_indexes where tablename = $1", _TABLE
            )
        }
        constraints = {
            tuple(row)
            for row in await conn.fetch(
                "select conname, contype, pg_get_constraintdef(oid)"
                " from pg_constraint where conrelid = $1::regclass",
                _TABLE,
            )
        }
        markers = [tuple(row) for row in await conn.fetch(f"select * from {_TABLE}")]
    finally:
        await conn.close()
    return {"columns": columns, "indexes": indexes, "constraints": constraints, "markers": markers}


@pytest.mark.asyncio
async def test_0016_runs_no_sql_in_either_direction_on_postgres(
    postgres_server: PostgresContainer,
) -> None:
    database_url = await _populated_at_0015(postgres_server)
    before = await _shape(database_url)
    assert "migration_note" in {column[0] for column in before["columns"]}

    _tortoise(database_url, "migrate", "models", _MIGRATION)
    after_upgrade = await _shape(database_url)
    _tortoise(database_url, "downgrade", "models", _PREVIOUS)

    assert after_upgrade == before
    assert await _shape(database_url) == before
