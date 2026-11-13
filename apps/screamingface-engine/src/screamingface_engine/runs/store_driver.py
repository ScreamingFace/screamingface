"""The Run store's queries for the Engine's driver (E5 P2 spec §4.4, R1, R4, R7, R9 to R11).

FEATURE: a detached Run (OME-1837). STORY: as a researcher who starts an evaluation and walks
away, I trust the Engine to start every Candidate and to stop the Run when it should stop.

INVARIANT (P1 spec §4.2): every write is compare-and-set on what it expects, in one `UPDATE …
WHERE`, so the row count says whether this writer won, identically on both databases.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from screamingface_engine.runs.db import CONNECTION
from screamingface_engine.runs.models import Candidate, Run
from screamingface_engine.runs.records import (
    DueRun,
    OwnerKey,
    PendingStart,
    StartPlan,
    StopReason,
)
from screamingface_engine.runs.store_core import (
    LIVE,
    StoreCore,
    in_context,
    lock_run,
    start_from_json,
    touch,
)

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
        rows = await Run.filter(id__in=list(live | set(owed))).values(
            "id",
            "created_at",
            "detached",
            "deadline_at",
            "stopped_by",
            "driver_lease_until",
            "last_followed_at",
        )
        due = (
            self._due(row, now, row["id"] in live, row["id"] in with_starts, owed.get(row["id"]))
            for row in rows
        )
        return [run for run in due if run.drive or run.past_deadline or run.unfollowed or run.owed]

    def _due(
        self, row: dict[str, Any], now: datetime, live: bool, starts: bool, owed: list[str] | None
    ) -> DueRun:
        lease: datetime | None = row["driver_lease_until"]
        deadline: datetime | None = row["deadline_at"]
        # WHY the creation time for a Run never followed: its Client follows right after
        # `POST /runs`, so the grace counts from then (R10).
        stamp: datetime = row["last_followed_at"] or row["created_at"]
        unstopped = live and row["stopped_by"] is None
        follow_rule = bool(self._orphan_grace) and starts and not row["detached"]
        return DueRun(
            run_id=row["id"],
            drive=live and starts and (lease is None or lease <= now),
            past_deadline=unstopped and deadline is not None and deadline <= now,
            unfollowed=unstopped and follow_rule and stamp <= now - self._orphan_grace,
            owed=tuple(sorted(owed or ())),
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
            elsewhere = (
                await Candidate.filter(run__owner=run.owner, state__in=_IN_FLIGHT)
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
        return StartPlan(
            run_id=run_id,
            owner=OwnerKey(run.owner),
            owner_email=run.owner_email,
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
    async def followed(self, run_id: str, at: datetime) -> None:
        # INVARIANT (R10): the stamp only moves forward, so a late or slow stamp never pulls the
        # orphan clock back.
        await Run.filter(
            Q(id=run_id), Q(last_followed_at__isnull=True) | Q(last_followed_at__lt=at)
        ).update(last_followed_at=at)

    @in_context
    async def stop(
        self,
        run_id: str,
        reason: StopReason,
        *,
        unless_followed_since: datetime | None = None,
    ) -> bool:
        """Stop the Run (R9) and say whether this call did. ``unless_followed_since`` makes an
        orphan stop do nothing when the Run was followed after that time (R10)."""
        now = self._clock()
        async with in_transaction(CONNECTION) as conn:
            await lock_run(run_id, conn)
            # INVARIANT (D12): the first stop's reason is kept. WHY owe the stops only in the
            # call that set it: a retry finds the stops that succeeded cleared, and must not owe
            # them again while their outcomes land.
            if not await _may_stop(run_id, unless_followed_since, conn) or not await Run.filter(
                id=run_id, stopped_by__isnull=True
            ).using_db(conn).update(stopped_by=reason, canceled=True):
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
        Client from before P2 registered (R11). Returns how many it moved.

        An unbound one is `stopped`; a bound one's start may have landed, so it becomes
        `scheduled` and its outcome, or reconcile, settles it.
        """
        now = self._clock()
        startless = Candidate.filter(state="pending", start__isnull=True)
        stopped = await startless.filter(topic__isnull=True).update(
            state="stopped", finished_at=now
        )
        scheduled = await startless.filter(topic__isnull=False).update(
            state="scheduled", bound_at=now
        )
        return stopped + scheduled


async def _may_stop(
    run_id: str, unless_followed_since: datetime | None, conn: BaseDBAsyncClient
) -> bool:
    """Whether a stop applies: the Run exists, something in it is live, and, for an orphan
    stop, nobody followed it after ``unless_followed_since`` (R9, R10)."""
    run = await Run.filter(id=run_id).using_db(conn).first()
    if run is None:
        return False
    if not await Candidate.filter(run_id=run_id, state__in=LIVE).using_db(conn).exists():
        return False
    followed = run.last_followed_at or run.created_at
    return unless_followed_since is None or followed <= unless_followed_since


__all__ = ["DriverStore"]
