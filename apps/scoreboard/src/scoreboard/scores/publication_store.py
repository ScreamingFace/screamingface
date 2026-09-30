"""`PublicationStore`: the Tortoise adapter of the publication state (erd 2.6).

FEATURE: OME-1307 (E14). INVARIANT: every change of `state` goes through `state.apply`, and this
class is the only writer. Each change locks the row (`select_for_update`) and re-reads the state
under the lock, so an owner request, an admin takedown and a worker finish cannot overwrite each
other. SQLite implements no row lock; the lock is proven by rendering the SQL (PB-8a).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.functions import Count
from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from scoreboard.core.publish.backoff import MAX_ATTEMPTS
from scoreboard.core.publish.eligibility import board_refusal
from scoreboard.core.publish.ports import ReleaseRef
from scoreboard.core.publish.release_body import ReleaseFacts
from scoreboard.core.publish.state import State, apply

from .cluster_types import load_result_chain
from .models import (
    CacheVersionPublication,
    ReportedResult,
    Score,
    System,
    SystemRevision,
)
from .schemas import _publish_authors, _publish_submitter

LEASE_S = 600  # PB-D2: lease_until = now + 10 min


@dataclass(frozen=True, slots=True)
class PublishJob:
    result_id: UUID
    state: str  # "requested" or "withdrawn" (cleanup)
    attempts: int
    release_tag: str
    cache_version_id: UUID
    cache_version_sha256: str


class PublicationStore:
    def __init__(self, public_base_url: str) -> None:
        self._public_base_url = public_base_url.rstrip("/")

    async def request_publish(
        self, result_id: UUID, *, requested_by: str, now: datetime
    ) -> tuple[State, bool]:
        """Apply `owner_publishes` under the row lock. Returns (new state, changed).

        On a change: state=requested, requested_by, requested_at=now, no next attempt, no last
        error, release_tag `cv-<cache_version_id>`, and attempts=0 when the transition resets them.
        Raises `TransitionRejected` for a withdrawn row (the route maps it to 409).
        """
        async with in_transaction() as conn:
            row = await self._locked(result_id, conn)
            transition = apply(cast(State, row.state), "owner_publishes")
            if transition.changed:
                version_id = await self._version_id(result_id, conn)
                row.state = transition.to
                row.requested_by = requested_by
                row.requested_at = now
                row.next_attempt_at = None
                row.last_error = None
                row.release_tag = f"cv-{version_id}"
                if transition.reset_attempts:
                    row.attempts = 0
                await row.save(using_db=conn)
            return cast(State, row.state), transition.changed

    def lease_query(
        self, now: datetime, *, connection: Any = None
    ) -> QuerySet[CacheVersionPublication]:
        """The due-job read, exposed so a test can render its SQL (PB-8a).

        Due = (requested, and no next attempt or it has come) OR (withdrawn with a cleanup
        pending, and its attempt has come); AND no live lease. Oldest request first.

        INVARIANT: a MODEL projection, and `select_for_update(skip_locked=True)` applied LAST.
        `values()` and `values_list()` build a fresh query without the lock state, so projecting
        would drop `FOR UPDATE` silently, and SQLite cannot show it. The PostgreSQL rendering test
        proves the clause is there.
        """
        publish_due = Q(state="requested") & (
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
        )
        cleanup_due = Q(state="withdrawn", next_attempt_at__isnull=False, next_attempt_at__lte=now)
        unleased = Q(lease_until__isnull=True) | Q(lease_until__lt=now)
        rows = CacheVersionPublication.filter((publish_due | cleanup_due) & unleased)
        if connection is not None:
            rows = rows.using_db(connection)
        return rows.order_by("requested_at", "result_id").select_for_update(skip_locked=True)

    async def lease_next(self, now: datetime) -> PublishJob | None:
        """Lease the oldest due row for `LEASE_S`, or None."""
        async with in_transaction() as conn:
            row = await self.lease_query(now, connection=conn).first()
            if row is None:
                return None
            row.lease_until = now + timedelta(seconds=LEASE_S)
            await row.save(using_db=conn, update_fields=["lease_until"])
            return await self._job(row, conn)

    async def finish_published(
        self, job: PublishJob, *, release: ReleaseRef, now: datetime
    ) -> bool:
        """Mark the row published, unless an admin withdrew it meanwhile (PB-D3).

        Locks the row and RE-READS the state. `requested` -> published, return True. `withdrawn`
        -> the release this worker just made must go: next_attempt_at=now (cleanup), lease cleared,
        return False.
        """
        async with in_transaction() as conn:
            row = await self._locked(job.result_id, conn)
            row.lease_until = None
            if row.state == "withdrawn":
                row.next_attempt_at = now
                await row.save(using_db=conn)
                return False
            row.state = apply(cast(State, row.state), "worker_succeeds").to
            row.release_url = release.html_url
            row.published_at = now
            row.last_error = None
            await row.save(using_db=conn)
            return True

    async def record_failed(self, job: PublishJob, *, error: str, now: datetime) -> None:
        """A failure that no retry can fix: `requested` -> failed.

        A row that an admin withdrew meanwhile only gets its cleanup scheduled.
        """
        async with in_transaction() as conn:
            row = await self._locked(job.result_id, conn)
            row.lease_until = None
            if row.state == "withdrawn":
                row.next_attempt_at = now
            else:
                row.state = apply(cast(State, row.state), "attempts_exhausted").to
                row.last_error = error
            await row.save(using_db=conn)

    async def withdraw(
        self,
        result_id: UUID,
        *,
        actor: str,
        reason: str,
        now: datetime,
        on_previous: Callable[[State], None] | None = None,
    ) -> State:
        """Apply `admin_takedown` under the row lock. Returns the new state.

        `on_previous` gets the state that the row held under the lock, before the takedown. The
        admin audit record (C10, MRA-2) needs it, and only this read cannot be stale.

        On a change: withdrawn_at/by/reason, attempts=0, and next_attempt_at=now when a release
        can exist (the previous state was requested, published or failed: cleanup pending, PB-D4),
        else None (PB-D6: a never published row makes no GitHub call). Withdrawn again is a no-op.

        INVARIANT: `lease_until` is NOT touched. A worker that holds the lease is mid-publish; it
        re-reads the state in `finish_published` (PB-D3) and does the cleanup itself. Clearing the
        lease would let a second worker lease the cleanup job while the first still uploads.
        """
        async with in_transaction() as conn:
            row = await self._locked(result_id, conn)
            previous = cast(State, row.state)
            if on_previous is not None:
                on_previous(previous)
            if apply(previous, "admin_takedown").changed:
                row.state = "withdrawn"
                row.withdrawn_at = now
                row.withdrawn_by = actor
                row.withdrawn_reason = reason
                row.attempts = 0
                row.next_attempt_at = now if previous != "private" else None
                await row.save(using_db=conn)
            return cast(State, row.state)

    async def record_retry(
        self, job: PublishJob, *, error: str, delay_s: float, now: datetime
    ) -> State:
        """A retryable failure: count it and back off. Returns the new state.

        Locks the row and RE-READS the state first. A publish job whose row is now withdrawn (an
        admin won a race) keeps `withdrawn` and gets its cleanup due at once. Otherwise
        attempts += 1. A publish job stops at `MAX_ATTEMPTS` (`failed`); a cleanup job has no cap.
        """
        async with in_transaction() as conn:
            row = await self._locked(job.result_id, conn)
            row.lease_until = None
            if job.state == "requested" and row.state == "withdrawn":
                row.next_attempt_at = now
            else:
                self._count_failure(row, job, error, now + timedelta(seconds=delay_s))
            await row.save(using_db=conn)
            return cast(State, row.state)

    def _count_failure(
        self, row: CacheVersionPublication, job: PublishJob, error: str, retry_at: datetime
    ) -> None:
        row.attempts += 1
        row.last_error = error
        if job.state != "requested":
            row.next_attempt_at = retry_at
            return
        exhausted = row.attempts >= MAX_ATTEMPTS
        event = "attempts_exhausted" if exhausted else "worker_fails_retryable"
        row.state = apply(cast(State, row.state), event).to
        if not exhausted:
            row.next_attempt_at = retry_at

    async def finish_cleanup(self, job: PublishJob) -> None:
        """The release and the tag are gone: nothing is pending. `release_url` stays as history."""
        async with in_transaction() as conn:
            row = await self._locked(job.result_id, conn)
            row.next_attempt_at = None
            row.attempts = 0
            row.lease_until = None
            await row.save(using_db=conn)

    async def gauges(self, now: datetime) -> tuple[dict[str, int], int]:
        """(count by state, withdrawn rows whose cleanup has been pending for more than 1 h).

        WHY `withdrawn_at` and not `next_attempt_at`: the backoff moves `next_attempt_at` forward,
        so it does not measure how long the cleanup has been pending (PB-D4).
        """
        by_state = await (
            CacheVersionPublication.annotate(n=Count("id")).group_by("state").values("state", "n")
        )
        pending = await CacheVersionPublication.filter(
            state="withdrawn",
            next_attempt_at__isnull=False,
            withdrawn_at__lte=now - timedelta(hours=1),
        ).count()
        return {str(entry["state"]): int(entry["n"]) for entry in by_state}, pending

    async def revalidate_publishable(self, result_id: UUID) -> str | None:
        """Re-read the board of the head and return the refusal code, or None when it may go public.

        The codes are those of `board_refusal`: `private_board` or `not_redistributable`.

        INVARIANT: read fresh at the time the job runs, never from the request. A request can wait
        for hours (backoff, lease) after the route checked the board, and the worker then copies
        the cache to a PUBLIC repository (PRD Q6, OME-894). A head or a benchmark that cannot be
        found is refused as a private board (fail closed).
        """
        chain = await load_result_chain(result_id)
        board = None if chain is None else chain[2]
        return board_refusal(
            public=board is not None and board.visibility == "public",
            redistributable=board is not None and board.redistributable,
        )

    async def release_facts(self, result_id: UUID, published_at: datetime) -> ReleaseFacts:
        """The facts of the release body, in the published (local-part) forms of the read API.

        WHY here and not in `core/publish/release_body.py`: that module must not import
        `scoreboard.scores.schemas` (its package runs `store.py` and Tortoise).
        """
        result = await ReportedResult.get(id=result_id)
        head = await Score.get(id=cast(UUID, getattr(result, "head_id")))
        name, revision = await self._system_of(head)
        return ReleaseFacts(
            system_name=name,
            system_revision=revision,
            benchmark_id=cast(str, getattr(head, "benchmark_id")),
            benchmark_revision=head.benchmark_revision,
            score=result.score,
            reporter=_publish_submitter(result.reporter),
            authors=_publish_authors(cast("list[str] | None", head.authors)),
            paper_url=head.paper_url,
            scoreboard_url=f"{self._public_base_url}/v1/scores/{head.id}",
            entry_count=cast(int, result.cache_entry_count),
            call_count=cast(int, result.cache_call_count),
            coverage_status=cast(str, result.cache_coverage_status),
            archive_sha256=cast(str, result.cache_version_sha256),
            published_at=published_at,
        )

    async def _system_of(self, head: Score) -> tuple[str | None, int | None]:
        if head.system_revision_id is None:
            return None, None
        revision = await SystemRevision.get(id=head.system_revision_id)
        system = await System.get(id=cast(UUID, getattr(revision, "system_id")))
        return system.name, revision.revision

    async def _job(self, row: CacheVersionPublication, conn: BaseDBAsyncClient) -> PublishJob:
        result = await ReportedResult.filter(id=getattr(row, "result_id")).using_db(conn).get()
        version_id = cast(UUID, result.cache_version_id)
        return PublishJob(
            result_id=cast(UUID, getattr(row, "result_id")),
            state=row.state,
            attempts=row.attempts,
            # WHY the fallback: the tag is a pure function of the version id (PB-D1).
            release_tag=row.release_tag or f"cv-{version_id}",
            cache_version_id=version_id,
            cache_version_sha256=cast(str, result.cache_version_sha256),
        )

    async def _locked(self, result_id: UUID, conn: BaseDBAsyncClient) -> CacheVersionPublication:
        return await (
            CacheVersionPublication.filter(result_id=result_id)
            .using_db(conn)
            .select_for_update()
            .get()
        )

    async def _version_id(self, result_id: UUID, conn: BaseDBAsyncClient) -> UUID:
        versions = await (
            ReportedResult.filter(id=result_id)
            .using_db(conn)
            .values_list("cache_version_id", flat=True)
        )
        return cast(UUID, versions[0])
