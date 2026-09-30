"""The archive exporter: an owned outbox task (OME-1307, GW-freeze).

FEATURE: OME-1307 (E14) - a version with status `frozen` is archived to the bucket, then marked
`archived`. The database rows stay the source of truth while the bucket is down (CV-E5).

INVARIANT: bytes whose sha256 differs from `archive_sha256` are never uploaded, and an object is
never overwritten (the archive port is write-once).
INVARIANT: the version status is the outbox. A failed pass leaves `frozen` rows, and the next pass
retries them, so nothing is queued in memory that a restart could lose. Only the backoff clock is in
memory (a restart retries at once; accepted).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from .archive import ENTRIES_OBJECT, MANIFEST_OBJECT, archive_prefix, manifest_bytes, write_entries
from .ports import ExportStore, StoredVersion, VersionArchiveStore
from .stats import CaptureStats

logger = logging.getLogger(__name__)


class CacheVersionExporter:
    def __init__(
        self,
        *,
        store: ExportStore,
        archive: VersionArchiveStore,
        stats: CaptureStats,
        poll_interval_s: float,
        batch_size: int = 10,
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = lambda: random.uniform(0.0, 1.0),
        spool_root: Path | None = None,
    ) -> None:
        self._store = store
        self._archive = archive
        self._stats = stats
        self._poll_interval_s = poll_interval_s
        self._batch_size = batch_size
        self._base_backoff_s = base_backoff_s
        self._max_backoff_s = max_backoff_s
        self._monotonic = monotonic
        self._jitter = jitter
        self._spool_root = spool_root
        self._attempts: dict[UUID, int] = {}
        self._next_attempt: dict[UUID, float] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> int:
        """One pass over the oldest frozen versions. Returns how many it archived."""
        self._stats.export_pending = await self._store.count_frozen()
        archived = 0
        now = self._monotonic()
        # WHY: versions still in backoff are excluded in the query. If they were only skipped after
        # the read, `batch_size` stuck versions would fill every batch and block all newer ones.
        backed_off = [vid for vid, at in self._next_attempt.items() if at > now]
        for version in await self._store.list_frozen(self._batch_size, backed_off):
            if await self._export(version):
                archived += 1
        return archived

    def notify(self) -> None:
        """Wake the loop now. ``FreezeService.on_frozen`` calls this."""
        self._wake.set()

    def start(self) -> None:
        """Begin the loop as one owned task. Idempotent: a live task is left alone."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(
            self._loop(), name="cache-version-exporter"
        )

    async def stop(self) -> None:
        """Cancel and await the owned task, so none outlives shutdown."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                # The loop must never die on one bad pass: the rows stay `frozen` and the next pass
                # retries them.
                logger.exception("cache version export pass failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval_s)
            except TimeoutError:
                pass
            self._wake.clear()

    async def _export(self, version: StoredVersion) -> bool:
        spool: Path | None = None
        try:
            spool = Path(tempfile.mkdtemp(prefix="aigw-cv-", dir=self._spool_root))
            entries = await self._store.load_archive_entries(version.id)
            entries_path = spool / ENTRIES_OBJECT

            def _write() -> str:
                with entries_path.open("wb") as handle:
                    # WHY no cap: the freeze already refused an archive over its cap, and this is a
                    # rebuild of the same entries. The digest check below catches any difference.
                    # The entries hold the stored canonical text as `CanonicalJson`, so this step
                    # splices that text and sorts, and parses nothing.
                    return write_entries(entries, handle, max_bytes=sys.maxsize).sha256

            digest = await asyncio.to_thread(_write)
            if digest != version.archive_sha256:
                self._stats.export_digest_mismatches += 1
                logger.error(
                    "cache version %s: rebuilt archive does not match archive_sha256; not uploaded",
                    version.id,
                )
                self._next_attempt[version.id] = self._monotonic() + self._max_backoff_s
                return False
            manifest = manifest_bytes(version)
            manifest_path = spool / MANIFEST_OBJECT
            manifest_path.write_bytes(manifest)
            prefix = archive_prefix(version.id)
            # Entries first, so a manifest never names an object that is absent.
            await self._archive.put_once(prefix + ENTRIES_OBJECT, entries_path, sha256_hex=digest)
            await self._archive.put_once(
                prefix + MANIFEST_OBJECT,
                manifest_path,
                sha256_hex=hashlib.sha256(manifest).hexdigest(),
            )
            await self._store.mark_archived(version.id)
        except Exception as exc:
            # WHY: any error from one version (bucket, disk, database, a bad stored row) is counted
            # and backed off for that version alone, so it can never abort the pass for the others.
            self._record_failure(version, exc)
            return False
        finally:
            if spool is not None:
                shutil.rmtree(spool, ignore_errors=True)
        self._attempts.pop(version.id, None)
        self._next_attempt.pop(version.id, None)
        return True

    def _record_failure(self, version: StoredVersion, exc: Exception) -> None:
        attempts = self._attempts.get(version.id, 0) + 1
        self._attempts[version.id] = attempts
        delay = min(self._max_backoff_s, self._base_backoff_s * 2 ** (attempts - 1))
        self._next_attempt[version.id] = self._monotonic() + delay + self._jitter()
        self._stats.export_failures += 1
        # The exception type only: a bucket error text is not needed to act on, and no credential
        # can reach a log this way.
        logger.warning(
            "cache version %s: archive export failed (%s); retry in %.1fs",
            version.id,
            type(exc).__name__,
            delay,
        )
