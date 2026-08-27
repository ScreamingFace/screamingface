"""The `reports` table, behind the only object allowed to write it.

Three rules from spec §5 and plan §6 are enforced here rather than remembered:

**Persist before deliver.** :meth:`ReportStore.record` returns only after the row is committed.
Nothing in this module can reach a sink, and `OME-1009`'s sink is handed rendered strings rather
than a report — so "the record exists before anything tries to file it" is a property of the
call graph, not of a convention. Calling the sink first and storing on success is the single
most common way a service like this drops reports.

**The dedup key identifies the submission, not its content.** Only `Idempotency-Key` resolves a
replay. `request_fingerprint` is written and indexed for a human reading the table and is never
consulted by :meth:`record` — the scoreboard deduplicates on a content hash and `OME-970` is
what that cost: a resubmission answered with *another* run's id.

**A storage failure is a `503`, never a partial write.** Every ORM failure leaves this module as
:class:`~report_intake.reports.pipeline.StorageUnavailable`, which the route renders as the one
status that tells a client to keep the report on disk.

**A retry candidate is claimed by the database, not by this process.**
:meth:`ReportStore.claim_due` takes each row with a conditional UPDATE against
`lease_expires_at`, so two replicas sweeping at the same instant cannot both believe they own
one report — which is what lets this service run with `replicaCount > 1` without filing a bug
report twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple, cast

from tortoise.exceptions import BaseORMException, IntegrityError
from tortoise.queryset import QuerySet

from .models import Report
from .pipeline import DeliveryState, StorageUnavailable, mint_ref

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]

STORAGE_TIMEOUT_S = 5.0
"""How long a write or a purge may spend inside the ORM before it counts as unavailable.

**This is not belt-and-braces; without it this service hangs on the exact failure spec §2.3's
`503` was written for.** tortoise-orm 1.1.8's `ConnectionWrapper.__aenter__`
(`backends/base/client.py`) acquires the connection lock and THEN opens the connection — so when
opening fails, `__aenter__` raises without ever returning, Python never calls `__aexit__`, and
the lock is held for the life of the process. Reproduced: with an unwritable sqlite path the
first query raises `OperationalError` and every query after it blocks forever. Postgres escapes
that particular shape (its pool wrapper takes its lock in an `async with`) but has its own: an
exhausted or dead pool makes `_pool.acquire()` wait with no deadline.

A request that hangs is strictly worse than one that fails: the client gets no answer at all,
cannot fall back to disk, and holds a worker while it waits.
"""

PROBE_TIMEOUT_S = 2.0
"""Tighter than a write, because a kubelet gives a probe about a second before it counts the
attempt as failed anyway. An unready answer now beats a correct answer after the deadline."""

_STORAGE_FAILURES = (BaseORMException, RuntimeError, TimeoutError)
"""What "the database would not cooperate" looks like coming out of tortoise-orm 1.1.8.

`RuntimeError` is in the tuple for one specific case and is not a catch-all: querying with no
active Tortoise context — a process whose `_lifespan` never opened the database, or whose
connections have been closed under it — raises a bare `RuntimeError` from
`tortoise.context.require_context`, not an ORM error. That is a `503` by any reading of spec
§2.3, and a tidier tuple would make it a `500`.
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


