"""Postgres evidence for the cache-snapshot EXPORTER (OME-1021).

The exporter's guarantees are Postgres guarantees, pinned here against the real dialect:
the COPY-text round trip is byte-identical after re-feeding an exported archive through the
existing loader, the manifest's ``row_count``/``sha256``/``revisions`` survive the runner's
checksum and revision gates, and a single ``COPY (SELECT …)`` sees exactly one
point-in-time view even while rows commit concurrently — no torn rows, no later rows.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.request_cache.bulk_loader import load_snapshot
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.snapshot import (
    CopyBlockSource,
    digest_matches,
    open_snapshot_stream,
    parse_manifest,
)
from aigateway.core.request_cache.snapshot_export import (
    CacheSnapshotExporter,
    postgres_connect,
)
from aigateway.core.request_cache.store import RequestCacheWrite, TortoiseRequestCacheStore
from aigateway.core.request_cache.upload_job import CacheUploadRunner, UploadAcceptance
from aigateway.db import close_db, init_db

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]


def _database_url(postgres: PostgresContainer) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
        f"/{postgres.dbname}"
    )


def _migrate(database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
        cwd=_APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        _migrate(database_url)
        yield database_url


@asynccontextmanager
async def _db(database_url: str) -> AsyncIterator[TortoiseRequestCacheStore]:
    await close_db()
    await init_db(database_url)
    raw = await asyncpg.connect(database_url)  # type: ignore[arg-type]
    try:
        await RequestCacheEntry.all().delete()
        await raw.execute("DROP TABLE IF EXISTS request_cache_entries_staging")
        yield TortoiseRequestCacheStore()
    finally:
        await raw.close()
        await close_db()


def _write(
    key_hash: str, response: dict, *, model: str = "openrouter/openai/gpt-5.5"
) -> RequestCacheWrite:
    payload = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
    return RequestCacheWrite(
        key_hash=key_hash,
        prompt_hash="p" * 64,
        provider="openrouter",
        model=model,
        response=response,
        response_size_bytes=len(payload.encode()),
    )


HOSTILE_PAYLOAD = {
    "id": "cmpl-x",
    "choices": [
        {
            "message": {
                "content": (
                    'line1\nline2\twith tabs and \\ backslash and "quotes" and unicode: déjà 🚀'
                ),
            }
        }
    ],
    "usage": {"total_tokens": 42, "cost": 0.000717},
}


def _archive_row_count(archive: Path) -> int:
    """The loader's own view of how many rows an archive carries."""
    with open_snapshot_stream(archive) as stream:
        source = CopyBlockSource(stream)
        source.header()
        return sum(1 for _ in source.data_lines())


class _MidCopyInserter:
    """Forward the COPY to a real asyncpg connection, committing one insert mid-stream.

    The hook fires after the first row chunk is delivered — by then the COPY's snapshot
    has been taken, so the committed insert must be invisible to the archive.
    """

    def __init__(self, real: object, hook: Callable[[], Awaitable[None]]) -> None:
        self._real = real
        self._hook = hook
        self._first = True

    async def copy_from_query(  # type: ignore[override]
        self, query: str, *, output: object, timeout: object = None
    ) -> str:
        async def hooked(chunk: bytes) -> None:
            if self._first:
                self._first = False
                await self._hook()
            await output(chunk)  # type: ignore[operator]

        return await self._real.copy_from_query(query, output=hooked, timeout=timeout)  # type: ignore[attr-defined]

    async def close(self) -> None:
        await self._real.close()  # type: ignore[attr-defined]


async def _ready(conn: _MidCopyInserter) -> _MidCopyInserter:
    return conn


