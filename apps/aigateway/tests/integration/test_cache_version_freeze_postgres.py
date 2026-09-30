"""PostgreSQL evidence for the E14 freeze (OME-1307, GW-freeze).

SQLite serialises writers and checks a unique key row by row, so it hides the two properties that
need the dialect production runs.

1. **CV-8 (race twin):** two concurrent freezes of one trace make ONE version. The loser hits the
   unique key inside its transaction, which Postgres aborts, so the adapter must translate the error
   OUTSIDE the transaction and the service must return the winner.
2. **Freeze NFR:** a trace of 5,000 calls freezes in at most 10 s (`test-plan.md` section 5).

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import Generator, Sequence
from pathlib import Path
from urllib.parse import quote

import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.cache_versions.freeze import FreezeService
from aigateway.core.cache_versions.freeze_store import TortoiseFreezeStore
from aigateway.core.cache_versions.models import (
    CacheCaptureEntry,
    CacheVersion,
    CacheVersionBlob,
    CacheVersionEntry,
    RequestCachePrompt,
)
from aigateway.core.cache_versions.ports import NewBlob, NewEntry, ReceiptClaims, StoredVersion
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.db import close_db, init_db
from tests.unit.cache_versions.conftest import seed_stored_calls

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_ACCOUNT = "acct-freeze-pg"


def _database_url(postgres: PostgresContainer) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
        f"/{postgres.dbname}"
    )


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    """One container, migrated to head: the deployed schema, not ``generate_schemas``."""
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


class _Signer:
    kid = "k"

    def sign(self, claims: ReceiptClaims) -> str:
        return "receipt"


class _BothReachInsert(TortoiseFreezeStore):
    """Holds each freeze at the insert until both have arrived, so the race always happens."""

    def __init__(self) -> None:
        self._barrier = asyncio.Barrier(2)

    async def insert_version(
        self, version: StoredVersion, blobs: Sequence[NewBlob], entries: Sequence[NewEntry]
    ) -> None:
        await self._barrier.wait()
        await super().insert_version(version, blobs, entries)


async def _wipe() -> None:
    for model in (
        CacheVersionEntry,
        CacheVersion,
        CacheVersionBlob,
        CacheCaptureEntry,
        RequestCachePrompt,
        RequestCacheEntry,
    ):
        await model.all().delete()


def _service(store: TortoiseFreezeStore, *, max_entries: int = 20_000) -> FreezeService:
    return FreezeService(
        store=store,
        signer=_Signer(),
        stats=CaptureStats(),
        max_entries=max_entries,
        max_archive_bytes=1_500_000_000,
    )


def test_concurrent_freezes_make_one_version(migrated_postgres: str) -> None:
    trace = "c8" * 16

    async def _run() -> tuple[list[object], int, int, int]:
        await close_db()
        await init_db(migrated_postgres)
        try:
            await _wipe()
            await seed_stored_calls(_ACCOUNT, trace, 3)
            service = _service(_BothReachInsert())
            results = await asyncio.gather(
                *(
                    service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=trace)
                    for _ in range(2)
                ),
                return_exceptions=True,
            )
            return (
                list(results),
                await CacheVersion.all().count(),
                await CacheVersionEntry.all().count(),
                await CacheVersionBlob.all().count(),
            )
        finally:
            await close_db()

    results, versions, entries, blobs = asyncio.run(_run())

    assert not [r for r in results if isinstance(r, BaseException)], results
    ids = {getattr(r, "version_id") for r in results}
    assert len(ids) == 1, "both callers get the same version"
    assert sorted(getattr(r, "created") for r in results) == [False, True]
    assert (versions, entries, blobs) == (1, 3, 3)


def test_freeze_of_5000_entries_is_at_most_10_s(migrated_postgres: str) -> None:
    trace = "5000" * 8

    async def _run() -> tuple[float, int]:
        await close_db()
        await init_db(migrated_postgres)
        try:
            await _wipe()
            await seed_stored_calls(_ACCOUNT, trace, 5000, answer_bytes=4096)
            service = _service(TortoiseFreezeStore())
            started = time.perf_counter()
            result = await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=trace)
            return time.perf_counter() - started, result.entry_count
        finally:
            await close_db()

    elapsed, entry_count = asyncio.run(_run())

    print(f"freeze of 5000 entries took {elapsed:.2f} s")
    assert entry_count == 5000
    assert elapsed <= 10.0