def request_fingerprint(payload: Mapping[str, Any]) -> str:
    """A stable digest of the stored payload — DIAGNOSTIC ONLY (see the module docstring).

    Deliberately strict about what it will serialize: `payload` came from `json.loads` and a
    truncator that only ever shortens strings, so a value this cannot encode is a bug worth a
    traceback rather than something to stringify quietly into a column.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PersistedReport:
    """One row, as everything outside this module sees it.

    INVARIANT (plan §2.2): this never crosses the `TicketSink` seam. A sink receives rendered
    strings, so an adapter cannot leak a payload it was never handed — which is what keeps spec
    §4's content rule enforceable at the port rather than by convention inside each adapter.
    """

    ref: str
    classification: str
    delivery_state: DeliveryState
    ticket_id: str | None
    ticket_url: str | None


@dataclass(frozen=True, slots=True)
class DueReport:
    """One row the retry queue has claimed, carrying only what a re-delivery needs.

    `payload` rather than a rendered anything: `OME-1010` re-validates it into a `ReportDocument`
    and hands THAT to the dispatcher, which is what makes a retried ticket byte-identical to the
    inline attempt's instead of a second, subtly different rendering of the same report.

    Like :class:`PersistedReport`, this never crosses the `TicketSink` seam (plan §2.2).
    """

    ref: str
    payload: Mapping[str, Any]
    caller_email: str | None
    attempts: int
    """How many attempts this report has already had. It is the backoff's only input, which is
    why :meth:`ReportStore.record_delivery` increments it after every one."""


class Recorded(NamedTuple):
    report: PersistedReport
    created: bool
    """False for an idempotent replay, which the route answers `200` rather than `202`."""


def _persisted(model: Report) -> PersistedReport:
    # The casts are tortoise-orm >=1.1.8's typing, not a narrowing this code is asserting on its
    # own: it types every CharField as `str | None` regardless of nullability, so a NOT NULL
    # column still reads as optional. The database enforces the real thing.
    return PersistedReport(
        ref=cast(str, model.ref),
        classification=cast(str, model.classification),
        delivery_state=cast(DeliveryState, model.delivery_state),
        ticket_id=model.ticket_id,
        ticket_url=model.ticket_url,
    )


class ReportStore:
    """Every read and write of the `reports` table.

    The TTL and the retention window are constructor arguments rather than module constants
    because they are `Settings` fields (plan §2.4) — a test that wants a closed idempotency
    window must not have to move the clock by a day.
    """

    def __init__(
        self,
        idempotency_ttl: timedelta,
        retention: timedelta,
        clock: Clock = utc_now,
    ) -> None:
        self._idempotency_ttl = idempotency_ttl
        self._retention = retention
        self._clock = clock

    async def record(
        self,
        *,
        payload: Mapping[str, Any],
        classification: str,
        caller_email: str | None,
        reply_to: str | None,
        idempotency_key: str | None,
    ) -> Recorded:
        """Commit the report, or replay the original one this key already produced.

        Raises :class:`StorageUnavailable` if the row could not be committed. There is no third
        outcome: this returns a row that exists, or it raises.

        ACCEPTED IMPRECISION: a timeout that fires after the INSERT committed but before this
        returns answers `503` for a report that IS stored, and spec §2.3 says `503` means nothing
        was stored. The window is small — the timeout overwhelmingly fires while acquiring a
        connection, long before any statement runs — and the cost of being wrong is one duplicate
        report from a client that retries, or none at all when it sent an `Idempotency-Key`. The
        alternative is a request that never answers, which no client can do anything with.
        """
        try:
            return await asyncio.wait_for(
                self._record(
                    now=self._clock(),
                    payload=payload,
                    classification=classification,
                    caller_email=caller_email,
                    reply_to=reply_to,
                    idempotency_key=idempotency_key,
                ),
                timeout=STORAGE_TIMEOUT_S,
            )
        except _STORAGE_FAILURES as exc:
            raise StorageUnavailable("the report could not be committed") from exc

    async def record_delivery(
        self,
        ref: str,
        *,
        state: DeliveryState,
        ticket_id: str | None = None,
        ticket_url: str | None = None,
        next_attempt_at: datetime | None = None,
    ) -> PersistedReport:
        """Write what one delivery attempt decided, and return the row as it now stands.

        Called after EVERY attempt, including one that got nowhere: `attempts` is what the retry
        backoff counts, and a row that says zero attempts after the inline one has run
        understates how hard this report has already been tried.

        `next_attempt_at` is supplied ONLY by the retry queue, which owns the schedule. The
        request path passes nothing and the deadline is left where the insert put it — a row due
        at `created_at` is exactly what the sweep is built to find. When it IS supplied the lease
        is released to the same moment, so the row becomes unleased precisely when it falls due;
        the outcome and the schedule therefore land in one statement rather than in two writes a
        crash could separate.

        The signature takes primitives rather than a `DeliveryOutcome` so that this module — the
        only writer of the table — keeps no import of the delivery package. The store does not
        know that sinks exist, which is the same reason nothing in here can reach one.

        Raises :class:`StorageUnavailable` like every other write. The pipeline catches it: the
        report is already committed at this point, so failing to record the OUTCOME must not turn
        a durable `202` into a `503` that makes the client file the report twice.
        """
        try:
            return await asyncio.wait_for(
                self._record_delivery(ref, state, ticket_id, ticket_url, next_attempt_at),
                timeout=STORAGE_TIMEOUT_S,
            )
        except _STORAGE_FAILURES as exc:
            raise StorageUnavailable("the delivery outcome could not be recorded") from exc

    async def claim_due(
        self, *, due_before: datetime, lease_until: datetime, limit: int
    ) -> tuple[DueReport, ...]:
        """Take ownership of up to `limit` reports whose next attempt is owed, and return them.

        `due_before` is one moment for both halves of the predicate: a row is a candidate when
        its retry deadline AND any lease on it fell before it. Every moment is the caller's —
        this method holds no schedule of its own, because the backoff and the grace that produce
        `due_before` are retry policy and the store is not where policy lives.

        THE CLAIM IS A CONDITIONAL UPDATE, and that is the whole of it: each row is taken by an
        UPDATE whose WHERE clause repeats the due predicate, so the database — not this process —
        decides who got it. A read-then-write sweep would let two replicas file the same bug
        report as two tickets, which is the failure `lease_expires_at` exists to prevent and the
        reason this service can be deployed with `replicaCount > 1` at all.

        Raises :class:`StorageUnavailable` like every other write. A sweep that cannot claim
        anything is a sweep that does nothing, not a process that dies.
        """
        try:
            return await asyncio.wait_for(
                self._claim_due(due_before, lease_until, limit), timeout=STORAGE_TIMEOUT_S
            )
        except _STORAGE_FAILURES as exc:
            raise StorageUnavailable("reports due for retry could not be claimed") from exc

    async def purge_expired(self, now: datetime | None = None) -> int:
        """Delete rows past spec §5's retention window; returns how many went.

        The ticket is the durable artifact. A row exists for idempotency, retry, and operational
        forensics, all of which are over long before 90 days.
        """
        cutoff = (now if now is not None else self._clock()) - self._retention
        try:
            return await asyncio.wait_for(
                Report.filter(created_at__lte=cutoff).delete(), timeout=STORAGE_TIMEOUT_S
            )
        except _STORAGE_FAILURES as exc:
            raise StorageUnavailable("expired reports could not be purged") from exc

    async def is_reachable(self) -> bool:
        """The readiness probe (plan §2.5), installed on `app.state.readiness_check`.

        It touches the `reports` table rather than the connection, because the two failures a
        rollout must not survive are indistinguishable from the connection's point of view: a
        database that is down, and a database whose migration has not been applied. This service
        never migrates itself, so the second is the ordinary state of a freshly deployed pod and
        must keep it out of the load balancer until an operator has run `tortoise migrate`.

        Fails closed on ANY error and on the deadline, and says so in the log: a readiness probe
        that flips to unready without leaving a reason behind is an outage with no first clue.
        """
        try:
            await asyncio.wait_for(Report.all().limit(1).exists(), timeout=PROBE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — see below
            # Deliberately every exception, and the only place in this app that does it. The
            # answers this probe can give are "ready" and "not ready"; there is no third one it
            # could usefully raise, and a probe that propagates turns a `503` a kubelet
            # understands into a `500` it treats as a broken service. The breadth is not
            # hypothetical: an uninitialised Tortoise — a pod whose `_lifespan` never opened the
            # database — raises a bare `RuntimeError`, not an ORM error, so a tidier
            # `except BaseORMException` fails exactly the case this exists for. The deadline
            # matters for the same reason: see STORAGE_TIMEOUT_S for the tortoise lock that is
            # held forever after a failed connect, which makes "hangs" the default failure here.
            logger.warning("readiness probe: the reports table is not queryable (%s)", exc)
            return False
        return True

    async def _record(
        self,
        *,
        now: datetime,
        payload: Mapping[str, Any],
        classification: str,
        caller_email: str | None,
        reply_to: str | None,
        idempotency_key: str | None,
    ) -> Recorded:
        replay = await self._replay(idempotency_key, now)
        if replay is not None:
            return Recorded(replay, created=False)
        try:
            return Recorded(
                await self._insert(
                    now=now,
                    payload=payload,
                    classification=classification,
                    caller_email=caller_email,
                    reply_to=reply_to,
                    idempotency_key=idempotency_key,
                ),
                created=True,
            )
        except IntegrityError:
            # A concurrent request won the race on the unique key between the lookup above and
            # this insert. The desired end state — one report per key per window — holds either
            # way, so the loser replays the winner's row instead of failing a reporter's request.
            raced = await self._replay(idempotency_key, now)
            if raced is None:
                raise
            return Recorded(raced, created=False)

    async def _record_delivery(
        self,
        ref: str,
        state: DeliveryState,
        ticket_id: str | None,
        ticket_url: str | None,
        next_attempt_at: datetime | None,
    ) -> PersistedReport:
        # Named columns, so a delivery outcome cannot rewrite `payload` or move `created_at` —
        # the two values every policy in this service measures against.
        updated = ["delivery_state", "attempts", "ticket_id", "ticket_url", "updated_at"]
        report = await Report.get(ref=ref)
        report.delivery_state = state
        report.attempts += 1
        if ticket_id is not None and ticket_url is not None:
            # Only ever set, never cleared. A later attempt that comes back `queued` must not
            # erase the ticket an earlier one filed — the columns are the ticket's address, and
            # losing it would leave a delivered report looking undelivered.
            report.ticket_id = ticket_id
            report.ticket_url = ticket_url
        if next_attempt_at is not None:
            report.next_attempt_at = next_attempt_at
            report.lease_expires_at = next_attempt_at
            updated += ["next_attempt_at", "lease_expires_at"]
        await report.save(update_fields=updated)
        return _persisted(report)

    async def _claim_due(
        self, due_before: datetime, lease_until: datetime, limit: int
    ) -> tuple[DueReport, ...]:
        # Oldest deadline first, so a backlog drains in the order it fell due rather than in
        # whatever order the table hands back — the report that has been waiting longest is the
        # one whose reporter has been waiting longest.
        candidates = await self._due(due_before).order_by("next_attempt_at").limit(limit)
        claimed: list[DueReport] = []
        for report in candidates:
            # `.update()` answers with the number of rows it changed, and for a single-row
            # predicate that number IS the arbitration: 1 means this process took the row, 0
            # means another replica leased it between the scan above and this statement. Claiming
            # one row per statement rather than the whole batch in one is what makes the answer
            # attributable — a batch UPDATE reports how many it won, never which.
            taken = (
                await self._due(due_before)
                .filter(ref=report.ref)
                .update(lease_expires_at=lease_until)
            )
            if taken:
                claimed.append(
                    DueReport(
                        ref=cast(str, report.ref),
                        payload=report.payload,
                        caller_email=report.caller_email,
                        attempts=report.attempts,
                    )
                )
        return tuple(claimed)

    @staticmethod
    def _due(due_before: datetime) -> QuerySet[Report]:
        """Spec §6's retry candidates: `pending`, owed an attempt, and held by nobody.

        `pending` ONLY (plan §2.3, §11 conflict 8). `queued` is terminal SUCCESS — `QueueSink`
        answering it means an agent will file the report — and a scan that read it as "no attempt
        scheduled" would re-deliver every successfully queued report six times and then alarm on
        it. `delivered` and `failed` are terminal for the obvious reasons.
        """
        return Report.filter(
            delivery_state="pending",
            next_attempt_at__lte=due_before,
            lease_expires_at__lte=due_before,
        )

    async def _replay(self, idempotency_key: str | None, now: datetime) -> PersistedReport | None:
        """The original record for this key if the window is still open, else None."""
        # The guard is inside the expression rather than an early return because a lookup on
        # `idempotency_key=None` is not "no key" — it matches every keyless row, which would make
        # anonymous reports replay each other.
        existing = (
            await Report.get_or_none(idempotency_key=idempotency_key)
            if idempotency_key is not None
            else None
        )
        if existing is None:
            return None
        if existing.created_at > now - self._idempotency_ttl:
            return _persisted(existing)
        # Past the window the same key is a new report (spec §5). The key is RELEASED rather
        # than the row deleted: the column is unique, so the stale binding would otherwise
        # refuse the insert, and the old row is still owed its 90 days of retention.
        await Report.filter(ref=existing.ref).update(idempotency_key=None)
        return None

    async def _insert(
        self,
        *,
        now: datetime,
        payload: Mapping[str, Any],
        classification: str,
        caller_email: str | None,
        reply_to: str | None,
        idempotency_key: str | None,
    ) -> PersistedReport:
        report = await Report.create(
            # Server-minted, and minted HERE rather than taken as an argument: the primary key is
            # the one column a client must never be able to influence, and the way to guarantee
            # that is for no caller to be able to supply it.
            ref=mint_ref(),
            idempotency_key=idempotency_key,
            payload=dict(payload),
            classification=classification,
            caller_email=caller_email,
            reply_to=reply_to,
            delivery_state="pending",
            attempts=0,
            # All three from ONE clock (plan §2.3: both deadlines default to `created_at` at
            # insert). The first attempt is due now and the row starts unleased, so
            # `OME-1010`'s conditional claim can take it on the next sweep.
            created_at=now,
            next_attempt_at=now,
            lease_expires_at=now,
            request_fingerprint=request_fingerprint(payload),
        )
        return _persisted(report)
