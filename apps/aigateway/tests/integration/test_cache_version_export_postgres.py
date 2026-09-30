"""PostgreSQL and MinIO evidence for the E14 archive export (OME-1307, GW-freeze; CV-22).

The exporter reads the frozen rows from PostgreSQL and writes the archive pair to an S3-compatible
bucket with signed requests. A unit test with a mock transport cannot show that a real server
accepts the SigV4 HEAD, or that it enforces the payload hash of the PUT.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres`` (Docker is needed: PostgreSQL and MinIO
both start as containers).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import pytest
from testcontainers.community.minio import MinioContainer  # type: ignore[import-untyped]
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from aigateway.core.cache_versions.archive import (
    ENTRIES_OBJECT,
    MANIFEST_OBJECT,
    archive_prefix,
)
from aigateway.core.cache_versions.archive_store import S3VersionArchiveStore
from aigateway.core.cache_versions.exporter import CacheVersionExporter
from aigateway.core.cache_versions.freeze import FreezeService
from aigateway.core.cache_versions.freeze_store import TortoiseFreezeStore
from aigateway.core.cache_versions.models import CacheVersion
from aigateway.core.cache_versions.ports import ReceiptClaims
from aigateway.core.cache_versions.stats import CaptureStats
from aigateway.core.object_store import S3ObjectStoreConfig
from aigateway.core.sigv4 import Credentials
from aigateway.db import close_db, init_db
from tests.unit.cache_versions.conftest import seed_stored_calls

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_ACCOUNT = "acct-export-pg"
_BUCKET = "cache-versions-test"
# WHY not the testcontainers default image: `minio/minio` was removed from Docker Hub, so the
# default tag (`RELEASE.2022-12-02...`) can no longer be pulled. The Chainguard build is MinIO.
# AIDEV-NOTE: an unpinned tag can move. If a later MinIO build refuses the legacy
# MINIO_ACCESS_KEY / MINIO_SECRET_KEY variables that `MinioContainer` sets, pin a digest here.
_MINIO_IMAGE = "cgr.dev/chainguard/minio:latest"
_MANIFEST_KEYS = {
    "schema",
    "version_id",
    "trace_id",
    "created_at",
    "entry_count",
    "call_count",
    "missing_count",
    "coverage_status",
    "entries_sha256",
    "parameter_contract_revision",
    "key_revision",
}


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


@pytest.fixture(scope="module")
def minio() -> Generator[MinioContainer, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with MinioContainer(image=_MINIO_IMAGE) as container:
        container.get_client().make_bucket(_BUCKET)
        yield container


class _Signer:
    kid = "k"

    def sign(self, claims: ReceiptClaims) -> str:
        return "receipt"


@dataclass(frozen=True)
class _Outcome:
    first_id: UUID
    first_sha: str
    first_status: str
    second_id: UUID
    second_status: str
    archived_first_pass: int
    archived_repeat_pass: int
    archived_second_pass: int


def test_export_writes_pair_and_sets_archived(
    migrated_postgres: str, minio: MinioContainer
) -> None:
    config = minio.get_config()
    s3 = minio.get_client()
    trace, second_trace = "22" * 16, "23" * 16
    planted = b"planted before the export"
    store = TortoiseFreezeStore()
    exporter = CacheVersionExporter(
        store=store,
        archive=S3VersionArchiveStore(
            S3ObjectStoreConfig(
                endpoint_url=f"http://{config['endpoint']}",
                bucket=_BUCKET,
                credentials=Credentials(
                    access_key=config["access_key"],
                    secret_key=config["secret_key"],
                    region="us-east-1",
                ),
            )
        ),
        stats=CaptureStats(),
        poll_interval_s=3600.0,
    )

    async def _run() -> _Outcome:
        await close_db()
        await init_db(migrated_postgres)
        try:
            await CacheVersion.all().delete()
            service = FreezeService(
                store=store,
                signer=_Signer(),
                stats=CaptureStats(),
                max_entries=100,
                max_archive_bytes=10**9,
            )
            await seed_stored_calls(_ACCOUNT, trace, 3)
            first = await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=trace)
            first_pass = await exporter.run_once()
            first_status = (await CacheVersion.get(id=first.version_id)).status
            repeat_pass = await exporter.run_once()

            # An object that already exists in the bucket is never overwritten.
            await seed_stored_calls(_ACCOUNT, second_trace, 2)
            second = await service.freeze(account_id=_ACCOUNT, subject="ada", trace_id=second_trace)
            s3.put_object(
                _BUCKET,
                archive_prefix(second.version_id) + ENTRIES_OBJECT,
                io.BytesIO(planted),
                length=len(planted),
            )
            second_pass = await exporter.run_once()
            return _Outcome(
                first_id=first.version_id,
                first_sha=first.archive_sha256,
                first_status=first_status,
                second_id=second.version_id,
                second_status=(await CacheVersion.get(id=second.version_id)).status,
                archived_first_pass=first_pass,
                archived_repeat_pass=repeat_pass,
                archived_second_pass=second_pass,
            )
        finally:
            await close_db()

    outcome = asyncio.run(_run())

    prefix = archive_prefix(outcome.first_id)
    entries_bytes = s3.get_object(_BUCKET, prefix + ENTRIES_OBJECT).data
    manifest = json.loads(s3.get_object(_BUCKET, prefix + MANIFEST_OBJECT).data)
    assert outcome.first_status == "archived"
    assert hashlib.sha256(entries_bytes).hexdigest() == outcome.first_sha
    assert set(manifest) == _MANIFEST_KEYS
    assert manifest["entries_sha256"] == outcome.first_sha
    assert (manifest["entry_count"], manifest["trace_id"]) == (3, trace)
    assert (outcome.archived_first_pass, outcome.archived_repeat_pass) == (1, 0), (
        "a second pass writes nothing"
    )

    second_prefix = archive_prefix(outcome.second_id)
    assert outcome.second_status == "archived"
    assert outcome.archived_second_pass == 1
    assert s3.get_object(_BUCKET, second_prefix + ENTRIES_OBJECT).data == planted, (
        "a pre-written object is not overwritten"
    )
    second_manifest = json.loads(s3.get_object(_BUCKET, second_prefix + MANIFEST_OBJECT).data)
    assert second_manifest["trace_id"] == second_trace
