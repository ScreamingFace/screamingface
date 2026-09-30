"""Composition of the freeze service and the archive exporter (OME-1307, GW-freeze).

FEATURE: OME-1307 (E14) - keeps ``main.py`` short: one call builds the freezer and the exporter
from the settings, like ``snapshot_publish.build_snapshot_scheduler``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ...config import Settings
from ..object_store import S3ObjectStoreConfig
from ..sigv4 import Credentials
from .archive_store import FilesystemVersionArchiveStore, S3VersionArchiveStore
from .exporter import CacheVersionExporter
from .freeze import FreezeService
from .freeze_store import TortoiseFreezeStore
from .ports import CacheVersionFreezer, VersionArchiveStore
from .receipt import Ed25519ReceiptSigner
from .stats import CaptureStats

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheVersionServices:
    freezer: CacheVersionFreezer | None
    exporter: CacheVersionExporter | None


def _archive_store(settings: Settings) -> VersionArchiveStore | None:
    backend = settings.cache_version_archive_backend
    if backend == "s3":
        access_key = settings.cache_version_s3_access_key
        secret_key = settings.cache_version_s3_secret_key
        endpoint = settings.cache_version_s3_endpoint_url
        assert access_key is not None and secret_key is not None and endpoint  # Settings validated
        return S3VersionArchiveStore(
            S3ObjectStoreConfig(
                endpoint_url=endpoint,
                bucket=settings.cache_version_s3_bucket,
                credentials=Credentials(
                    access_key=access_key.get_secret_value(),
                    secret_key=secret_key.get_secret_value(),
                    region=settings.cache_version_s3_region,
                ),
                timeout_s=settings.cache_version_s3_timeout_s,
            )
        )
    if backend == "filesystem":
        assert settings.cache_version_archive_dir  # Settings validated
        return FilesystemVersionArchiveStore(Path(settings.cache_version_archive_dir))
    return None


def build_cache_version_services(settings: Settings, stats: CaptureStats) -> CacheVersionServices:
    """Build the freezer and the exporter. Either can be ``None``.

    INVARIANT: capture never depends on this. A missing signing key turns freeze off (the route
    answers 503) and leaves capture running.
    """
    if not settings.cache_versions_enabled:
        return CacheVersionServices(freezer=None, exporter=None)
    key = settings.receipt_signing_key
    if key is None or not key.get_secret_value().strip():
        logger.warning(
            "cache versions: capture on, freeze off (AIGATEWAY_RECEIPT_SIGNING_KEY is not set)"
        )
        return CacheVersionServices(freezer=None, exporter=None)
    signer = Ed25519ReceiptSigner.from_base64(key)
    logger.info("cache version receipts ready kid=%s", signer.kid)

    store = TortoiseFreezeStore()
    archive = _archive_store(settings)
    exporter = (
        CacheVersionExporter(
            store=store,
            archive=archive,
            stats=stats,
            poll_interval_s=settings.cache_version_export_poll_s,
        )
        if archive is not None
        else None
    )
    freezer = FreezeService(
        store=store,
        signer=signer,
        stats=stats,
        max_entries=settings.cache_version_max_entries,
        max_archive_bytes=settings.cache_version_max_archive_bytes,
        on_frozen=exporter.notify if exporter is not None else None,
    )
    return CacheVersionServices(freezer=freezer, exporter=exporter)