@pytest.mark.asyncio
async def test_an_exported_archive_round_trips_through_the_existing_loader(
    migrated_postgres, tmp_path: Path
) -> None:
    async with _db(migrated_postgres):
        store = TortoiseRequestCacheStore()
        for key, response in (
            ("a" * 64, {"v": 1}),
            ("b" * 64, HOSTILE_PAYLOAD),
            ("c" * 64, {"v": 3}),
        ):
            await store.set_if_absent(_write(key, response))

        exporter = CacheSnapshotExporter(
            lambda: postgres_connect(migrated_postgres), spool_dir=str(tmp_path)
        )
        export = await exporter.export()

        manifest = parse_manifest(export.manifest_path.read_bytes())
        assert manifest.row_count == 3
        assert manifest.row_count == _archive_row_count(export.archive_path)
        assert digest_matches(export.sha256_hex, manifest)

        # A cold deployment receives the archive: wipe the live table, then load through
        # the EXISTING loader with the manifest's own row_count as the gate.
        await RequestCacheEntry.all().delete()
        outcome = await load_snapshot(
            export.archive_path,
            mode="merge",
            expected_rows=manifest.row_count,
            acknowledge_loss=False,
        )
        assert outcome.staged_rows == 3
        assert outcome.live_after == 3

        # Byte identity: the hostile payload crossed export + COPY + load untouched.
        hostile = await RequestCacheEntry.get(key_hash="b" * 64)
        assert hostile is not None
        assert hostile.response_json == json.dumps(
            HOSTILE_PAYLOAD, separators=(",", ":"), ensure_ascii=False
        )
        decoded = json.loads(hostile.response_json)
        assert (
            decoded["choices"][0]["message"]["content"]
            == HOSTILE_PAYLOAD["choices"][0]["message"]["content"]
        )


@pytest.mark.asyncio
async def test_the_admin_runner_accepts_an_exported_archive(migrated_postgres, tmp_path) -> None:
    async with _db(migrated_postgres) as store:
        await store.set_if_absent(_write("a" * 64, {"v": 1}))

        # Importing the plugin registers its adapter revision exactly as production wiring
        # does — the runner's revision gate must see the deployed constants.
        import aigateway.plugins.openrouter_provider.global_cache  # noqa: F401
        from aigateway.core.request_cache.revisions import active_cache_revisions

        export = await CacheSnapshotExporter(
            lambda: postgres_connect(migrated_postgres), spool_dir=str(tmp_path)
        ).export()

        runner = CacheUploadRunner(revisions=active_cache_revisions)
        record = runner.start(
            UploadAcceptance(
                upload_path=export.archive_path,
                sha256_hex=export.sha256_hex,
                actual_bytes=export.archive_path.stat().st_size,
                manifest_raw=export.manifest_path.read_bytes(),
                mode="merge",
                force=False,
                acknowledge_loss=False,
                actor="admin@openmined.org",
            )
        )
        task = runner._task
        assert task is not None
        await asyncio.wait_for(asyncio.gather(task), timeout=60)

        assert record.state == "complete", record.error
        assert record.manifest_present is True
        assert record.warnings == []  # verified revisions, matching digest: nothing unverified
        assert record.staged_rows == 1


@pytest.mark.asyncio
async def test_export_sees_one_point_in_time_under_concurrent_writes(
    migrated_postgres, tmp_path: Path
) -> None:
    """A mid-COPY committed insert is invisible: no torn rows, no later rows."""
    async with _db(migrated_postgres):
        store = TortoiseRequestCacheStore()
        await store.set_if_absent(_write("a" * 64, {"v": 1}))
        await store.set_if_absent(_write("b" * 64, {"v": 2}))

        fired = False

        async def insert_mid_copy() -> None:
            nonlocal fired
            fired = True
            # Committed on a different connection than the COPY, mid-stream.
            await RequestCacheEntry.create(
                key_hash="c" * 64,
                prompt_hash="p" * 64,
                provider="openrouter",
                model="openrouter/openai/gpt-5.5",
                response_json='{"v":"inserted mid-copy"}',
                response_size_bytes=20,
                expires_at=None,
                last_hit_at=None,
                hit_count=0,
            )

        raw = await asyncpg.connect(migrated_postgres)  # type: ignore[arg-type]
        try:
            wrapped = _MidCopyInserter(raw, insert_mid_copy)
            exporter = CacheSnapshotExporter(lambda: _ready(wrapped), spool_dir=str(tmp_path))
            export = await exporter.export()
        finally:
            await raw.close()

        assert fired, "the mid-COPY insert never ran — the timing assumption is broken"

        # The COPY's snapshot was taken at statement start: the archive holds only the two
        # original rows, and the live table now holds three.
        assert export.row_count == 2
        assert await RequestCacheEntry.all().count() == 3

        # The archive is consistent: every row is a complete, loadable COPY line.
        assert _archive_row_count(export.archive_path) == 2
