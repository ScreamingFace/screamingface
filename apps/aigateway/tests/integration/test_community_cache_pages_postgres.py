"""PostgreSQL evidence for the community-cache pages (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).

The hosted cache is Postgres, where ``updated_at`` is ``timestamptz`` and the page order rides on
migration 0015's composite index; SQLite stores the same column as text. So the properties the
unit suite pins on SQLite are pinned here on the deployed dialect too: migration 0015 creates the
index; a walk across many tied timestamps returns every eligible row exactly once; a page cursor
round-trips a Postgres timestamp exactly; ``count_rows`` agrees with the walk; and a hit on the
Postgres path leaves ``updated_at`` alone.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.request_cache.community_pages import (
    PageCursor,
    count_rows,
    cursor_after,
    iter_page,
)
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import record_hit_metadata
from aigateway.db import close_db, init_db

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_T0 = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)
_NOW = datetime(2026, 10, 15, tzinfo=UTC)


def _database_url(postgres: PostgresContainer) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
        f"/{postgres.dbname}"
    )


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    """One container, migrated to head — the deployed schema, not ``generate_schemas``."""
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        subprocess.run(
            [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


async def _seed(count: int, *, per_timestamp: int) -> list[str]:
    keys = [f"{i:064x}" for i in range(count)]
    for i, key in enumerate(keys):
        entry = await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="tavily" if i % 7 == 6 else "openrouter",
            model=f"m{i % 2}",
            response_json='{"choices": []}',
            response_size_bytes=15,
        )
        await RequestCacheEntry.filter(id=entry.id).update(
            updated_at=_T0 + timedelta(seconds=i // per_timestamp)
        )
    return [k for i, k in enumerate(keys) if i % 7 != 6]


@pytest.mark.asyncio
async def test_0015_creates_the_write_order_index(migrated_postgres: str) -> None:
    conn = await asyncpg.connect(migrated_postgres)
    try:
        definitions = await conn.fetch(
            "select indexdef from pg_indexes where tablename = 'request_cache_entries'"
        )
    finally:
        await conn.close()

    assert any("(updated_at, key_hash)" in row["indexdef"] for row in definitions)


@pytest.mark.asyncio
async def test_a_walk_over_ties_returns_every_eligible_row_once(migrated_postgres: str) -> None:
    await close_db()
    await init_db(migrated_postgres)
    try:
        await RequestCacheEntry.all().delete()
        eligible = await _seed(40, per_timestamp=9)

        walked: list[str] = []
        after: PageCursor | None = None
        while True:
            page = [
                row
                async for batch in iter_page(after=after, limit=6, models=(), now=_NOW)
                for row in batch
            ]
            walked.extend(row["key_hash"] for row in page)
            after = cursor_after(page, limit=6)
            if after is None:
                break

        assert walked == sorted(eligible, key=lambda k: (int(k, 16) // 9, k))
        assert await count_rows(after=None, models=(), now=_NOW) == len(eligible)
        assert await count_rows(after=None, models=("m0",), now=_NOW) == len(
            [k for k in eligible if int(k, 16) % 2 == 0]
        )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_a_cursor_round_trips_a_postgres_timestamp(migrated_postgres: str) -> None:
    await close_db()
    await init_db(migrated_postgres)
    try:
        await RequestCacheEntry.all().delete()
        await _seed(3, per_timestamp=1)
        [first] = [
            row
            async for batch in iter_page(after=None, limit=1, models=(), now=_NOW)
            for row in batch
        ]

        cursor = PageCursor.decode(cursor_after([first], limit=1).encode())  # type: ignore[union-attr]

        assert cursor.updated_at == _T0
        assert await count_rows(after=cursor, models=(), now=_NOW) == 2
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_a_hit_on_postgres_leaves_updated_at_alone(migrated_postgres: str) -> None:
    await close_db()
    await init_db(migrated_postgres)
    try:
        await RequestCacheEntry.all().delete()
        await _seed(1, per_timestamp=1)
        entry = await RequestCacheEntry.get(key_hash=f"{0:064x}")

        await record_hit_metadata(entry.id, _NOW)

        refreshed = await RequestCacheEntry.get(id=entry.id)
        assert (refreshed.hit_count, refreshed.updated_at) == (1, _T0)
    finally:
        await close_db()
