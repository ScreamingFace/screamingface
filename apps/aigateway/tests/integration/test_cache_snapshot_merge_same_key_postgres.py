"""A merge never makes a hit wait on a key it is replacing, and its count blames only itself.

FEATURE: admin cache snapshot upload (OME-951), follow-up OME-1221. STORY: as an operator patching
a cache gap on a live deployment, a request for a key the archive also carries is answered at once,
and the job's `metadata_degraded` names only rows this load degraded.

The merge (`INSERT … ON CONFLICT DO UPDATE`) holds every colliding row's lock until COMMIT, and a
hit awaits its `hit_count` bump before returning the body. The sibling serving suite proves only
that an UNRELATED key is never blocked (no table lock); these tests cover the colliding key.

INVARIANT under test (owner decision, 2026-10-08): serving wins over hit telemetry. A bump that
would wait on a locked row is skipped, so the hit is served and simply not counted.
INVARIANT under test: the degradation count errs only downward. A row a concurrent writer degraded
is never counted against the load; a fill inserted mid-load may go uncounted.

AIDEV-NOTE: every interleaving here is driven by locks the test holds, never by sleeps: a test-only
trigger parks the merge on an advisory lock after it has locked the row, and a writer's open
transaction parks the load on that writer's row.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.request_cache.bulk_loader import load_snapshot
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.snapshot import LEGACY_COLUMNS
from aigateway.core.request_cache.store import TortoiseRequestCacheStore
from aigateway.db import close_db, init_db

pytestmark = pytest.mark.needs_postgres

_TABLE = "request_cache_entries"
_STAGING = "request_cache_entries_staging"
_APP_DIR = Path(__file__).resolve().parents[2]
_HOLD_KEY = 1221
_BLOCK = '{"marker":"live"}'


def _database_url(postgres: PostgresContainer) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
        f"/{postgres.dbname}"
    )


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
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


@asynccontextmanager
async def _db(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    await close_db()
    await init_db(database_url)
    raw = await asyncpg.connect(database_url)  # type: ignore[arg-type]
    try:
        await RequestCacheEntry.all().delete()
        await raw.execute(f"DROP TABLE IF EXISTS {_STAGING}")
        yield raw
    finally:
        await raw.close()
        await close_db()


def _legacy_dump(key_hash: str, response: str) -> bytes:
    """A 12-column archive row: no metadata block, so a merge onto a priced row degrades it."""
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "key_hash": key_hash,
        "prompt_hash": "p" * 64,
        "provider": "openrouter",
        "model": "openrouter/openai/gpt-5.5",
        "response_json": response,
        "response_size_bytes": len(response.encode()),
        "created_at": "2026-01-01 00:00:00+00",
        "updated_at": "2026-01-01 00:00:00+00",
        "expires_at": None,
        "last_hit_at": None,
        "hit_count": 0,
    }
    header = f"COPY public.{_TABLE} ({', '.join(LEGACY_COLUMNS)}) FROM stdin;\n"
    line = "\t".join("\\N" if row[name] is None else str(row[name]) for name in LEGACY_COLUMNS)
    return (header + line + "\n\\.\n").encode()


async def _live_row(key_hash: str, *, response: str = '{"v":0}') -> None:
    await RequestCacheEntry.create(
        key_hash=key_hash,
        prompt_hash="p" * 64,
        provider="openrouter",
        model="m",
        response_json=response,
        response_size_bytes=len(response.encode()),
        expires_at=None,
        metadata_json=_BLOCK,
    )


async def _until(raw: asyncpg.Connection, sql: str, *args: Any) -> None:
    """Poll a lock-state predicate (a fact the test holds the locks for — never a timing guess)."""
    for _ in range(500):
        if await raw.fetchval(sql, *args):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"lock state never reached: {sql}")


# The merge parks in the test trigger only AFTER rewriting the row, so a backend waiting on the
# advisory lock means the row lock is already held.
_MERGE_IS_PARKED = """
SELECT count(*) > 0 FROM pg_stat_activity
 WHERE datname = current_database() AND wait_event_type = 'Lock' AND wait_event = 'advisory'
"""
_SOMEONE_WAITS_ON_A_ROW = """
SELECT count(*) > 0 FROM pg_stat_activity
 WHERE datname = current_database() AND wait_event_type = 'Lock'
   AND wait_event IN ('transactionid', 'tuple')
