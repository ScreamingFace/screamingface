"""`TortoiseRunStore`: the `RunRegistry` on SQLite or Postgres (OME-1785, E5 P1 spec D2, §4.2).

FEATURE: first-class Runs. Laid out like an aigateway feature's `store.py`: the queries next to
the models they read. The driver's queries are in `runs/store_driver.py`, and what both share in
`runs/store_core.py`.

INVARIANT (spec §4.3): the store keeps facts only. A Run's state and `finished_at` are derived
from them on every read (`runs.state.derive_state`), so a read is always exact for its moment.

INVARIANT (spec §4.2): every write is compare-and-set on state. Each is one `UPDATE … WHERE`
guarded on the state it expects, and the row count says whether this writer won, identically on
both databases. So a terminal Candidate never moves (R4), and a bind cannot overwrite a stop.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.queryset import QuerySet
from tortoise.transactions import in_transaction

from screamingface_engine.artifacts.run_results import context_key, result_key, result_prefix
from screamingface_engine.candidate_outcomes import CandidateOutcome, stored_cost
from screamingface_engine.runs.db import CONNECTION
from screamingface_engine.runs.ids import new_run_id
from screamingface_engine.runs.models import Candidate, Run
from screamingface_engine.runs.records import (
    OwnerKey,
    RunPage,
    RunQuery,
    RunRecord,
    RunSpec,
)
from screamingface_engine.runs.registry import (
    CandidateAlreadyStarted,
    ClientKeyConflict,
    InvalidCursor,
    RunCanceled,
    RunNotFound,
    UnknownCandidate,
)
from screamingface_engine.runs.store_core import (
    LIVE,
    in_context,
    lock_run,
    read_runs,
    start_to_json,
    touch,
)
from screamingface_engine.runs.store_driver import DriverStore

# How many Runs one state-filtered `list` reads per query.
_SCAN_BATCH = 200
# How many Runs one retention pass lists, so its id list stays under every driver's
# bound-parameter limit.
_EXPIRY_BATCH = 500
# A Candidate whose start was sent: reconcile may settle it `lost` (spec R6, E5 P2 spec R8).
_SENT = ("scheduled", "running")


class TortoiseRunStore(DriverStore):
    """The one `RunRegistry` implementation."""

    # --- reads -------------------------------------------------------------------------------

    @in_context
    async def get(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        return await _one(Candidate.filter(run_id=run_id, run__owner=owner), full=True)

    @in_context
    async def summary(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        """`get` without each Candidate's start and record (E5 P2 spec §4.4)."""
        return await _one(Candidate.filter(run_id=run_id, run__owner=owner), full=False)

    # --- writes ------------------------------------------------------------------------------

    async def create(self, owner: OwnerKey, spec: RunSpec) -> RunRecord:
        record, _ = await self.register(owner, spec)
        return record

    @in_context
    async def register(self, owner: OwnerKey, spec: RunSpec) -> tuple[RunRecord, bool]:
        existing = await self._by_client_key(owner, spec)
        if existing is not None:
            return existing, False
        now = self._clock()
        run_id = spec.run_id or new_run_id()
        deadline = self._deadline(spec)
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
                    detached=spec.detach,
                    deadline_at=None if deadline is None else now + deadline,
                    owner_email=spec.owner_email,
                    context_sha256=None if spec.context is None else spec.context.sha256,
                    context_bytes=None if spec.context is None else spec.context.size_bytes,
                )
                starts = spec.starts or (None,) * len(spec.candidates)
                await Candidate.bulk_create(
                    [
                        Candidate(
                            run_id=run_id,
                            index=index,
                            name=name,
                            start=None if start is None else start_to_json(start),
                        )
                        for index, (name, start) in enumerate(
                            zip(spec.candidates, starts, strict=True)
                        )
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

    def _deadline(self, spec: RunSpec) -> timedelta | None:
        """How long after its creation the Run stops (E5 P2 spec D11, R10)."""
        if spec.detach:
            return spec.deadline or self._default_deadline
        # WHY: with the orphan rule off nothing else would ever stop an attached Run.
        if spec.starts and not self._orphan_grace:
            return self._default_deadline
        return None

    async def _by_client_key(self, owner: OwnerKey, spec: RunSpec) -> RunRecord | None:
        record = await _one(
            Candidate.filter(run__owner=owner, run__client_key=spec.client_key), full=True
        )
        if record is None:
            return None
        names = tuple(candidate.name for candidate in record.candidates)
        starts = tuple(c.start for c in record.candidates if c.start is not None)
        stored = None if record.deadline_at is None else record.deadline_at - record.created_at
        if (record.benchmark, record.case_count, names, starts, record.detached, stored) != (
            spec.benchmark,
            spec.case_count,
            spec.candidates,
            spec.starts,
            spec.detach,
            self._deadline(spec),
        ):
            raise ClientKeyConflict(f"client_key {spec.client_key!r} names another evaluation")
        return record

    @in_context
    async def bind(
        self,
        owner: OwnerKey,
        run_id: str,
        candidate: int,
        topic: str,
        *,
        trace_id: str | None = None,
    ) -> None:
        row = await self._unbound_candidate(owner, run_id, candidate, topic)
        if row is None:
            return
        now = self._clock()
        try:
            # WHY one transaction: a re-sent start finds the topic bound and returns early, so a
            # touch lost after the bind committed would never be retried.
            async with in_transaction(CONNECTION) as conn:
                await lock_run(run_id, conn)
                # E5 P2 spec R8: the clock starts when the start is sent, at `mark_scheduled`.
                won = await (
                    Candidate.filter(id=row.id, topic__isnull=True, state="pending")
                    .using_db(conn)
                    .update(topic=topic, trace_id=trace_id)
                )
                if won:
                    await touch(run_id, now, conn)
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
        # WHY the stop check first: a start sent after a stop must not schedule (spec R2, E5 P2
        # spec R9).
        if run.canceled:
            raise RunCanceled(run_id)
        if row.topic == topic:
            return None
        if row.topic is not None:
            raise CandidateAlreadyStarted(f"{run_id} Candidate {candidate}")
        return row

    @in_context
    async def mark_scheduled(self, topic: str) -> bool:
        row = await Candidate.get_or_none(topic=topic)
        if row is None:
            return True
        now = self._clock()
        async with in_transaction(CONNECTION) as conn:
            await lock_run(row.run_id, conn)
            if (
                await Candidate.filter(id=row.id, state="pending")
                .using_db(conn)
                .update(state="scheduled", bound_at=now)
            ):
                await touch(row.run_id, now, conn)
            # WHY a stop of a live Candidate: the stop owes it one, so the start that was just
            # sent must be stopped too (E5 P2 spec R9). A Candidate that already ended (a fast
            # run whose outcome beat this call) has nothing left to stop.
            live = await Candidate.filter(id=row.id, state__in=LIVE).using_db(conn).exists()
            stopped = await Run.filter(id=row.run_id, canceled=True).using_db(conn).exists()
            return not (live and stopped)

    @in_context
    async def settle(self, topic: str, outcome: CandidateOutcome) -> None:
        row = await Candidate.get_or_none(topic=topic)
        if row is None:
            # An unbound topic (a start without a Run, or one whose bind failed): no-op.
            return
        now = self._clock()
        cost = None if outcome.cost_usd is None else stored_cost(outcome.cost_usd)
        record = None if outcome.record is None else dict(outcome.record)
        # WHY one transaction: a redelivered outcome finds the Candidate terminal and writes
        # nothing, so a touch lost after the state commit would never be retried.
        async with in_transaction(CONNECTION) as conn:
            await lock_run(row.run_id, conn)
            won = await (
                Candidate.filter(id=row.id, state__in=LIVE)
                .using_db(conn)
                .update(
                    state=outcome.status,
                    # WHY the producer's time: an outcome written late (after a database outage)
                    # still ends the Candidate when the run ended.
                    finished_at=outcome.finished_at,
                    cost_usd=cost,
                    # The outcome refuses a code the column cannot hold (`CandidateOutcome`).
                    error_code=outcome.error_code,
                    record=record,
                )
            )
            if won:
                await touch(row.run_id, now, conn)
                return
            # INVARIANT (E5 P2 spec §4.4): state and error code are first-wins. A later outcome
            # with the same state fills a cost or a record still empty, and nothing else: an
            # outcome rebuilt from the stream (R7) has neither, and the runner's lands after it.
            same = Candidate.filter(id=row.id, state=outcome.status).using_db(conn)
            if cost is not None:
                await same.filter(cost_usd__isnull=True).update(cost_usd=cost)
            if record is not None:
                await same.filter(record__isnull=True).update(record=record)

    @in_context
    async def cancel(self, owner: OwnerKey, run_id: str) -> RunRecord | None:
        if not await Run.filter(id=run_id, owner=owner).exists():
            return None
        await self.stop(run_id, "canceled")
        return await self.get(owner, run_id)

    @in_context
    async def stored_objects(self, run_ids: Sequence[str]) -> dict[str, list[str]]:
        """The run-results keys each Run names: its context, and each Candidate's result by the
        checksum in its record (E5 P2 spec R13). A malformed checksum names nothing."""
        keys: dict[str, list[str]] = {run_id: [] for run_id in run_ids}
        with_context = await Run.filter(
            id__in=list(run_ids), context_sha256__isnull=False
        ).values_list("id", flat=True)
        for run_id in cast(list[str], with_context):
            keys[run_id].append(context_key(run_id))
        rows = await Candidate.filter(run_id__in=list(run_ids), record__isnull=False).values(
            "run_id", "index", "record"
        )
        for row in rows:
            result = row["record"].get("result") if isinstance(row["record"], dict) else None
            digest = result.get("sha256") if isinstance(result, dict) else None
            if not isinstance(digest, str):
                continue
            with contextlib.suppress(ValueError):
                keys[row["run_id"]].append(
                    result_key(result_prefix(row["run_id"], row["index"]), digest)
                )
        return keys

    @in_context
    async def records(
        self, owner: OwnerKey, run_id: str, indexes: Sequence[int]
    ) -> dict[int, dict[str, Any] | None] | None:
        if not await Run.filter(id=run_id, owner=owner).exists():
            return None
        rows = await Candidate.filter(run_id=run_id, index__in=list(indexes)).values(
            "index", "record"
        )
        return {row["index"]: row["record"] for row in rows}

    @in_context
    async def has_start(self, topic: str) -> bool:
        """Whether ``topic`` is a Candidate's whose Run the Engine drives (E5 P2 spec R14)."""
        return await Candidate.filter(topic=topic, start__isnull=False).exists()

    @in_context
    async def owed_stops(self, owner: OwnerKey, run_id: str) -> list[str]:
        rows = await Candidate.filter(run_id=run_id, run__owner=owner, stop_owed=True)
        return [row.topic for row in rows if row.topic is not None]

    @in_context
    async def stop_done(self, topic: str) -> None:
        await Candidate.filter(topic=topic, stop_owed=True).update(stop_owed=False)

    # --- sweeps ------------------------------------------------------------------------------

    @in_context
    async def reconcile(self) -> int:
        now = self._clock()
        stale = Q(bound_at__lt=now - self._lost_after)
        if not self._outcomes_survive_restart:
            # The outcomes of Candidates sent before this process started died with the old one.
            stale |= Q(bound_at__lt=self._started_at)
        # INVARIANT (spec R6): reconcile writes `lost` and nothing else. E5 P2 spec R8: a
        # `pending` Candidate was never sent, so no outcome is owed for it.
        return await Candidate.filter(stale, state__in=_SENT, bound_at__isnull=False).update(
            state="lost", finished_at=now
        )

    @in_context
    async def expiring(self, older_than: datetime) -> list[str]:
        """The ids of the Runs created before ``older_than``, oldest first, at most one batch
        (E5 P2 spec R13). The sweep deletes their results, then `expire`s them."""
        rows = (
            Run.filter(created_at__lt=older_than)
            .order_by("created_at", "id")
            .limit(_EXPIRY_BATCH)
            .values_list("id", flat=True)
        )
        return cast(list[str], await rows)

    @in_context
    async def expire(self, run_ids: Sequence[str]) -> int:
        if not run_ids:
            return 0
        expired = Run.filter(id__in=list(run_ids))
        async with in_transaction(CONNECTION) as conn:
            # INVARIANT (lock order): the Runs first, as every write does, so a sweep and a
            # `settle` on an expiring Run never wait on each other in a cycle.
            await expired.using_db(conn).select_for_update().only("id")
            await Candidate.filter(run_id__in=list(run_ids)).using_db(conn).delete()
            # WHY the Runs' own count: SQLite counts the rows a cascade deletes, so it is the one
            # count both databases agree on, and it is what this call deleted, not what a
            # concurrent sweep did.
            return await expired.using_db(conn).delete()

    # WHY last: a method named `list` shadows the builtin in annotations of the methods below it.
    @in_context
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
        # and its `IN` list can outgrow a driver's bound-parameter limit.
        batch_size = query.limit + 1 if query.state is None else _SCAN_BATCH
        while len(records) <= query.limit:
            batch = await rows.order_by("-created_at", "-id").limit(batch_size)
            derived = await _records([run.id for run in batch])
            records.extend(r for r in derived if query.state is None or r.state == query.state)
            if len(batch) < batch_size:
                break
            # WHY from `base`: the last row bounds the next batch alone; stacking each batch's
            # filter would grow the query with every batch.
            rows = _after(base, batch[-1])
        more = len(records) > query.limit
        page = tuple(records[: query.limit])
        return RunPage(page, page[-1].id if more else None)


async def _one(candidates: QuerySet[Candidate], *, full: bool) -> RunRecord | None:
    # WHY from the Candidates: every Run has at least one, and each row carries its Run.
    records = await read_runs(candidates, full=full)
    return records[0] if records else None


async def _records(run_ids: list[str]) -> list[RunRecord]:
    """The records of ``run_ids`` in that order, from one statement (spec R5). A Run that
    retention deleted after the page was read is left out."""
    by_id = {r.id: r for r in await read_runs(Candidate.filter(run_id__in=run_ids), full=False)}
    return [by_id[run_id] for run_id in run_ids if run_id in by_id]


def _after(rows: QuerySet[Run], anchor: Run) -> QuerySet[Run]:
    """The Runs after ``anchor`` in newest-first order, the id breaking ties (spec D5)."""
    return rows.filter(
        Q(created_at__lt=anchor.created_at) | Q(created_at=anchor.created_at, id__lt=anchor.id)
    )


__all__ = ["TortoiseRunStore"]
