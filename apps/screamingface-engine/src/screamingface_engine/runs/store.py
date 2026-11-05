"""`TortoiseRunStore`: the `RunRegistry` on SQLite or Postgres (OME-1785, E5 P1 spec D2, §4.2).

FEATURE: first-class Runs. Laid out like an aigateway feature's `store.py`: the queries next to
the models they read.

INVARIANT (spec §4.3): the store keeps facts only. A Run's state and `finished_at` are derived
from them on every read (`runs.state.derive_state`), so a read is always exact for its moment.

INVARIANT (spec §4.2): every write is compare-and-set on state. Each is one `UPDATE … WHERE`
guarded on the state it expects, and the row count says whether this writer won, identically on
both databases. So a terminal Candidate never moves (R4), and a bind cannot overwrite a cancel.

INVARIANT: every write transaction locks its Run row first (`_lock_run`), then its Candidates.
One lock order means a bind, settle and cancel of one Run never deadlock on Postgres, and a
cancel's "is any Candidate live?" check holds until its flag commits (spec D12). SQLite takes one
write lock per transaction, so the order holds there by construction.

INVARIANT (spec R5): a record is derived from ONE statement, the Run's Candidates joined to their
Run, so a read never combines facts from two moments.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine, Iterable
from datetime import datetime, timedelta
from typing import Any, Concatenate, cast

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.context import TortoiseContext, get_current_context
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q, Subquery
from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from screamingface_engine.candidate_outcomes import CandidateOutcome, stored_cost
from screamingface_engine.runs.db import CONNECTION, using
from screamingface_engine.runs.ids import new_run_id
from screamingface_engine.runs.models import Candidate, Run
from screamingface_engine.runs.records import (
    CandidateRecord,
    CandidateState,
    OwnerKey,
    RunPage,
    RunQuery,
    RunRecord,
    RunSpec,
    is_terminal_run,
)
from screamingface_engine.runs.registry import (
    CandidateAlreadyStarted,
    ClientKeyConflict,
    InvalidCursor,
    RunCanceled,
    RunNotFound,
    UnknownCandidate,
)
from screamingface_engine.runs.state import derive_state

# The non-terminal Candidate states: the only ones a write may move a Candidate out of.
_LIVE = ("pending", "scheduled", "running")
# How many Runs one state-filtered `list` reads per query.
_SCAN_BATCH = 200


def _in_context[**P, R](
    method: Callable[Concatenate[TortoiseRunStore, P], Coroutine[Any, Any, R]],
) -> Callable[Concatenate[TortoiseRunStore, P], Coroutine[Any, Any, R]]:
    """Run a store method's queries in the store's own Tortoise context."""

    @functools.wraps(method)
    async def in_context(store: TortoiseRunStore, *args: P.args, **kwargs: P.kwargs) -> R:
        context = store._context
        if context is None or get_current_context() is context:
            return await method(store, *args, **kwargs)
        with using(context):
            return await method(store, *args, **kwargs)

    return in_context


class TortoiseRunStore:
    """The one `RunRegistry` implementation.

    ``outcomes_survive_restart`` is the outcome stream's `survives_restart`, and ``started_at``
    when this process started: together they decide what reconcile may settle (spec R6).
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        pending_grace: timedelta,
        lost_after: timedelta,
        outcomes_survive_restart: bool,
        started_at: datetime,
        context: TortoiseContext | None = None,
    ) -> None:
        self._clock = clock
        self._grace = pending_grace
        self._lost_after = lost_after
        self._outcomes_survive_restart = outcomes_survive_restart
        self._started_at = started_at
        # The Engine's own Tortoise context (`db.open_context`), or None to use the current one.
        self._context = context

    async def aclose(self) -> None:
        """Close the store's own database connections, when it owns a context."""
        if self._context is not None:
            await self._context.close_connections()

    # --- reads -------------------------------------------------------------------------------

    @_in_context
    async def get(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        return await self._one(Candidate.filter(run_id=run_id, run__owner=owner))

    async def _one(self, candidates: QuerySet[Candidate]) -> RunRecord | None:
        # WHY from the Candidates: every Run has at least one, and each row carries its Run.
        rows = await candidates.select_related("run")
        return self._record(rows[0].run, rows) if rows else None

    def _record(self, run: Run, candidates: Iterable[Candidate]) -> RunRecord:
        rows = sorted(candidates, key=lambda row: row.index)
        state = derive_state(
            [cast(CandidateState, row.state) for row in rows],
            canceled=run.canceled,
            last_activity_at=run.last_activity_at,
            now=self._clock(),
            grace=self._grace,
        )
        ends = [row.finished_at for row in rows if row.finished_at is not None]
        # A Run's end is its last Candidate's, once it is over and every Candidate has one.
        over = is_terminal_run(state) and len(ends) == len(rows)
        finished_at = max(ends) if over else None
        return RunRecord(
            id=run.id,
            state=state,
            created_at=run.created_at,
            finished_at=finished_at,
            benchmark=run.benchmark,
            case_count=run.case_count,
            candidates=tuple(_candidate(row) for row in rows),
            canceled=run.canceled,
        )

    # --- writes ------------------------------------------------------------------------------

    async def create(self, owner: OwnerKey, spec: RunSpec) -> RunRecord:
        record, _ = await self.register(owner, spec)
        return record

    @_in_context
    async def register(self, owner: OwnerKey, spec: RunSpec) -> tuple[RunRecord, bool]:
        existing = await self._by_client_key(owner, spec)
        if existing is not None:
            return existing, False
        now = self._clock()
        run_id = new_run_id()
        try:
            async with in_transaction(CONNECTION) as conn:
                await Run.create(
                    using_db=conn,
                    id=run_id,
                    owner=owner,
                    client_key=spec.client_key,
                    benchmark=spec.benchmark,
                    case_count=spec.case_count,
                    client_version=spec.client_version,
                    created_at=now,
                    last_activity_at=now,
                )
                await Candidate.bulk_create(
                    [
                        Candidate(run_id=run_id, index=index, name=name)
                        for index, name in enumerate(spec.candidates)
                    ],
                    using_db=conn,
                )
        except IntegrityError:
            # WHY: a concurrent retry of the same `POST /runs` inserted first. Its Run is ours.
            raced = await self._by_client_key(owner, spec)
            if raced is None:
                raise
            return raced, False
        created = await self.get(owner, run_id)
        assert created is not None
        return created, True

    async def _by_client_key(self, owner: OwnerKey, spec: RunSpec) -> RunRecord | None:
        record = await self._one(
            Candidate.filter(run__owner=owner, run__client_key=spec.client_key)
        )
        if record is None:
            return None
        names = tuple(candidate.name for candidate in record.candidates)
        if (record.benchmark, record.case_count, names) != (
            spec.benchmark,
            spec.case_count,
            spec.candidates,
        ):
            raise ClientKeyConflict(f"client_key {spec.client_key!r} names another evaluation")
        return record

    @_in_context
    async def bind(self, owner: OwnerKey, run_id: str, candidate: int, topic: str) -> None:
        row = await self._unbound_candidate(owner, run_id, candidate, topic)
        if row is None:
            return
        now = self._clock()
        try:
            # WHY one transaction: a re-sent start finds the topic bound and returns early, so a
            # touch lost after the bind committed would never be retried.
            async with in_transaction(CONNECTION) as conn:
                await _lock_run(run_id, conn)
                won = await (
                    Candidate.filter(id=row.id, topic__isnull=True, state="pending")
                    .using_db(conn)
                    .update(topic=topic, bound_at=now)
                )
                if won:
                    await self._touch(run_id, now, conn)
        except IntegrityError as exc:
            raise CandidateAlreadyStarted("the topic is bound to another Candidate") from exc
        if not won:
            # Another write moved the Candidate between the read and the bind: the same checks
            # now raise the error that says which.
            await self._unbound_candidate(owner, run_id, candidate, topic)

    async def _unbound_candidate(
        self, owner: OwnerKey, run_id: str, candidate: int, topic: str
    ) -> Candidate | None:
        """The Candidate a bind may claim, or `None` when it is already bound to ``topic``."""
        run = await Run.get_or_none(id=run_id, owner=owner)
        if run is None:
            raise RunNotFound(run_id)
        row = await Candidate.get_or_none(run_id=run_id, index=candidate)
        if row is None:
            raise UnknownCandidate(f"{run_id} has no Candidate {candidate}")
        # WHY the cancel check first: a start re-sent after a cancel must not schedule (R2).
        if run.canceled:
            raise RunCanceled(run_id)
        if row.topic == topic:
            return None
        if row.topic is not None:
            raise CandidateAlreadyStarted(f"{run_id} Candidate {candidate}")
        return row

    @_in_context
    async def mark_scheduled(self, topic: str) -> bool:
        row = await Candidate.get_or_none(topic=topic)
        if row is None:
            return True
        now = self._clock()
        async with in_transaction(CONNECTION) as conn:
            await _lock_run(row.run_id, conn)
            if (
                await Candidate.filter(id=row.id, state="pending")
                .using_db(conn)
                .update(state="scheduled")
            ):
                await self._touch(row.run_id, now, conn)
                return True
        # WHY this Candidate's own state: a re-sent start finds it already `scheduled`, and a
        # fast run may have settled it, even under a Run a sibling's cancel flagged. Only a
        # cancel that stopped THIS Candidate before it was scheduled loses the race.
        current = await Candidate.get(id=row.id)
        return (
            current.state != "stopped"
            or not await Run.filter(id=row.run_id, canceled=True).exists()
        )

    @_in_context
    async def settle(self, topic: str, outcome: CandidateOutcome) -> None:
        row = await Candidate.get_or_none(topic=topic)
        if row is None:
            # An unbound topic (a start without `X-SF-Run`, or one whose bind failed): no-op.
            return
        now = self._clock()
        # WHY one transaction: a redelivered outcome finds the Candidate terminal and writes
        # nothing, so a touch lost after the state commit would never be retried.
        async with in_transaction(CONNECTION) as conn:
            await _lock_run(row.run_id, conn)
            won = await (
                Candidate.filter(id=row.id, state__in=_LIVE)
                .using_db(conn)
                .update(
                    state=outcome.status,
                    # WHY the producer's time: an outcome written late (after a database outage)
                    # still ends the Candidate when the run ended.
                    finished_at=outcome.finished_at,
                    cost_usd=None if outcome.cost_usd is None else stored_cost(outcome.cost_usd),
                    # The outcome refuses a code the column cannot hold (`CandidateOutcome`).
                    error_code=outcome.error_code,
                )
            )
            if won:
                await self._touch(row.run_id, now, conn)

    @_in_context
    async def cancel(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        now = self._clock()
        async with in_transaction(CONNECTION) as conn:
            if not await Run.filter(id=run_id, owner=owner).using_db(conn).exists():
                return None
            await _lock_run(run_id, conn)
            if await Candidate.filter(run_id=run_id, state__in=_LIVE).using_db(conn).exists():
                await Run.filter(id=run_id).using_db(conn).update(canceled=True)
                # Spec D12: every bound live Candidate may be on a runner, so it is owed a stop.
                await (
                    Candidate.filter(run_id=run_id, state__in=_LIVE, topic__isnull=False)
                    .using_db(conn)
                    .update(stop_owed=True)
                )
                await (
                    Candidate.filter(run_id=run_id, state="pending")
                    .using_db(conn)
                    .update(state="stopped", finished_at=now)
                )
                await self._touch(run_id, now, conn)
        return await self.get(owner, run_id)

    @_in_context
    async def owed_stops(self, owner: OwnerKey, run_id: str) -> list[str]:
        rows = await Candidate.filter(run_id=run_id, run__owner=owner, stop_owed=True)
        return [row.topic for row in rows if row.topic is not None]

    @_in_context
    async def stop_done(self, topic: str) -> None:
        await Candidate.filter(topic=topic, stop_owed=True).update(stop_owed=False)

    async def _touch(
        self, run_id: str, now: datetime, conn: BaseDBAsyncClient | None = None
    ) -> None:
        # INVARIANT (spec §4.3): `last_activity_at` only moves forward, so a write stamped by a
        # slower clock never pulls the grace window back.
        await (
            Run.filter(id=run_id, last_activity_at__lt=now)
            .using_db(conn)
            .update(last_activity_at=now)
        )

    # --- sweeps ------------------------------------------------------------------------------

    @_in_context
    async def reconcile(self) -> int:
        now = self._clock()
        stale = Q(bound_at__lt=now - self._lost_after)
        if not self._outcomes_survive_restart:
            # The outcomes of Candidates bound before this process started died with the old one.
            stale |= Q(bound_at__lt=self._started_at)
        # INVARIANT (spec R6): reconcile writes `lost` and nothing else; an unbound Candidate is
        # left to the R5 grace.
        return await Candidate.filter(stale, state__in=_LIVE, bound_at__isnull=False).update(
            state="lost", finished_at=now
        )

    @_in_context
    async def expire(self, older_than: datetime) -> int:
        # WHY the Candidates first, by subquery: SQLite counts the rows a cascade deletes, so the
        # Runs' own delete is the only count both databases agree on, and it is what this call
        # deleted, not what a concurrent sweep did. No id list, so no driver's bound-parameter
        # limit applies.
        expired = Run.filter(created_at__lt=older_than)
        async with in_transaction(CONNECTION) as conn:
            # INVARIANT (lock order): the Runs first, as every write does, so a sweep and a
            # `settle` on an expiring Run never wait on each other in a cycle.
            await expired.using_db(conn).select_for_update().only("id")
            await (
                Candidate.filter(run_id__in=Subquery(expired.values("id"))).using_db(conn).delete()
            )
            return await expired.using_db(conn).delete()

    # WHY last: a method named `list` shadows the builtin in annotations of the methods below it.
    @_in_context
    async def list(self, owner: OwnerKey, query: RunQuery) -> RunPage:
        base = Run.filter(owner=owner)
        if query.since is not None:
            base = base.filter(created_at__gte=query.since)
        rows = base
        if query.cursor is not None:
            anchor = await Run.get_or_none(id=query.cursor, owner=owner)
            if anchor is None:
                # WHY refuse: an empty page would read as the end of the list.
                raise InvalidCursor(query.cursor)
            rows = _after(base, anchor)
        records: list[RunRecord] = []
        # Spec R5: state is derived, so a state filter is applied here. WHY scan in keyset
        # batches: loading the whole retention window at once grows without bound per owner,
        # and its prefetch `IN` list can outgrow a driver's bound-parameter limit.
        batch_size = query.limit + 1 if query.state is None else _SCAN_BATCH
        while len(records) <= query.limit:
            batch = await rows.order_by("-created_at", "-id").limit(batch_size)
            derived = await self._records([run.id for run in batch])
            records.extend(r for r in derived if query.state is None or r.state == query.state)
            if len(batch) < batch_size:
                break
            # WHY from `base`: the last row bounds the next batch alone; stacking each batch's
            # filter would grow the query with every batch.
            rows = _after(base, batch[-1])
        more = len(records) > query.limit
        page = tuple(records[: query.limit])
        return RunPage(page, page[-1].id if more else None)

    async def _records(self, run_ids: list[str]) -> list[RunRecord]:
        """The records of ``run_ids`` in that order, from one statement (spec R5). A Run that
        retention deleted after the page was read is left out."""
        by_run: dict[str, list[Candidate]] = {}
        for row in await Candidate.filter(run_id__in=run_ids).select_related("run"):
            by_run.setdefault(row.run_id, []).append(row)
        return [self._record(by_run[i][0].run, by_run[i]) for i in run_ids if i in by_run]


async def _lock_run(run_id: str, conn: BaseDBAsyncClient) -> None:
    """Lock the Run's row for this transaction (see the module's lock-order invariant)."""
    await Run.filter(id=run_id).using_db(conn).select_for_update().first()


def _after(rows: QuerySet[Run], anchor: Run) -> QuerySet[Run]:
    """The Runs after ``anchor`` in newest-first order, the id breaking ties (spec D5)."""
    return rows.filter(
        Q(created_at__lt=anchor.created_at) | Q(created_at=anchor.created_at, id__lt=anchor.id)
    )


def _candidate(row: Candidate) -> CandidateRecord:
    return CandidateRecord(
        index=row.index,
        name=row.name,
        state=cast(CandidateState, row.state),
        attempt_id=row.topic,
        started_at=row.bound_at,
        finished_at=row.finished_at,
        cost_usd=row.cost_usd,
        error_code=row.error_code,
    )


__all__ = ["TortoiseRunStore"]
