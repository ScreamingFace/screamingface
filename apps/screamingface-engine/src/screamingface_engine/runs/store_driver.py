"""The Run store's queries for the Engine's driver (E5 P2 spec §4.4, R1, R4, R7, R9 to R11).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who starts an evaluation and walks
away, I trust the Engine to start every Candidate and to stop the Run when it should stop.

INVARIANT (P1 spec §4.2): every write is compare-and-set on what it expects, in one `UPDATE …
WHERE`, so the row count says whether this writer won, identically on both databases.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, cast

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from screamingface_engine.runs.db import CONNECTION
from screamingface_engine.runs.models import Candidate, Run
from screamingface_engine.runs.records import (
    P1_PENDING_GRACE,
    DueRun,
    OwnerKey,
    PendingStart,
    StartPlan,
    StopReason,
)
from screamingface_engine.runs.sealing import Unreadable
from screamingface_engine.runs.store_core import (
    LIVE,
    StoreCore,
    in_context,
    lock_run,
    start_from_json,
    touch,
)

logger = logging.getLogger(__name__)

# Startless Candidates read per batch; a pass reads batches until none is left.
_STARTLESS_BATCH = 500
# WHY a bound on the batches of one pass: the loop ends even if a row could never move.
_STARTLESS_BATCHES = 200
# Run ids per query of `due_runs`, well under every database's bound-parameter limit.
_ID_BATCH = 500

# The states of a Candidate whose start was sent: it holds one of the Run's slots (R1).
_IN_FLIGHT = ("scheduled", "running")


class DriverStore(StoreCore):
    """The driver's reads and writes. `runs.store.TortoiseRunStore` adds the rest."""

    # --- the lease (R4) ----------------------------------------------------------------------

    @in_context
    async def lease_run(self, run_id: str, held_until: datetime | None, until: datetime) -> bool:
        """Take or renew the Run's lease until ``until``. Wins when nobody holds it, it has
        expired, or it is still the ``held_until`` this driver last wrote."""
        free = Q(driver_lease_until__isnull=True) | Q(driver_lease_until__lte=self._clock())
        if held_until is not None:
            free |= Q(driver_lease_until=held_until)
        return bool(await Run.filter(Q(id=run_id), free).update(driver_lease_until=until))

    @in_context
    async def release_run(self, run_id: str, held_until: datetime) -> None:
        """Give the lease up, if this driver still holds it."""
        await Run.filter(id=run_id, driver_lease_until=held_until).update(driver_lease_until=None)

    # --- the driver's reads ------------------------------------------------------------------

    @in_context
    async def due_runs(self, now: datetime) -> list[DueRun]:
        live = set(
            await Candidate.filter(state__in=LIVE).distinct().values_list("run_id", flat=True)
        )
        with_starts = set(
            await Candidate.filter(state__in=LIVE, start__isnull=False)
            .distinct()
            .values_list("run_id", flat=True)
        )
        owed: dict[str, list[str]] = {}
        for run_id, topic in await Candidate.filter(
            stop_owed=True, topic__isnull=False
        ).values_list("run_id", "topic"):
            owed.setdefault(run_id, []).append(topic)
        ids = sorted(live | set(owed))
        rows: list[dict[str, Any]] = []
        # WHY batches: one `IN` list of every live Run would pass the database's bound-parameter
        # limit with enough Runs, and then every tick would fail.
        for at in range(0, len(ids), _ID_BATCH):
            rows += await Run.filter(id__in=ids[at : at + _ID_BATCH]).values(
                "id",
                "detached",
                "deadline_at",
                "stopped_by",
                "canceled",
                "driver_lease_until",
            )
        due = (
            self._due(row, now, row["id"] in live, row["id"] in with_starts, owed.get(row["id"]))
            for row in rows
        )
        return [run for run in due if run.drive or run.past_deadline or run.owed]

    def _due(
        self, row: dict[str, Any], now: datetime, live: bool, starts: bool, owed: list[str] | None
    ) -> DueRun:
        lease: datetime | None = row["driver_lease_until"]
        deadline: datetime | None = row["deadline_at"]
        unstopped = live and row["stopped_by"] is None
        # WHY due at once: an App from before P2 cancels by the flag alone while a deploy rolls
        # (R12). The driver starts nothing of it, so its stop is finished now, as `canceled`.
        flagged = unstopped and row["canceled"]
        return DueRun(
            run_id=row["id"],
            drive=live and starts and (lease is None or lease <= now),
            past_deadline=flagged or (unstopped and deadline is not None and deadline <= now),
            detached=row["detached"],
            owed=tuple(sorted(owed or ())),
            flagged=flagged,
        )

    @in_context
    async def pending_starts(self, run_id: str, *, inflight: int | None = None) -> StartPlan | None:
        """The Run's plan. With ``inflight``, only the starts of the Candidates that fit beside
        the owner's in flight are loaded: a start may be most of a MiB, and the driver asks
        every few seconds.

        WHY the owner's, across Runs: the runner caps a caller, so a Run behind the same
        owner's other Run has no room, whatever its own count.
        """
        run = await Run.get_or_none(id=run_id)
        if run is None:
            return None
        states = await Candidate.filter(run_id=run_id).values_list("state", flat=True)
        in_flight = sum(state in _IN_FLIGHT for state in states)
        waiting = Candidate.filter(run_id=run_id, state="pending", start__isnull=False)
        room = None
        if inflight is not None:
            # WHY only the driver's (review round 5): a Candidate of a Run a Client from before P2
            # registered may never have reached a runner, and is settled only by its outcome or
            # reconcile; counting it could hold the owner's new Runs back for days. A start it
            # does crowd out is refused at capacity and sent again (R2).
            elsewhere = (
                await Candidate.filter(
                    run__owner=run.owner, state__in=_IN_FLIGHT, start__isnull=False
                )
                .exclude(run_id=run_id)
                .count()
            )
            room = max(inflight - in_flight - elsewhere, 0)
        rows = (
            []
            if room == 0
            else await (
                waiting.order_by("index") if room is None else waiting.order_by("index").limit(room)
            ).values("index", "name", "topic", "trace_id", "start")
        )
        email, unreadable = self._opened(run)
        return StartPlan(
            run_id=run_id,
            owner=OwnerKey(run.owner),
            owner_email=email,
            owner_unreadable=unreadable,
            client_version=run.client_version,
            stopped=run.canceled,
            in_flight=in_flight,
            pending=tuple(
                PendingStart(
                    index=row["index"],
                    start=start_from_json(row["name"], row["start"]),
                    topic=row["topic"],
                    trace_id=row["trace_id"],
                )
                for row in rows
            ),
            waiting=await waiting.count(),
        )

    def _opened(self, run: Run) -> tuple[str | None, bool]:
        """The Run's email, opened (R16), and whether it could not be."""
        if run.sealed_owner_email is None:
            return None, False
        try:
            return self._seal.open(run.sealed_owner_email), False
        except Unreadable:
            # WHY the Run id alone: what failed to open is personal data.
            logger.warning("the owner email of %s cannot be opened with this key", run.id)
            return None, True

    @in_context
    async def overdue(self, run_id: str, before: datetime) -> list[str]:
        """The topics of the Run's in-flight Candidates whose start was sent before ``before``:
        the ones R7 reads the last frame of."""
        rows = await Candidate.filter(
            run_id=run_id, state__in=_IN_FLIGHT, topic__isnull=False, bound_at__lt=before
        ).values_list("topic", flat=True)
        return sorted(cast(list[str], rows))

    # --- writes ------------------------------------------------------------------------------

    @in_context
    async def hold(self, run_id: str) -> None:
        until = self._clock() + self._held_for
        # INVARIANT (R10): a deadline only moves forward, so a late or slow hold never pulls it
        # in; a detached or stopped Run's never moves (an older App's cancel sets only the flag,
        # R12); NULL (a Run without starts) stays NULL.
        await Run.filter(
            id=run_id,
            detached=False,
            stopped_by__isnull=True,
            canceled=False,
            deadline_at__lt=until,
        ).update(deadline_at=until)

    @in_context
    async def stop(
        self,
        run_id: str,
        reason: StopReason,
        *,
        past_deadline_at: datetime | None = None,
    ) -> bool:
        """Stop the Run (R9) and say whether this call did. ``past_deadline_at`` makes a deadline
        stop do nothing when a follower moved the deadline past that time (R11)."""
        now = self._clock()
        async with in_transaction(CONNECTION) as conn:
            await lock_run(run_id, conn)
            # INVARIANT (D12): the first stop's reason is kept. WHY owe the stops only in the
            # call that set it: a retry finds the stops that succeeded cleared, and must not owe
            # them again while their outcomes land.
            if not await _may_stop(run_id, past_deadline_at, conn):
                return False
            unstopped = Run.filter(id=run_id, stopped_by__isnull=True).using_db(conn)
            # WHY `canceled` for a flagged Run: an App from before P2 cancels by the flag alone
            # (R12), and that cancel came first (D12).
            if not (
                await unstopped.filter(canceled=True).update(stopped_by="canceled")
                or await unstopped.filter(canceled=False).update(stopped_by=reason, canceled=True)
            ):
                return False
            pending = Candidate.filter(run_id=run_id, state="pending").using_db(conn)
            await pending.filter(topic__isnull=True).update(state="stopped", finished_at=now)
            # WHY `scheduled`: a bound Candidate's start may have landed, so it is owed a stop
            # and its clock starts now, like any start that was sent.
            await pending.filter(topic__isnull=False).update(state="scheduled", bound_at=now)
            await (
                Candidate.filter(run_id=run_id, state__in=LIVE, topic__isnull=False)
                .using_db(conn)
                .update(stop_owed=True)
            )
            await touch(run_id, now, conn)
        return True

    @in_context
    async def settle_startless(self) -> int:
        """Settle the `pending` Candidates nothing in the Engine will start: those of a Run a
        Client from before P2 registered (R11), once it has been idle for P1's pending grace.
        Returns how many it moved.

        WHY the grace: while a deploy rolls, an older App registers a released Client's Run and
        binds its starts one at a time, each after up to 900 s in admission; settling them
        sooner would refuse those starts. An unbound one is `stopped`; a bound one's start may
        have landed, so it becomes `scheduled` and its outcome, or reconcile, settles it.
        WHY every batch until none is left (review round 4): a deploy can leave thousands, and
        their Runs read `running` until they settle.
        """
        now = self._clock()
        moved = 0
        for _ in range(_STARTLESS_BATCHES):
            rows = await (
                Candidate.filter(
                    state="pending",
                    start__isnull=True,
                    run__last_activity_at__lt=now - P1_PENDING_GRACE,
                )
                .limit(_STARTLESS_BATCH)
                .values_list("run_id", "id", "topic")
            )
            by_run: dict[str, list[tuple[int, str | None]]] = {}
            for run_id, row_id, topic in rows:
                by_run.setdefault(run_id, []).append((row_id, topic))
            for run_id, members in by_run.items():
                moved += await _settle_startless_of(run_id, members, now)
            if len(rows) < _STARTLESS_BATCH:
                break
        return moved


