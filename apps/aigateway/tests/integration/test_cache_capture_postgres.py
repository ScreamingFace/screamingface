"""PostgreSQL evidence for E14 capture (OME-1307, GW-capture).

SQLite serialises writers, which hides a concurrent first-write race entirely, and it treats
``INSERT OR IGNORE`` differently from ``ON CONFLICT DO NOTHING``. So two properties need the
dialect that production runs.

1. **CV-24:** ten concurrent first writes of one key leave ONE prompt row and ten capture rows, and
   none of them raises.
2. **Migration 0013:** it upgrades a populated database and downgrades it, on Postgres.

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
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.cache_versions.capture_store import TortoiseCaptureSink
from aigateway.core.cache_versions.models import CacheCaptureEntry, RequestCachePrompt
from aigateway.core.cache_versions.ports import CaptureRecord
from aigateway.db import close_db, init_db

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_PREVIOUS = "0012_provider_credential_slots"
_TABLES = {
    "request_cache_prompt",
    "cache_capture_entry",
    "cache_version",
    "cache_version_blob",
    "cache_version_entry",
}
_KEY_HASH = "c" * 64


def _database_url(postgres: PostgresContainer) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
        f"/{postgres.dbname}"
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


def _skip_unless_enabled() -> None:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    """One container, migrated to head: the deployed schema, not ``generate_schemas``."""
    _skip_unless_enabled()
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        _tortoise(database_url, "migrate")
        yield database_url


def _record(index: int) -> CaptureRecord:
    return CaptureRecord(
        account_id="acct",
        trace_id="f6" * 16,
        outcome="stored",
        key_hash=_KEY_HASH,
        request_material=f'{{"prompt":"first writer {index}"}}',
        response_json=None,
    )


async def _tables(database_url: str) -> set[str]:
    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            "select table_name from information_schema.tables where table_schema = 'public'"
        )
    finally:
        await conn.close()
    return {row["table_name"] for row in rows}


def test_prompt_stored_once_per_key_concurrent_first_writes_one_row(
    migrated_postgres: str,
) -> None:
    async def _run() -> tuple[int, int, int]:
        await close_db()
        await init_db(migrated_postgres)
        try:
            await CacheCaptureEntry.all().delete()
            await RequestCachePrompt.all().delete()
            sink = TortoiseCaptureSink()
            results = await asyncio.gather(
                *(sink.record(_record(i)) for i in range(10)), return_exceptions=True
            )
            failures = [r for r in results if isinstance(r, BaseException)]
            return (
                len(failures),
                await RequestCachePrompt.filter(key_hash=_KEY_HASH).count(),
                await CacheCaptureEntry.filter(key_hash=_KEY_HASH).count(),
            )
        finally:
            await close_db()

    failures, prompt_rows, capture_rows = asyncio.run(_run())

    assert failures == 0, "a lost first-write race must never raise"
    assert prompt_rows == 1
    assert capture_rows == 10


def test_0013_upgrades_and_downgrades_on_postgres() -> None:
    _skip_unless_enabled()
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        # Replay the deployed upgrade path: stop at the previous head, insert a real row,
        # then apply 0013 on the populated database.
        _tortoise(database_url, "migrate", "models", _PREVIOUS)

        async def _seed() -> None:
            conn = await asyncpg.connect(database_url)
            try:
                await conn.execute(
                    "insert into accounts (id, username, password_hash, created_at, is_active)"
                    " values ($1, 'u1', 'x', now(), true)",
                    uuid.uuid4(),
                )
            finally:
                await conn.close()

        asyncio.run(_seed())
        assert not (_TABLES & asyncio.run(_tables(database_url)))

        _tortoise(database_url, "migrate")
        assert _TABLES <= asyncio.run(_tables(database_url))

        _tortoise(database_url, "downgrade", "models", _PREVIOUS)
        remaining = asyncio.run(_tables(database_url))
        assert not (_TABLES & remaining)
        assert "accounts" in remaining, "the downgrade must not touch an existing table"

        _tortoise(database_url, "migrate")
        assert _TABLES <= asyncio.run(_tables(database_url))
