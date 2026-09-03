"""Composition of the weekly cache-snapshot publish pipeline (OME-1021).

Extracted from ``main.py`` (review C7): the app composition root owns WHEN — the lifespan
starts and stops the scheduler — while this module owns WHAT runs: exporter + object store
+ the publish-then-clean protocol. Keeping them beside ``snapshot_scheduler.py`` (which
owns the timing/concurrency contract) keeps ``main.py`` inside the repo's ≤450-line review
boundary without splitting the feature's wiring across files that never mention it.

The publish protocol (``_run``), in order:
1. ``exporter.export()`` — stream the table into a fresh spool (archive + manifest).
2. PUT the archive, then PUT the manifest, under the unique ``cache-snapshots/<stamp>``
   keys — archive first so a manifest never names bytes that are absent.
3. Remove the spool in ``finally`` either way: the durable copies are in the store now,
   and a failed run must not leave spool files behind on the shared temp dir.
4. Log ``published`` — only reached when both PUTs returned 2xx (the store raises on
   anything else, redirects included), so the log line cannot lie.
"""

from __future__ import annotations

import hashlib
import logging
import shutil

from ..config import Settings
from .object_store import S3ObjectStore, S3ObjectStoreConfig
from .request_cache.snapshot_export import CacheSnapshotExporter, postgres_connect
from .sigv4 import Credentials
from .snapshot_scheduler import CacheSnapshotScheduler

logger = logging.getLogger(__name__)


def build_snapshot_scheduler(settings: Settings) -> CacheSnapshotScheduler:
    """Wire the weekly cache-snapshot export: exporter + store + publish-then-clean run.

    The exporter opens its OWN database connection per run (never the request-path pool),
    the store PUTs the archive and its manifest under the unique ``cache-snapshots/`` keys,
    and the spool directory is removed in ``finally`` either way. Only called from
    ``_lifespan`` when the feature is enabled — the storage keys, the Postgres DSN, and the
    cap invariant are guaranteed by ``Settings._validate_cache_snapshot`` (fail-fast at
    construction), and the endpoint shape by ``S3ObjectStoreConfig`` (fail-fast at wiring).
    """

    access_key = settings.cache_snapshot_s3_access_key
    secret_key = settings.cache_snapshot_s3_secret_key
    endpoint = settings.cache_snapshot_s3_endpoint_url
    assert access_key is not None and secret_key is not None and endpoint  # Settings validated
    exporter = CacheSnapshotExporter(
        lambda: postgres_connect(settings.database_url.get_secret_value()),
        max_bytes=settings.cache_snapshot_max_bytes,
    )
    store = S3ObjectStore(
        S3ObjectStoreConfig(
            endpoint_url=endpoint,
            bucket=settings.cache_snapshot_s3_bucket,
            credentials=Credentials(
                access_key=access_key.get_secret_value(),
                secret_key=secret_key.get_secret_value(),
                region=settings.cache_snapshot_s3_region,
            ),
            timeout_s=settings.cache_snapshot_timeout_s,
        )
    )

    async def _run() -> None:
        export = await exporter.export()
        prefix = f"cache-snapshots/{export.stamp}"
        try:
            await store.put(f"{prefix}.sql.gz", export.archive_path, sha256_hex=export.sha256_hex)
            manifest_sha = hashlib.sha256(export.manifest_path.read_bytes()).hexdigest()
            await store.put(
                f"{prefix}.manifest.json", export.manifest_path, sha256_hex=manifest_sha
            )
        finally:
            shutil.rmtree(export.archive_path.parent, ignore_errors=True)
        logger.info(
            "cache snapshot published rows=%d sha256=%s stamp=%s (archive + manifest)",
            export.row_count,
            export.sha256_hex[:12],
            export.stamp,
        )

    return CacheSnapshotScheduler(_run)


__all__ = ["build_snapshot_scheduler"]