async def _settle_startless_of(
    run_id: str, members: list[tuple[int, str | None]], now: datetime
) -> int:
    """Settle one Run's startless Candidates under its lock. INVARIANT (store_core.lock_run):
    the Run row first, then its Candidates, as a stop takes them, so the two never deadlock."""
    unbound = [row_id for row_id, topic in members if topic is None]
    bound = [row_id for row_id, topic in members if topic is not None]
    async with in_transaction(CONNECTION) as conn:
        await lock_run(run_id, conn)
        # WHY guarded on `pending` again: a start may bind or settle one since the read.
        stopped = await (
            Candidate.filter(id__in=unbound, state="pending", topic__isnull=True)
            .using_db(conn)
            .update(state="stopped", finished_at=now)
        )
        # WHY the bind time an older App wrote is kept (review round 5): reconcile settles it
        # `lost` from when it was bound, as P1 did; a new clock would hold it live for another
        # 48 h. One with none starts its clock now, so reconcile still reaches it.
        bound_pending = Candidate.filter(id__in=bound, state="pending").using_db(conn)
        scheduled = await bound_pending.filter(bound_at__isnull=False).update(state="scheduled")
        scheduled += await bound_pending.filter(bound_at__isnull=True).update(
            state="scheduled", bound_at=now
        )
    return stopped + scheduled


async def _may_stop(
    run_id: str, past_deadline_at: datetime | None, conn: BaseDBAsyncClient
) -> bool:
    """Whether a stop applies: the Run exists, something in it is live, and, for a deadline
    stop, its deadline is still at or before ``past_deadline_at`` (R9, R11)."""
    run = await Run.filter(id=run_id).using_db(conn).first()
    if run is None or past_deadline_at is not None and _held(run, past_deadline_at):
        return False
    return await Candidate.filter(run_id=run_id, state__in=LIVE).using_db(conn).exists()


def _held(run: Run, past_deadline_at: datetime) -> bool:
    """Whether a deadline stop no longer applies: a follower moved the deadline past the tick's
    time (R11). WHY never for a flagged Run: an older App's cancel came first (R12)."""
    return not run.canceled and (run.deadline_at is None or run.deadline_at > past_deadline_at)


__all__ = ["DriverStore"]
