"""Postgres evidence for the cache-entry metadata COLUMN on the snapshot path.

Runs against the dialect the loader exists for, because the behaviour pinned here is a Postgres
behaviour: a 13-column COPY reaches the staging twin and the live row, a 12-column legacy archive
still loads with ``metadata_json`` NULL, and a merge takes the snapshot's metadata block.

Run with:
``AIGW_TEST_PG=1 uv run pytest -m needs_postgres`` (the module selects itself).
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
from tortoise.migrations.api.migrate import migrate as _run_migration

from aigateway.core.request_cache.bulk_loader import load_snapshot
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.snapshot import CANONICAL_COLUMNS, LEGACY_COLUMNS
from aigateway.db import build_tortoise_config, close_db, init_db

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


# --- Finding 4 — the count and the merge must see ONE state, under concurrent fills ------------


@pytest.mark.asyncio
async def test_a_racing_write_to_an_unrelated_row_no_longer_blocks_the_merge(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """REVISED in review round 3 (finding 2), and the reversal is the point.

    Round 2 asserted the opposite of this: it took `SHARE ROW EXCLUSIVE` for the merge so that the
    degraded count could be EXACT, and pinned the exclusion ("a concurrent writer cannot commit
    while the merge transaction is open") as the fix. The cost was not paid by writers, though —
    serving a cache HIT is a write, because `TortoiseRequestCacheStore.get` awaits a
    `hit_count`/`last_hit_at` bump before it returns the cached body. So every hit on the whole
    table stalled for the merge's duration, which contradicts the approved snapshot contract
    (`docs/spec/2026-08-22-OME-951-admin-cache-snapshot-upload.md` §7, "The load never blocks
    serving").

    The trade is reversed here: serving wins, and `metadata_degraded` becomes an explicit LOWER
    BOUND. The uncounted interleaving round 2 closed is real and is now accepted — it can only
    UNDER-report, never claim a degradation that did not happen — and it is documented on the
    field rather than engineered away at the cost of availability.

    What this asserts is the inverse of its predecessor: an open writer on an unrelated row does
    NOT hold the merge up, and the merge still lands its own row correctly.
    """
    target, unrelated = "e" * 64, "f" * 64
    dump = tmp_path / "legacy-target-only.sql"
    dump.write_bytes(_dump(LEGACY_COLUMNS, [_base_row(target)]))  # mentions "target" only

    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=target,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":0}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"marker":"live"}',
        )
        await RequestCacheEntry.create(
            key_hash=unrelated,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"v":0}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json=None,
        )

        other = await asyncpg.connect(migrated_postgres)  # type: ignore[arg-type]
        try:
            await other.execute("BEGIN")
            # Holds a table-level ROW EXCLUSIVE for the life of this transaction — the mode the
            # round-2 lock conflicted with, and the mode every served cache hit takes.
            await other.execute(
                f"UPDATE {_TABLE} SET hit_count = hit_count + 1 WHERE key_hash = $1", unrelated
            )

            outcome = await asyncio.wait_for(
                load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False),
                timeout=15.0,
            )
        finally:
            await other.execute("ROLLBACK")
            await other.close()

        # The merge ran to completion beside the open writer, and still degraded the row it was
        # always going to degrade: dropping the lock cost the EXACTNESS of the count, not its
        # correctness on the rows the archive actually mentions.
        assert outcome.metadata_degraded == 1
        after = await _fetch(raw, target)
        assert after["metadata_json"] is None


# --- Finding 2 — the migration must give up the lock queue instead of leading it ---------------


@pytest.fixture
def postgres_at_0010() -> Generator[str, None, None]:
    """A fresh Postgres migrated only to ``0010`` — one migration short of ``0011``, so ``0011``
    can still be applied (and observed failing under a held lock) against it.

    Deliberately its own container rather than reusing ``migrated_postgres``: that fixture is
    module-scoped and already carries ``0011``, so there would be nothing left to apply.
    """
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tortoise",
                "-c",
                "aigateway.db.TORTOISE_CONFIG",
                "migrate",
                "models",
                "0010_simplify_request_cache",
            ],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


@asynccontextmanager
async def _holding_access_share_on_request_cache_entries(
    database_url: str,
) -> AsyncIterator[None]:
    """Holds ACCESS SHARE on ``request_cache_entries`` for the life of the context.

    The same lock mode, and the same "held open by a long transaction" shape, as the snapshot
    exporter's COPY — which sets ``lock_timeout = 0`` and can hold it for the whole
    ``_COPY_TIMEOUT_S = 600.0`` (``snapshot_export.py:54,71-72``).
    """
    conn = await asyncpg.connect(database_url)  # type: ignore[arg-type]
    try:
        await conn.execute("BEGIN")
        await conn.execute(f"SELECT * FROM {_TABLE}")
        yield
    finally:
        await conn.execute("ROLLBACK")
        await conn.close()


async def _apply_migration_0011(database_url: str) -> None:
    """Runs the REAL migration 0011 in-process, through Tortoise's own `migrate()` API.

    Not hand-rolled SQL: this goes through the real `AddField.database_forward` and the
    ``RunPython(code=_bound_lock_wait, ...)`` entry exactly as a real deploy would, so a broken
    wiring — the `RunPython` dropped from `operations`, or a `_dialect_of` that misreads the
    dialect — fails THIS test even though the unit tests only check the constants in isolation.
    """
    await close_db()
    await init_db(database_url)
    try:
        await _run_migration(
            config=build_tortoise_config(database_url),
            app_labels=["models"],
            target="models.0011_cache_entry_metadata",
        )
    finally:
        await close_db()


async def _select_one_from_request_cache_entries(database_url: str) -> int | None:
    conn = await asyncpg.connect(database_url)  # type: ignore[arg-type]
    try:
        return await conn.fetchval(f"SELECT count(*) FROM {_TABLE}")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_the_migration_gives_up_the_lock_queue_instead_of_blocking_readers(
    postgres_at_0010: str,
) -> None:
    """With a conflicting lock held, migration 0011 must fail fast under its own bounded
    ``lock_timeout`` — not sit at the head of the lock queue for as long as whatever holds the
    conflicting lock does.
    """
    async with _holding_access_share_on_request_cache_entries(postgres_at_0010):
        with pytest.raises(Exception) as caught:
            # Bounded so a regression (an unbounded wait) fails the test instead of hanging it.
            await asyncio.wait_for(_apply_migration_0011(postgres_at_0010), timeout=10.0)

    assert getattr(caught.value, "sqlstate", None) == "55P03"
    # This does NOT show a concurrent reader was never made to wait: by the time this select
    # runs, the DDL has already given up the queue AND the ACCESS SHARE lock above has been
    # released. What it shows is that the failed, rolled-back attempt left the table in a
    # normal, queryable state — the connection was not wedged by the aborted DDL.
    assert await _select_one_from_request_cache_entries(postgres_at_0010) is not None


# --- Finding 1 — a stale metadata block must be impossible, whatever binary writes -------------


@pytest.mark.asyncio
async def test_replacing_a_response_alone_clears_its_metadata_block(
    migrated_postgres: str,
) -> None:
    """An old binary updates the body and not the block; the pairing must not survive that.

    This is what a rolling upgrade or a rollback produces: a new response beside the PREVIOUS
    response's cost, tokens and latency. Nothing downstream could detect it, because the block
    is perfectly well-formed — it just describes a different answer.
    """
    key = "4" * 64
    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"body": "old"}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"cost_for": "old"}',
        )

        await raw.execute(
            f"UPDATE {_TABLE} SET response_json = $1 WHERE key_hash = $2",
            '{"body": "new"}',
            key,
        )

        after = await _fetch(raw, key)
        assert after["metadata_json"] is None


@pytest.mark.asyncio
async def test_replacing_a_response_with_its_own_block_keeps_the_block(
    migrated_postgres: str,
) -> None:
    """The current writer sets both together and must not be punished for it."""
    key = "5" * 64
    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"body": "old"}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"cost_for": "old"}',
        )

        await raw.execute(
            f"UPDATE {_TABLE} SET response_json = $1, metadata_json = $2 WHERE key_hash = $3",
            '{"body": "new"}',
            '{"cost_for": "new"}',
            key,
        )

        after = await _fetch(raw, key)
        assert after["metadata_json"] == '{"cost_for": "new"}'


@pytest.mark.asyncio
async def test_a_hit_count_bump_never_touches_the_block(migrated_postgres: str) -> None:
    """The hot path. The trigger's WHEN clause must keep it free of the trigger entirely."""
    key = "6" * 64
    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"body": "b"}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"cost_for": "b"}',
        )

        await raw.execute(f"UPDATE {_TABLE} SET hit_count = hit_count + 1 WHERE key_hash = $1", key)

        after = await _fetch(raw, key)
        assert after["metadata_json"] == '{"cost_for": "b"}'


