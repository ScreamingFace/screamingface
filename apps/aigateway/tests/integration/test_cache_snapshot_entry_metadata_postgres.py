"""Postgres evidence for the cache-entry metadata COLUMN on the snapshot path.

Runs against the dialect the loader exists for, because the behaviour pinned here is a Postgres
behaviour: a 13-column COPY reaches the staging twin and the live row, a 12-column legacy archive
still loads with ``metadata_json`` NULL, and a merge takes the snapshot's metadata block.

Run with:
``AIGW_TEST_PG=1 uv run pytest -m needs_postgres`` (the module selects itself).
"""

from __future__ import annotations

import logging
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
    """A clean live table and no staging twin, on the real connection the loader drives."""
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


def _base_row(
    key_hash: str,
    *,
    model: str = "openrouter/openai/gpt-5.5",
    metadata: str | None = None,
) -> dict[str, Any]:
    response = '{"v":1}'
    return {
        "id": str(uuid.uuid4()),
        "key_hash": key_hash,
        "prompt_hash": "p" * 64,
        "provider": "openrouter",
        "model": model,
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
    """A COPY block in the exact text format pg_dump writes, for the given column layout.

    Values here need no escapes: they carry no tab, newline or backslash. NULL travels as
    ``\\N``, which is what a nullable column the writer never filled carries.
    """
    header = f"COPY public.{_TABLE} ({', '.join(columns)}) FROM stdin;\n"
    body = "".join(
        "\t".join("\\N" if row.get(name) is None else str(row[name]) for name in columns) + "\n"
        for row in rows
    )
    return (header + body + "\\.\n").encode()


async def _fetch(raw: asyncpg.Connection, key_hash: str) -> dict[str, Any]:
    record = await raw.fetchrow(
        f"SELECT id, model, hit_count, response_json, metadata_json FROM {_TABLE}"
        " WHERE key_hash = $1",
        key_hash,
    )
    assert record is not None, f"key {key_hash[:8]}… did not load"
    return dict(record)


@pytest.mark.asyncio
async def test_a_merge_takes_the_snapshot_metadata_on_conflict(
    migrated_postgres: str, tmp_path: Path
) -> None:
    # S20: the merge must not silently drop the block the snapshot carried.
    key = "a" * 64
    snapshot_row = _base_row(key, metadata='{"marker":"snapshot"}')
    dump = tmp_path / "snapshot.sql"
    dump.write_bytes(_dump(CANONICAL_COLUMNS, [snapshot_row]))

    async with _db(migrated_postgres) as raw:
        # The row the snapshot holds, then diverges locally AFTER the snapshot was taken.
        await raw.execute(
            f"INSERT INTO {_TABLE} (id, key_hash, prompt_hash, provider, model, response_json,"
            " response_size_bytes, created_at, updated_at, expires_at, last_hit_at, hit_count,"
            " metadata_json) VALUES ($1,$2,$3,$4,$5,$6,$7,now(),now(),NULL,NULL,$8,$9)",
            uuid.UUID(snapshot_row["id"]),
            key,
            "p" * 64,
            "openrouter",
            "openrouter/diverged",
            snapshot_row["response_json"],
            snapshot_row["response_size_bytes"],
            5,
            '{"marker":"local-mutation"}',
        )

        outcome = await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)
        assert outcome.live_after == 1

        after = await _fetch(raw, key)
        assert after["metadata_json"] == '{"marker":"snapshot"}'
        assert after["model"] == snapshot_row["model"]
        # F11: identity and serving history are NOT part of the merge.
        assert after["hit_count"] == 5
        assert str(after["id"]) == snapshot_row["id"]


@pytest.mark.asyncio
async def test_a_legacy_twelve_column_archive_imports_with_null_metadata(
    migrated_postgres: str, tmp_path: Path
) -> None:
    # S12: an archive written before the metadata column existed still restores, and every row
    # it carries reads as unknown — never as a fabricated or zero-valued block.
    key = "b" * 64
    dump = tmp_path / "legacy.sql"
    dump.write_bytes(_dump(LEGACY_COLUMNS, [_base_row(key)]))

    async with _db(migrated_postgres) as raw:
        outcome = await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)
        assert outcome.live_after == 1

        after = await _fetch(raw, key)
        assert after["metadata_json"] is None
        assert after["response_json"] == '{"v":1}'


@pytest.mark.asyncio
async def test_a_legacy_archive_leaves_a_live_block_as_unknown_on_conflict(
    migrated_postgres: str, tmp_path: Path
) -> None:
    # ERD 5.2 item 3, taken literally: metadata_json is content, so EXCLUDED wins — and for a
    # legacy row EXCLUDED is NULL. A restore can therefore only degrade a block to "unknown"
    # (ERD E7), never leave a stale one beside a replaced response.
    key = "c" * 64
    dump = tmp_path / "legacy-conflict.sql"
    dump.write_bytes(_dump(LEGACY_COLUMNS, [_base_row(key)]))

    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="openrouter/old",
            response_json='{"v":0}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"marker":"live"}',
        )

        await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)

        after = await _fetch(raw, key)
        assert after["metadata_json"] is None
        assert after["response_json"] == '{"v":1}'


