"""NFR: a replay hit costs at most 30 ms at p99 with a warm grant cache (OME-1307, GW-replay).

The budget comes from `prd/cache-version-store.md` section 4. A budget test has no honest RED: it
measures. The measured number goes into the work ledger.

FEATURE: OME-1307 (E14) - a replay hit is one grant check plus one indexed read of the version.
INVARIANT: the read uses the unique index `(version_id, key_hash, blob_id)` of migration 0013, so
its cost does not grow with the number of entries in other versions.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.cache_versions.grant import Ed25519ReplayGrantVerifier
from aigateway.core.cache_versions.lookup import TortoiseCacheVersionLookup
from aigateway.core.cache_versions.models import CacheVersion, CacheVersionBlob, CacheVersionEntry
from aigateway.db import close_db, init_db
from tests.unit.cache_versions.conftest import mint_grant

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_ENTRIES = 200
_BUDGET_SECONDS = 0.030


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = (
            f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
            f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
            f"/{postgres.dbname}"
        )
        subprocess.run(
            [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


def _key(index: int) -> str:
    return hashlib.sha256(f"call {index}".encode()).hexdigest()


async def _seed() -> UUID:
    version = await CacheVersion.create(
        owner_account_id="acct",
        trace_id="d4" * 16,
        entry_count=_ENTRIES,
        call_count=_ENTRIES,
        missing_count=0,
        coverage_status="complete",
        archive_sha256="0" * 64,
        archive_key="k",
    )
    blobs = [
        CacheVersionBlob(
            sha256=_key(index),
            request_json="{}",
            response_json='{"choices":[{"message":{"content":"' + "x" * 2_000 + '"}}]}',
            metadata_json=None,
            size_bytes=2_000,
        )
        for index in range(_ENTRIES)
    ]
    await CacheVersionBlob.bulk_create(blobs, batch_size=100)
    await CacheVersionEntry.bulk_create(
        [
            CacheVersionEntry(
                version_id=version.id,
                key_hash=_key(index),
                blob_id=_key(index),
                first_ordinal=index,
            )
            for index in range(_ENTRIES)
        ],
        batch_size=100,
    )
    return version.id


def test_replay_hit_p99_is_at_most_30_ms(migrated_postgres: str) -> None:
    signer = Ed25519PrivateKey.generate()

    async def _run() -> list[float]:
        await close_db()
        await init_db(migrated_postgres)
        try:
            version = await _seed()
            lookup = TortoiseCacheVersionLookup()
            verifier = Ed25519ReplayGrantVerifier(
                public_keys={"test-kid": signer.public_key()}, lookup=lookup
            )
            token = mint_grant(signer, sub="ana@example.org", vid=version)
            await verifier.verify(token, caller="ana@example.org")  # warm: grant, pool, statements
            await lookup.find(version, _key(0))
            samples: list[float] = []
            for index in range(_ENTRIES):
                started = time.perf_counter()
                await verifier.verify(token, caller="ana@example.org")
                hit = await lookup.find(version, _key(index))
                samples.append(time.perf_counter() - started)
                assert hit is not None, "the bench must measure hits"
            return samples
        finally:
            await close_db()

    samples = asyncio.run(_run())
    p99 = statistics.quantiles(samples, n=100, method="inclusive")[98]
    print(f"replay hit p99 (ms): {p99 * 1000:.3f}; max {max(samples) * 1000:.3f}")

    assert p99 <= _BUDGET_SECONDS
