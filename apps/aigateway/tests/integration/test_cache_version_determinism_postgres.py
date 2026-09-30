"""PostgreSQL twin of the freeze-then-export determinism test (OME-1307, E14).

The unit twin (``tests/unit/cache_versions/test_freeze_export_determinism.py``) runs on SQLite. The
stored columns the exporter reads are TEXT on both, but Postgres is the dialect production runs, so
this checks that a shared blob with a changed live metadata, plus an inline call, still exports to
the digest the freeze recorded, with no parse of the stored columns in between.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres`` (Docker is needed for PostgreSQL).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.cache_versions.archive import ENTRIES_OBJECT, archive_prefix
from aigateway.core.cache_versions.exporter import CacheVersionExporter
from aigateway.core.cache_versions.freeze import FreezeService
from aigateway.core.cache_versions.freeze_store import TortoiseFreezeStore
from aigateway.core.cache_versions.models import CacheVersion
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.db import close_db, init_db
from tests.unit.cache_versions.test_freeze_export_determinism import (
    _ACCOUNT,
    _INLINE_ANSWER,
    _INLINE_REQUEST,
    _METADATA_ONE,
    _METADATA_TWO,
    _REQUEST,
    _SHARED_ANSWER,
    _TRACE_ONE,
    _TRACE_TWO,
    _Archive,
    _capture,
    _key_of,
    _lines,
    _oracle_line,
    _seed_prompt,
    _set_live,
    _Signer,
)

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]


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


def test_a_shared_blob_and_a_changed_live_metadata_export_to_the_frozen_digest(
    migrated_postgres: str,
) -> None:
    archive, stats = _Archive(), CaptureStats()
    store = TortoiseFreezeStore()
    service = FreezeService(
        store=store,
        signer=_Signer(),
        stats=CaptureStats(),
        max_entries=100,
        max_archive_bytes=10**9,
    )
    exporter = CacheVersionExporter(
        store=store, archive=archive, stats=stats, poll_interval_s=3600.0, jitter=lambda: 0.0
    )

    async def _run() -> tuple[tuple[UUID, str], tuple[UUID, str], int]:
        await close_db()
        await init_db(migrated_postgres)
        try:
            await CacheVersion.all().delete()
            shared_key = await _seed_prompt(_REQUEST)
            inline_key = await _seed_prompt(_INLINE_REQUEST)

            await _set_live(shared_key, metadata=_METADATA_ONE)
            await _capture(_TRACE_ONE, shared_key, "stored")
            one = await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=_TRACE_ONE)

            await _set_live(shared_key, metadata=_METADATA_TWO)
            await _capture(_TRACE_TWO, shared_key, "hit")
            await _capture(_TRACE_TWO, inline_key, "unstored", _INLINE_ANSWER)
            two = await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=_TRACE_TWO)

            archived = await exporter.run_once()
            return (
                (one.version_id, one.archive_sha256),
                (two.version_id, two.archive_sha256),
                archived,
            )
        finally:
            await close_db()

    (one_id, one_sha), (two_id, two_sha), archived = asyncio.run(_run())

    assert archived == 2
    assert stats.export_digest_mismatches == 0
    shared_key, inline_key = _key_of(_REQUEST)[1], _key_of(_INLINE_REQUEST)[1]
    one_bytes = archive.objects[archive_prefix(one_id) + ENTRIES_OBJECT]
    two_bytes = archive.objects[archive_prefix(two_id) + ENTRIES_OBJECT]
    assert hashlib.sha256(one_bytes).hexdigest() == one_sha
    assert hashlib.sha256(two_bytes).hexdigest() == two_sha
    shared = _oracle_line(shared_key, 0, _REQUEST, _SHARED_ANSWER, _METADATA_ONE)
    inline = _oracle_line(inline_key, 1, _INLINE_REQUEST, _INLINE_ANSWER, None)
    assert _lines(one_bytes) == [shared]
    assert _lines(two_bytes) == [shared, inline]