@pytest.mark.asyncio
async def test_the_merge_still_carries_a_real_block_through(
    migrated_postgres: str, tmp_path: Path
) -> None:
    """Regression guard: the loader sets both columns, so the trigger must not fire on it."""
    key = "7" * 64
    archive_row = _base_row(key, metadata='{"cost_for": "archived"}')
    dump = tmp_path / "archived-metadata.sql"
    dump.write_bytes(_dump(CANONICAL_COLUMNS, [archive_row]))

    async with _db(migrated_postgres) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"body": "old"}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"cost_for": "old"}',
        )

        await load_snapshot(dump, mode="merge", expected_rows=1, acknowledge_loss=False)

        after = await _fetch(raw, key)
        assert after["metadata_json"] == '{"cost_for": "archived"}'


async def _reverse_migration_0011(database_url: str) -> None:
    """Runs the REAL migration 0011 downgrade in-process, back to 0010.

    Mirrors `_apply_migration_0011` exactly but targets the prior migration, so Tortoise's own
    executor computes and runs the BACKWARD plan — the same code path a real rollback takes,
    not a hand-rolled `DROP TRIGGER`.
    """
    await close_db()
    await init_db(database_url)
    try:
        await _run_migration(
            config=build_tortoise_config(database_url),
            app_labels=["models"],
            target="models.0010_simplify_request_cache",
        )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_the_trigger_and_function_drop_together_on_reverse_and_recreate_idempotently(
    postgres_at_0010: str,
) -> None:
    """The Postgres reverse path had zero coverage: the SQLite downgrade tests no-op the
    `_LOCKING_DIALECTS` guard, so `_DROP_TRIGGER_SQL` was never executed by any test. A trigger
    left behind after a rollback that already dropped its column would break every subsequent
    write to the table — the worst outcome this task could produce.

    This also pins the fix for the brief's own SQL defect: a bare `CREATE TRIGGER` is not
    idempotent, so re-running the forward trigger SQL against an already-migrated table used to
    raise "trigger already exists". `CREATE OR REPLACE TRIGGER` must not.
    """
    key = "9" * 64
    await _apply_migration_0011(postgres_at_0010)

    # 1-2: the trigger actually works forward, proven before its removal is tested.
    async with _db(postgres_at_0010) as raw:
        await RequestCacheEntry.create(
            key_hash=key,
            prompt_hash="p" * 64,
            provider="openrouter",
            model="m",
            response_json='{"body": "old"}',
            response_size_bytes=7,
            expires_at=None,
            metadata_json='{"cost_for": "old"}',
        )
        await raw.execute(
            f"UPDATE {_TABLE} SET response_json = $1 WHERE key_hash = $2",
            '{"body": "new"}',
            key,
        )
        after = await _fetch(raw, key)
        assert after["metadata_json"] is None

    # Re-applying the forward trigger SQL against the still-migrated table must not raise
    # "trigger already exists" — the exact defect CREATE OR REPLACE TRIGGER fixes.
    module = import_module("aigateway.migrations.0011_cache_entry_metadata")
    conn = await asyncpg.connect(postgres_at_0010)  # type: ignore[arg-type]
    try:
        await conn.execute(module._CREATE_TRIGGER_SQL)  # noqa: SLF001
    finally:
        await conn.close()

    # 3: reverse the migration for real.
    await _reverse_migration_0011(postgres_at_0010)

    conn = await asyncpg.connect(postgres_at_0010)  # type: ignore[arg-type]
    try:
        # 4: the trigger is gone.
        trigger = await conn.fetchval(
            "SELECT 1 FROM pg_trigger WHERE tgname = $1",
            "request_cache_entries_metadata_follows_response",
        )
        assert trigger is None
        # 5: so is its function — a stranded function alone would not break writes, but the
        # brief requires both dropped, and only checking the trigger would miss this.
        function = await conn.fetchval(
            "SELECT 1 FROM pg_proc WHERE proname = $1",
            "request_cache_entries_clear_stale_metadata",
        )
        assert function is None
        # 6: nothing dangling was left behind — a plain UPDATE on the reverted table still works.
        await conn.execute(
            f"UPDATE {_TABLE} SET response_json = $1 WHERE key_hash = $2",
            '{"body": "post-downgrade"}',
            key,
        )
    finally:
        await conn.close()
