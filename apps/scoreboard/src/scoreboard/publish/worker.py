"""`PublishWorker`: one publish or cleanup job per `run_once` (C7, PB-D1..PB-D4).

FEATURE: OME-1307 (E14), STORY: as the owner of a result, I ask once and the release appears on
GitHub, even if the worker crashed half way.

INVARIANT (PB-3): no GitHub call happens before the archive digest matches the receipt.
INVARIANT (PB-D1): the release tag is a pure function of the cache version id, so a retry finds the
release by its tag and never makes a second one; an existing asset with other bytes stops the job.
INVARIANT (PB-D3): the state is re-read under the row lock before `published` is written, so a
release that an admin withdrew meanwhile is deleted and never marked published.
INVARIANT: `run_once` never raises. An unexpected error is logged and the lease ends by itself.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from scoreboard.core.publish.backoff import next_delay_s
from scoreboard.core.publish.ports import (
    ArchiveMissing,
    ArchivePair,
    PublisherError,
    ReleasePublisher,
    ReleasePublisherFactory,
    ReleaseRef,
    VersionArchiveReader,
)
from scoreboard.core.publish.release_body import ReleaseFacts, render_release_body
from scoreboard.metrics import Metrics
from scoreboard.scores.publication_store import PublicationStore, PublishJob

logger = logging.getLogger(__name__)

FactsLoader = Callable[[UUID, datetime], Awaitable[ReleaseFacts]]

_STATES = ("private", "requested", "published", "failed", "withdrawn")
_ERROR_MAX = 512


class _IntegrityFailure(Exception):
    """The job cannot be trusted: the archive is missing, another digest, or the release differs.

    `error` is the stable `last_error` code (PB-E5): archive_missing, archive_mismatch or
    release_conflict.
    """

    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.error = error


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PublishWorker:
    def __init__(
        self,
        *,
        store: PublicationStore,
        publisher_factory: ReleasePublisherFactory,
        archive_reader: VersionArchiveReader,
        facts_loader: FactsLoader,
        metrics: Metrics,
        clock: Callable[[], datetime],
        rng: Callable[[], float],
    ) -> None:
        self._store = store
        self._publisher_factory = publisher_factory
        self._archive_reader = archive_reader
        self._facts_loader = facts_loader
        self._metrics = metrics
        self._clock = clock
        self._rng = rng

    async def run_once(self) -> bool:
        """Lease and handle one due job. True when there was one."""
        now = self._clock()
        try:
            job = await self._store.lease_next(now)
            if job is not None:
                handler = self._cleanup if job.state == "withdrawn" else self._publish
                await handler(job, now)
            await self._refresh_gauges(now)
        except Exception:
            # WHY the broad catch: this is the worker boundary. The lease of the job ends by
            # itself (LEASE_S), so the job is tried again; the state has not changed.
            # WHY False: the loop then sleeps the poll interval, and a database outage does not
            # turn into a busy loop.
            logger.exception("publish worker job failed")
            return False
        return job is not None

    async def _publish(self, job: PublishJob, now: datetime) -> None:
        try:
            # INVARIANT (PB-3): the digest check comes first; the publisher is not even built
            # before it passes.
            pair = await self._verified_archive(job)
            publisher = await self._publisher_factory()
            release = await self._release_of(publisher, job, now)
            await self._upload_missing(publisher, release, pair)
            await self._finish(publisher, job, release, now)
        except _IntegrityFailure as failure:
            await self._store.record_failed(job, error=failure.error, now=now)
            self._metrics.publish_integrity_failures.inc()
        except PublisherError as err:
            await self._on_error(job, err, now)

    async def _verified_archive(self, job: PublishJob) -> ArchivePair:
        """The bucket pair whose `entries.jsonl.gz` has the digest of the receipt (D7 X-16)."""
        try:
            pair = await self._archive_reader.read(job.cache_version_id)
        except ArchiveMissing as exc:
            raise _IntegrityFailure("archive_missing") from exc
        if _sha256(pair.entries) != job.cache_version_sha256:
            raise _IntegrityFailure("archive_mismatch")
        return pair

    async def _release_of(
        self, publisher: ReleasePublisher, job: PublishJob, now: datetime
    ) -> ReleaseRef:
        existing = await publisher.get_release_by_tag(job.release_tag)
        if existing is not None:
            return existing
        facts = await self._facts_loader(job.result_id, now)
        return await publisher.create_release(
            job.release_tag,
            f"Cache version {job.cache_version_id}",
            render_release_body(facts),
        )

    async def _upload_missing(
        self, publisher: ReleasePublisher, release: ReleaseRef, pair: ArchivePair
    ) -> None:
        """Both assets, the manifest last so it marks a complete release (PB-D1)."""
        present = {asset.name: asset for asset in release.assets}
        for name, data, content_type in (
            ("entries.jsonl.gz", pair.entries, "application/gzip"),
            ("manifest.json", pair.manifest, "application/json"),
        ):
            if name not in present:
                await publisher.upload_asset(release, name, data, content_type)
            elif _sha256(await publisher.download_asset(present[name])) != _sha256(data):
                raise _IntegrityFailure("release_conflict")

    async def _finish(
        self, publisher: ReleasePublisher, job: PublishJob, release: ReleaseRef, now: datetime
    ) -> None:
        published = await self._store.finish_published(job, release=release, now=now)
        if not published:
            await self._delete_after_withdraw(publisher, job, release.id)
        self._metrics.publish_attempts.labels(result="ok").inc()

    async def _delete_after_withdraw(
        self, publisher: ReleasePublisher, job: PublishJob, release_id: int
    ) -> None:
        """An admin won the race (PB-D3): remove what this run made."""
        try:
            await publisher.delete_release(release_id)
            await publisher.delete_tag(job.release_tag)
        except PublisherError as err:
            # The row is already scheduled for cleanup; the next run finishes it.
            logger.warning("release cleanup after withdraw is pending: %s", err.message)
            return
        await self._store.finish_cleanup(job)

    async def _cleanup(self, job: PublishJob, now: datetime) -> None:
        """Takedown: delete the release and the tag, if any (PB-D4)."""
        try:
            publisher = await self._publisher_factory()
            release = await publisher.get_release_by_tag(job.release_tag)
            if release is not None:
                await publisher.delete_release(release.id)
            await publisher.delete_tag(job.release_tag)
        except PublisherError as err:
            await self._on_error(job, err, now)
            return
        await self._store.finish_cleanup(job)

    async def _on_error(self, job: PublishJob, err: PublisherError, now: datetime) -> None:
        error = err.message[:_ERROR_MAX]
        if err.retryable:
            delay = next_delay_s(
                job.attempts + 1, retry_after_s=err.retry_after_s, jitter=self._rng()
            )
            await self._store.record_retry(job, error=error, delay_s=delay, now=now)
            self._metrics.publish_attempts.labels(result="retry").inc()
        else:
            await self._store.record_failed(job, error=error, now=now)
            self._metrics.publish_attempts.labels(result="error").inc()

    async def _refresh_gauges(self, now: datetime) -> None:
        by_state, pending = await self._store.gauges(now)
        for state in _STATES:
            self._metrics.publish_jobs.labels(state=state).set(by_state.get(state, 0))
        self._metrics.withdraw_cleanup_pending.set(pending)