@pytest.mark.asyncio
async def test_a_stale_twelve_column_staging_twin_is_widened_before_the_copy(
    migrated_postgres: str, tmp_path: Path
) -> None:
    # An upgrade path, not a test fixture: a gateway that ran before the column existed left a
    # 12-column staging twin behind, and CREATE TABLE IF NOT EXISTS will not widen it. Without
    # the sync the next 13-column COPY fails on the missing column.
    key = "d" * 64
    row = _base_row(key, metadata='{"marker":"snapshot"}')
    dump = tmp_path / "snapshot.sql"
    dump.write_bytes(_dump(CANONICAL_COLUMNS, [row]))

    async with _db(migrated_postgres) as raw:
        await raw.execute(f"CREATE TABLE {_STAGING} (LIKE {_TABLE})")
        await raw.execute(f"ALTER TABLE {_STAGING} DROP COLUMN metadata_json")

        outcome = await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)
        assert outcome.live_after == 1

        after = await _fetch(raw, key)
        assert after["metadata_json"] == '{"marker":"snapshot"}'
        staged = await raw.fetchval(f"SELECT count(*) FROM {_STAGING}")
        assert staged == 0


# --- ERD E7 — a restore that degrades blocks must SAY how many ---------------------------------


@pytest.mark.asyncio
async def test_a_legacy_merge_reports_how_many_blocks_it_degraded(
    migrated_postgres: str, tmp_path: Path, caplog
) -> None:
    """INVARIANT: an erasure a restore is allowed to perform is still an erasure worth reporting.

    Merging a pre-0011 archive turns priced rows back into unknown ones — deliberate (ERD 5.2:
    metadata_json is content, so EXCLUDED wins) and irreversible for that row. Without a count at
    the moment it happens, the only trace is `cache.saved_cost.unpriced_hits` drifting upward on
    some later engine run, which points at the engine rather than at the restore that caused it.
    """
    priced, unpriced, untouched = "e" * 64, "f" * 64, "1" * 64
    dump = tmp_path / "legacy-degrades.sql"
    dump.write_bytes(
        _dump(LEGACY_COLUMNS, [_base_row(priced), _base_row(unpriced)]),
    )

    async with _db(migrated_postgres) as raw:
        # Two live rows the archive overwrites — one carries a block, one does not — and a third
        # the archive never mentions, so the count cannot simply be "rows that ended up NULL".
        await RequestCacheEntry.create(
            key_hash=priced,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":0}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"marker":"live"}',
        )
        await RequestCacheEntry.create(
            key_hash=unpriced,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":0}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json=None,
        )
        await RequestCacheEntry.create(
            key_hash=untouched,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":0}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"marker":"survivor"}',
        )

        with caplog.at_level(logging.WARNING, logger="aigateway.core.request_cache.bulk_loader"):
            outcome = await load_snapshot(
                dump, mode="merge", expected_rows=2, acknowledge_loss=False
            )

        # Only the row that HAD a block and lost it counts.
        assert outcome.metadata_degraded == 1
        assert (await _fetch(raw, priced))["metadata_json"] is None
        assert (await _fetch(raw, unpriced))["metadata_json"] is None
        assert (await _fetch(raw, untouched))["metadata_json"] == '{"marker":"survivor"}'

        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "1" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_a_merge_that_replaces_every_block_reports_no_degradation(
    migrated_postgres: str, tmp_path: Path, caplog
) -> None:
    """A current archive carries blocks, so nothing is degraded and nothing is warned about."""
    key = "2" * 64
    dump = tmp_path / "current.sql"
    dump.write_bytes(_dump(CANONICAL_COLUMNS, [_base_row(key, metadata='{"marker":"snapshot"}')]))

    async with _db(migrated_postgres) as raw:
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

        with caplog.at_level(logging.WARNING, logger="aigateway.core.request_cache.bulk_loader"):
            outcome = await load_snapshot(
                dump, mode="merge", expected_rows=1, acknowledge_loss=False
            )

        assert outcome.metadata_degraded == 0
        assert (await _fetch(raw, key))["metadata_json"] == '{"marker":"snapshot"}'
        assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


@pytest.mark.asyncio
async def test_a_replace_reports_no_degradation_because_loss_was_acknowledged(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """Boundary: replace discards the whole table by contract, so per-row degradation is not the
    fact being reported — the caller already acknowledged the loss."""
    key = "3" * 64
    dump = tmp_path / "replace.sql"
    dump.write_bytes(_dump(LEGACY_COLUMNS, [_base_row(key)]))

    async with _db(migrated_postgres) as raw:
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

        outcome = await load_snapshot(dump, mode="replace", expected_rows=1, acknowledge_loss=True)

        assert outcome.metadata_degraded == 0
        assert (await _fetch(raw, key))["metadata_json"] is None