"""


@asynccontextmanager
async def _merge_parked_after_locking(raw: asyncpg.Connection) -> AsyncIterator[None]:
    """Park the merge on an advisory lock right after it rewrote (and so row-locked) a row.

    The trigger is `AFTER UPDATE OF response_json`: the merge's SET names that column, a hit's
    bump never does, so only the merge is parked. Holding the advisory lock on `raw` keeps the
    merge transaction open, with its row lock, for as long as the test needs.
    """
    await raw.execute(
        f"""
        CREATE OR REPLACE FUNCTION ome1221_park() RETURNS trigger AS $$
        BEGIN PERFORM pg_advisory_xact_lock_shared({_HOLD_KEY}); RETURN NEW; END
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER ome1221_park AFTER UPDATE OF response_json ON {_TABLE}
            FOR EACH ROW EXECUTE FUNCTION ome1221_park();
        """
    )
    await raw.execute("SELECT pg_advisory_lock($1)", _HOLD_KEY)
    try:
        yield
    finally:
        await raw.execute("SELECT pg_advisory_unlock_all()")
        await raw.execute(f"DROP TRIGGER IF EXISTS ome1221_park ON {_TABLE}")
        await raw.execute("DROP FUNCTION IF EXISTS ome1221_park()")


# ── serving: a hit on a key the open merge holds ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_hit_on_a_key_the_open_merge_holds_is_served_at_once(
    migrated_postgres: str, tmp_path: Path
) -> None:
    key = "a" * 64
    dump = tmp_path / "colliding.sql"
    dump.write_bytes(_legacy_dump(key, '{"v":1}'))

    async with _db(migrated_postgres) as raw:
        await _live_row(key)
        async with _merge_parked_after_locking(raw):
            load = asyncio.create_task(
                load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)
            )
            try:
                # The merge has rewritten the row (so it holds the row lock) and is now parked.
                await _until(raw, _MERGE_IS_PARKED)

                served = await asyncio.wait_for(TortoiseRequestCacheStore().get(key), timeout=5)
            finally:
                await raw.execute("SELECT pg_advisory_unlock($1)", _HOLD_KEY)
                outcome = await asyncio.wait_for(load, timeout=15)

        # MVCC: the hit is served the body committed before the merge, not a half-loaded one.
        assert served is not None
        assert served.response == {"v": 0}
        assert outcome.staged_rows == 1
        # WHY 0: the bump met the merge's row lock and was skipped — the price of never waiting.
        assert await raw.fetchval(f"SELECT hit_count FROM {_TABLE} WHERE key_hash = $1", key) == 0


@pytest.mark.asyncio
async def test_an_uncontended_hit_still_counts(migrated_postgres: str) -> None:
    # Boundary: skipping a locked row must not turn into never counting at all.
    key = "b" * 64
    async with _db(migrated_postgres) as raw:
        await _live_row(key)
        store = TortoiseRequestCacheStore()
        assert await store.get(key) is not None
        assert await store.get(key) is not None

        row = await raw.fetchrow(
            f"SELECT hit_count, last_hit_at FROM {_TABLE} WHERE key_hash = $1", key
        )
        assert row is not None
        assert row["hit_count"] == 2
        assert row["last_hit_at"] is not None


# ── telemetry: the count blames only this load ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_block_a_concurrent_writer_cleared_is_not_blamed_on_the_load(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """The ticket's over-attribution, deterministically: a legacy-style writer replaces the live
    response (the stale-metadata trigger clears the block) and commits while the load waits on its
    row. The block is gone because of the WRITER; the load degraded nothing."""
    key = "c" * 64
    dump = tmp_path / "writer-race.sql"
    dump.write_bytes(_legacy_dump(key, '{"v":1}'))

    async with _db(migrated_postgres) as raw:
        await _live_row(key)
        writer = await asyncpg.connect(migrated_postgres)  # type: ignore[arg-type]
        try:
            await writer.execute("BEGIN")
            await writer.execute(
                f"UPDATE {_TABLE} SET response_json = '{{\"v\":9}}' WHERE key_hash = $1", key
            )
            load = asyncio.create_task(
                load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)
            )
            await _until(raw, _SOMEONE_WAITS_ON_A_ROW)
            await writer.execute("COMMIT")
            outcome = await asyncio.wait_for(load, timeout=15)
        finally:
            await writer.close()

        assert (
            await raw.fetchval(f"SELECT metadata_json FROM {_TABLE} WHERE key_hash = $1", key)
            is None
        ), "the writer's trigger did not clear the block; this test's premise is stale"
        assert outcome.metadata_degraded == 0


@pytest.mark.asyncio
async def test_a_fill_landing_mid_load_can_only_be_undercounted(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """The residual error, pinned in its safe direction. A fill inserts a priced row for a staged
    key and commits while the merge waits on it; the merge then degrades it. The count could not
    see a row that did not exist yet, so it reports 0 for a real degradation of 1 — an
    understatement, which is what "at least" promises. It must never be the other way round."""
    key = "d" * 64
    dump = tmp_path / "fill-race.sql"
    dump.write_bytes(_legacy_dump(key, '{"v":1}'))

    async with _db(migrated_postgres) as raw:
        filler = await asyncpg.connect(migrated_postgres)  # type: ignore[arg-type]
        try:
            await filler.execute("BEGIN")
            await filler.execute(
                f"""INSERT INTO {_TABLE} (id, key_hash, prompt_hash, provider, model,
                        response_json, response_size_bytes, created_at, updated_at, hit_count,
                        metadata_json)
                    VALUES ($1, $2, $3, 'openrouter', 'm', '{{"v":0}}', 7, now(), now(), 0, $4)""",
                uuid.uuid4(),
                key,
                "p" * 64,
                _BLOCK,
            )
            load = asyncio.create_task(
                load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)
            )
            await _until(raw, _SOMEONE_WAITS_ON_A_ROW)
            await filler.execute("COMMIT")
            outcome = await asyncio.wait_for(load, timeout=15)
        finally:
            await filler.close()

        degraded = await raw.fetchval(
            f"SELECT metadata_json IS NULL FROM {_TABLE} WHERE key_hash = $1", key
        )
        assert degraded is True
        # WHY 0 for a real 1: the downward direction "at least" allows — never above the truth.
        assert outcome.metadata_degraded == 0
