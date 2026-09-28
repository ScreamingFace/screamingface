"""A merge never blocks serving, and its degradation signal is an honest lower bound.

FEATURE: admin cache snapshot upload (OME-951). STORY: as an operator patching a cache gap on a
live deployment, traffic keeps being served while the load runs, and the job tells me what the
load cost me in known prices.

Round 2 made `metadata_degraded` EXACT by taking `SHARE ROW EXCLUSIVE` on the live table for the
whole merge. That lock conflicts with the `ROW EXCLUSIVE` every cache hit takes to bump
`hit_count`/`last_hit_at` — and `TortoiseRequestCacheStore.get` awaits that bump inline before it
returns the cached body — so every hit stalled for the merge's duration. PR #930 review round 3,
finding 2: that trades away the approved availability contract
(`docs/spec/2026-08-22-OME-951-admin-cache-snapshot-upload.md` §7, "The load never blocks
serving") to sharpen a telemetry field, which is the wrong way round.

INVARIANT under test: serving wins. The count is a LOWER BOUND, named as one, and the bound errs
only downward — it can under-report a racing fill, never claim a degradation that did not happen.

INVARIANT under test (finding 4): the count mirrors the stale-metadata TRIGGER's `WHEN` clause,
not just the "archive carries no block" case. A staged row whose metadata equals the live block
but whose response differs is cleared by the trigger, and must be counted — otherwise zero reads
as "this load degraded nothing" while rows were in fact degraded.
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
from aigateway.core.request_cache.snapshot import CANONICAL_COLUMNS, LEGACY_COLUMNS
from aigateway.db import close_db, init_db

pytestmark = pytest.mark.needs_postgres

_TABLE = "request_cache_entries"
_STAGING = "request_cache_entries_staging"
_APP_DIR = Path(__file__).resolve().parents[2]


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


def _base_row(key_hash: str, *, response: str = '{"v":1}', metadata: str | None = None) -> dict:
    return {
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
        "metadata_json": metadata,
    }


def _dump(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    header = f"COPY public.{_TABLE} ({', '.join(columns)}) FROM stdin;\n"
    body = "".join(
        "\t".join("\\N" if row.get(name) is None else str(row[name]) for name in columns) + "\n"
        for row in rows
    )
    return (header + body + "\\.\n").encode()


# ── finding 2: the load never blocks serving ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_hit_count_bump_is_served_while_a_merge_is_open(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """The contract, stated as the thing an operator actually cares about.

    A cache hit's `hit_count` bump is an ordinary `UPDATE` — `ROW EXCLUSIVE`. Under round 2's
    `SHARE ROW EXCLUSIVE` it queued behind the whole merge; it must now complete while the merge
    transaction is still open. Asserted on a row the archive never mentions, so the only thing
    that could ever block it is a TABLE-level lock.
    """
    target, unrelated = "1" * 64, "2" * 64
    dump = tmp_path / "merge.sql"
    dump.write_bytes(_dump(LEGACY_COLUMNS, [_base_row(target)]))

    async with _db(migrated_postgres):
        for key in (target, unrelated):
            await RequestCacheEntry.create(
                key_hash=key,
                prompt_hash="p" * 64,
                provider="openrouter",
                model="m",
                response_json='{"v":0}',
                response_size_bytes=7,
                expires_at=None,
                metadata_json='{"marker":"live"}',
            )

        other = await asyncpg.connect(migrated_postgres)  # type: ignore[arg-type]
        try:
            # Hold a transaction open across the merge so the merge cannot simply finish first.
            await other.execute("BEGIN")
            await other.execute(
                f"UPDATE {_TABLE} SET hit_count = hit_count + 1 WHERE key_hash = $1", unrelated
            )
            # The merge must not need a lock this open writer is holding.
            outcome = await asyncio.wait_for(
                load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False),
                timeout=15,
            )
            await other.execute("COMMIT")
        finally:
            await other.close()

        assert outcome.staged_rows == 1


@pytest.mark.asyncio
async def test_the_merge_no_longer_offers_a_lock_timeout_refusal(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """With no table lock there is no lock to time out on, so the refusal must be gone rather
    than left in the API's vocabulary as a code nothing can ever produce."""
    from aigateway.core.request_cache import bulk_loader
    from aigateway.core.request_cache.upload_job import REFUSAL_CODES

    assert "merge_lock_timeout" not in REFUSAL_CODES
    assert not hasattr(bulk_loader, "MergeLockTimedOut")


# ── finding 4: the count mirrors the trigger ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_staged_block_equal_to_the_live_one_beside_a_new_response_is_counted(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """The gap the count had: the trigger fires on `response_json` changing while
    `metadata_json` does NOT, and clears the block. The old predicate only looked for a staged
    NULL, so this row was degraded and reported as zero."""
    key = "3" * 64
    block = '{"marker":"same"}'
    dump = tmp_path / "same-block-new-response.sql"
    dump.write_bytes(_dump(CANONICAL_COLUMNS, [_base_row(key, response='{"v":2}', metadata=block)]))

    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":1}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json=block,
        )

        outcome = await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)

        # The trigger really did clear it — the count is not asserting a hypothetical.
        after = await raw.fetchval(f"SELECT metadata_json FROM {_TABLE} WHERE key_hash = $1", key)
        assert after is None, "the trigger did not clear the block; this test's premise is stale"
        assert outcome.metadata_degraded == 1


@pytest.mark.asyncio
async def test_an_identical_row_degrades_nothing_and_is_counted_as_nothing(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """Boundary on the other side: same block AND same response means the trigger's `WHEN` is
    not satisfied, the block survives, and the count must stay zero. Widening the predicate must
    not start counting rows nothing happened to."""
    key = "4" * 64
    block = '{"marker":"same"}'
    dump = tmp_path / "identical.sql"
    dump.write_bytes(_dump(CANONICAL_COLUMNS, [_base_row(key, response='{"v":1}', metadata=block)]))

    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":1}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json=block,
        )

        outcome = await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)

        after = await raw.fetchval(f"SELECT metadata_json FROM {_TABLE} WHERE key_hash = $1", key)
        assert after == block
        assert outcome.metadata_degraded == 0


@pytest.mark.asyncio
async def test_a_replacement_block_beside_a_new_response_is_not_a_degradation(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """A staged row that brings a DIFFERENT block replaces one known price with another. The
    trigger does not fire (metadata changed), nothing became unknown, and the count stays zero."""
    key = "5" * 64
    dump = tmp_path / "new-block.sql"
    dump.write_bytes(
        _dump(CANONICAL_COLUMNS, [_base_row(key, response='{"v":2}', metadata='{"marker":"new"}')])
    )

    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":1}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"marker":"old"}',
        )

        outcome = await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)

        after = await raw.fetchval(f"SELECT metadata_json FROM {_TABLE} WHERE key_hash = $1", key)
        assert after == '{"marker":"new"}'
        assert outcome.metadata_degraded == 0
