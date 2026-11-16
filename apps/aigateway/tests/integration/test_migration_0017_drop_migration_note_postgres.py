"""PostgreSQL evidence for migration 0017, the `migration_note` drop (OME-1138 close-out, L4c-2).

The hosted gateway is Postgres, so the properties the unit suite pins on SQLite
(``tests/unit/test_migration_0017_drop_migration_note.py``) are pinned on the deployed dialect too:
on a populated database ``0017`` drops the column and keeps every index and constraint of the
marker table; it refuses a `quarantined` or noted row and changes nothing; the downgrade re-adds a
nullable column; and it gives up a blocked lock queue instead of stalling every marker read.

Each test migrates its own database in one shared container, so no test sees another's rows.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
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
from tortoise.migrations.api.migrate import migrate as _run_migration

from aigateway.db import build_tortoise_config, close_db, init_db

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_TABLE = "provider_credential_slots"
_COLUMN = "migration_note"
_PREVIOUS = "0016_forget_migration_note"
_MIGRATION = "0017_drop_migration_note"


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


async def _database_at_0016(postgres: PostgresContainer) -> str:
    dbname = f"m0017_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(_database_url(postgres, postgres.dbname))
    try:
        await admin.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await admin.close()
    database_url = _database_url(postgres, dbname)
    _tortoise(database_url, "migrate", "models", _PREVIOUS)
    return database_url


async def _seed(
    database_url: str, *, state: str = "migrated", note: str | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
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
            f"insert into {_TABLE} (id, provider, generation, migration_state, {_COLUMN},"
            " updated_at, account_id, effective_connection_id)"
            " values ($1, 'anthropic', 2, $2, $3, now(), $4, $5)",
            uuid.uuid4(),
            state,
            note,
            account_id,
            connection_id,
        )
    finally:
        await conn.close()
    return account_id, connection_id


async def _shape(database_url: str) -> dict[str, Any]:
    """The marker table's columns, indexes and constraints, plus its rows."""
    conn = await asyncpg.connect(database_url)
    try:
        columns = {
            row["column_name"]: (
                row["data_type"],
                row["character_maximum_length"],
                row["is_nullable"],
                row["column_default"],
            )
            for row in await conn.fetch(
                "select column_name, data_type, character_maximum_length, is_nullable,"
                " column_default from information_schema.columns where table_name = $1",
                _TABLE,
            )
        }
        indexes = {
            (row["indexname"], row["indexdef"])
            for row in await conn.fetch(
                "select indexname, indexdef from pg_indexes where tablename = $1", _TABLE
            )
        }
        constraints = {
            (row["conname"], row["contype"], row["definition"])
            for row in await conn.fetch(
                "select conname, contype, pg_get_constraintdef(oid) as definition"
                " from pg_constraint where conrelid = $1::regclass",
                _TABLE,
            )
        }
        markers = [
            tuple(row)
            for row in await conn.fetch(
                "select account_id, provider, generation, migration_state, effective_connection_id"
                f" from {_TABLE}"
            )
        ]
    finally:
        await conn.close()
    return {"columns": columns, "indexes": indexes, "constraints": constraints, "markers": markers}


@pytest.mark.asyncio
async def test_0017_drops_the_column_and_keeps_the_pair_rule_on_postgres(
    postgres_server: PostgresContainer,
) -> None:
    database_url = await _database_at_0016(postgres_server)
    account_id, connection_id = await _seed(database_url)
    before = await _shape(database_url)
    assert any("(account_id, provider)" in d for _, d in before["indexes"] if "UNIQUE" in d)

    _tortoise(database_url, "migrate", "models", _MIGRATION)

    after = await _shape(database_url)
    assert after["columns"] == {k: v for k, v in before["columns"].items() if k != _COLUMN}
    assert after["indexes"] == before["indexes"]
    assert after["constraints"] == before["constraints"]
    assert after["markers"] == [(account_id, "anthropic", 2, "migrated", connection_id)]

    conn = await asyncpg.connect(database_url)
    try:
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                f"insert into {_TABLE} (id, provider, generation, migration_state, updated_at,"
                " account_id) values ($1, 'anthropic', 1, 'none', now(), $2)",
                uuid.uuid4(),
                account_id,
            )
        await conn.execute("delete from oauth_connections where id = $1", connection_id)
        assert await conn.fetchval(f"select effective_connection_id from {_TABLE}") is None
        await conn.execute("delete from accounts where id = $1", account_id)
        assert await conn.fetchval(f"select count(*) from {_TABLE}") == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "note", "counts"),
    [
        ("quarantined", None, "1 quarantined and 0 noted"),
        ("none", "left by the retired backfill", "0 quarantined and 1 noted"),
    ],
)
async def test_0017_refuses_a_quarantined_or_noted_row_and_changes_nothing_on_postgres(
    postgres_server: PostgresContainer, state: str, note: str | None, counts: str
) -> None:
    database_url = await _database_at_0016(postgres_server)
    await _seed(database_url, state=state, note=note)
    before = await _shape(database_url)

    with pytest.raises(subprocess.CalledProcessError) as refused:
        _tortoise(database_url, "migrate", "models", _MIGRATION)

    assert counts in refused.value.stderr
    assert await _shape(database_url) == before


@pytest.mark.asyncio
async def test_0017_downgrade_re_adds_a_nullable_note_on_postgres(
    postgres_server: PostgresContainer,
) -> None:
    database_url = await _database_at_0016(postgres_server)
    await _seed(database_url)
    before = await _shape(database_url)
    _tortoise(database_url, "migrate", "models", _MIGRATION)

    _tortoise(database_url, "downgrade", "models", _PREVIOUS)

    after = await _shape(database_url)
    assert after == before
    assert after["columns"][_COLUMN] == ("character varying", 255, "YES", None)


async def _apply_migration_0017(database_url: str) -> None:
    await close_db()
    await init_db(database_url)
    try:
        await _run_migration(
            config=build_tortoise_config(database_url),
            app_labels=["models"],
            target=f"models.{_MIGRATION}",
        )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_0017_gives_up_a_blocked_postgres_lock_queue(
    postgres_server: PostgresContainer,
) -> None:
    # WHY: every request reads the marker table. A DROP COLUMN queued behind a long reader would
    # queue every later reader behind itself; the bounded wait fails the upgrade instead.
    database_url = await _database_at_0016(postgres_server)
    blocker = await asyncpg.connect(database_url)
    try:
        await blocker.execute("BEGIN")
        await blocker.execute(f"SELECT * FROM {_TABLE}")
        with pytest.raises(Exception) as caught:
            await asyncio.wait_for(_apply_migration_0017(database_url), timeout=10.0)
    finally:
        await blocker.execute("ROLLBACK")
        await blocker.close()

    assert getattr(caught.value, "sqlstate", None) == "55P03"
    assert _COLUMN in (await _shape(database_url))["columns"]
