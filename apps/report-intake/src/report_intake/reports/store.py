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

**The queue's drain path reads through here, and it is a command rather than an endpoint.**
:meth:`ReportStore.awaiting_triage`, :meth:`ReportStore.read_for_triage` and
:meth:`ReportStore.mark_filed` exist for `queue_cli.py`, reached by `kubectl exec`. Spec §1
removed `GET /v1/reports/{ref}` and these must not reinstate it under another name, so a
containment test asserts that nothing under `routes/` names any of the three.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple, cast

from tortoise.exceptions import BaseORMException, IntegrityError
from tortoise.queryset import QuerySet

from .models import TICKET_ID_MAX_LENGTH, TICKET_URL_MAX_LENGTH, Report
from .pipeline import DeliveryState, StorageUnavailable, mint_ref, request_fingerprint

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

_STORAGE_FAILURES = (BaseORMException, RuntimeError, OSError)
"""What "the database would not cooperate" looks like coming out of tortoise-orm 1.1.8.

Each member is here for a case that is NOT an ORM error, which is the whole point: a tidier tuple
turns one of them into a `500`, and spec §2.3 gives a reporting client exactly one status that
means *nothing was stored*.

`RuntimeError` — querying with no active Tortoise context, which is a process whose `_lifespan`
never opened the database or whose connections were closed under it. `tortoise.context
.require_context` raises a bare `RuntimeError`, not an ORM error.

`OSError` — THE CONNECTION NEVER OPENED. `Tortoise.init` is lazy for asyncpg, so an unreachable
Postgres is not a startup failure; it surfaces at the first query as `ConnectionRefusedError`, or
as `socket.gaierror` for a hostname that does not resolve, and neither is a `BaseORMException`.
Verified by probe: `awaiting_triage` against a closed loopback port raised
`ConnectionRefusedError` straight through this module. That is the most ordinary outage a deployed
install has, and without this line it was the one that answered `500`. `OSError` also SUBSUMES the
`TimeoutError` this tuple used to name — `asyncio.wait_for`'s deadline raises the builtin, which
has been an `OSError` subclass since 3.3 — so `STORAGE_TIMEOUT_S` is still covered.
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


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


@dataclass(frozen=True, slots=True)
class TriageReport:
    """One row as the operator console reads it (`queue_cli.py`) — the queue's drain path.

    `QueueSink` marking a row `queued` means "an agent will file this", and until `OME-1009`'s
    follow-up there was nothing that could name those rows: `cli.py` ran uvicorn, spec §1 forbids
    a `GET /v1/reports/{ref}`, and the queue was findable only by opening the database. Plan §13's
    verification says "confirm `queue list` shows it", so the drain path is a command reached by
    `kubectl exec`, NOT an endpoint — the forbidden read surface is forbidden by route, not by
    spelling, and adding one here under another name would be the same mistake.

    It carries `payload` for the same reason :class:`DueReport` does and with the same limit: the
    console re-validates it into a `ReportDocument` and renders through `render_ticket`, so the
    body an agent pastes into Linear is the one the sink would have sent rather than a second
    rendering of the same report. Unlike :class:`PersistedReport` this is not handed across the
    `TicketSink` seam — nothing in the console reaches a sink at all.
    """

    ref: str
    created_at: datetime
    """When the SERVER received the report. `occurred_at` lives in the payload and is the
    client's claim about when it broke, which is why the listing orders on this one — a clock
    a reporter controls must not decide what an operator reads first."""
    delivery_state: DeliveryState
    payload: Mapping[str, Any]
    reply_to: str | None
    caller_email: str | None
    ticket_id: str | None
    ticket_url: str | None


class Recorded(NamedTuple):
    report: PersistedReport
    created: bool
    """False for an idempotent replay, which the route answers `200` rather than `202`."""


def _triage(model: Report) -> TriageReport:
    # Same tortoise-orm >=1.1.8 typing caveat as `_persisted` below: every CharField reads as
    # `str | None` regardless of nullability, and the database enforces the real thing.
    return TriageReport(
        ref=cast(str, model.ref),
        created_at=model.created_at,
        delivery_state=cast(DeliveryState, model.delivery_state),
        payload=model.payload,
        reply_to=model.reply_to,
        caller_email=model.caller_email,
        ticket_id=model.ticket_id,
        ticket_url=model.ticket_url,
    )


def _clamped(ref: str, column: str, value: str, width: int) -> str:
    """`value` cut to the column's width, loudly. The backstop under every ticket-reference check.

    THIS EXISTS TO CLOSE A LOOP, not to be tidy. Tortoise validates `max_length` at `save`, and
    every ORM failure leaves this module as `StorageUnavailable` — which both writers of this
    column swallow on purpose, because the report is already durable and a delivery outcome that
    cannot be recorded must not turn a `202` into a `503`. The row would then keep
    `delivery_state='pending'` with `attempts` unmoved, and `attempts` is the retry budget's only
    input: the sweep re-claims it, the sink files ANOTHER issue, the write fails again, and
    `MAX_ATTEMPTS` is never reached because nothing ever increments it.

    So the write always succeeds and the state always advances. A clamped reference is wrong, and
    the ERROR line says so with the whole value — the row is the only place that pointer exists,
    and an operator reading the log can still reach the issue. Every caller is expected to have
    refused an over-wide value long before this (`queue_cli._ticket_argument`,
    `LinearSink._raise_for_unstorable_reference`); reaching here at all is a defect in one of
    them, which is why it is logged at ERROR rather than at WARNING.
    """
    if len(value) <= width:
        return value
    logger.error(
        "report %s: %s is %d characters and the column stores %d, so it is being recorded "
        "truncated rather than left unrecorded. The full value was %r. A sink that answers a "
        "reference this wide should be refusing it before the write — see "
        "LinearSink._raise_for_unstorable_reference.",
        ref,
        column,
        len(value),
        width,
        value,
    )
    return value[:width]


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

    async def awaiting_triage(self, *, limit: int) -> tuple[TriageReport, ...]:
        """The `queued` rows nobody has filed yet, newest first — spec §9's queue, as a list.

        `queued` ONLY, and that is the same reading `_due` takes from the other side: it is
        terminal SUCCESS, so it is exactly the set that is waiting on a human or an agent rather
        than on this service. `pending` rows belong to the retry queue and are not yet anyone's to
        file; `delivered` is done; `failed` is an alert (`retry.py` logs it at error), not a
        triage backlog — a report nothing will try again needs somebody paged, not somebody
        scrolling.

        NEWEST FIRST BY `created_at`, the server's clock. `occurred_at` is in the payload and is
        the client's claim about when the failure happened; ordering an operator's screen on a
        value a reporter chooses would let one report put itself at the top forever.

        `limit` is the caller's, and there is no unbounded spelling of this method. The queue is
        drained by a human reading a terminal, and a listing that pages a year of reports into it
        is one nobody reads at all.
        """
        try:
            return await asyncio.wait_for(self._awaiting_triage(limit), timeout=STORAGE_TIMEOUT_S)
        except _STORAGE_FAILURES as exc:
            raise StorageUnavailable("the triage queue could not be read") from exc

    async def read_for_triage(self, ref: str) -> TriageReport | None:
        """One row by `ref`, in whatever state, or None when there is no such report.

        None rather than an exception, because "no such ref" is an ordinary answer to an operator
        who mistyped one and is not a storage failure — the two have to stay distinguishable, or
        the console reports a database outage as a typo.

        INVARIANT: this is reachable from the console and from nowhere else.
        `tests/unit/test_triage_read_containment.py` asserts it, because the value of the rule is
        that it is already red when someone reaches for a by-ref read inside `routes/` — which is
        the `GET /v1/reports/{ref}` spec §1 removed, arriving under a different name.
        """
        try:
            return await asyncio.wait_for(self._read_for_triage(ref), timeout=STORAGE_TIMEOUT_S)
        except _STORAGE_FAILURES as exc:
            raise StorageUnavailable("the report could not be read") from exc

    async def mark_filed(self, ref: str, *, ticket_id: str, ticket_url: str) -> TriageReport | None:
        """Record that a human or an agent filed this report; returns the row, or None if it is
        gone.

        The counterpart to :meth:`record_delivery` for the one outcome this service did not
        produce itself. It is a separate method rather than a flag on that one for a reason that
        shows up in a column: `record_delivery` increments `attempts`, which is how hard THIS
        SERVICE tried, and a person filing a ticket by hand is not an attempt by this service. An
        operator reading `attempts = 2` on a row an agent filed would be reading a lie about the
        sink.

        WHETHER a mark is allowed is the console's decision, not this method's — the same division
        :meth:`claim_due` keeps, where the backoff that produces `due_before` is retry policy and
        the store is not where policy lives. This writes.

        ACCEPTED RACE: a `pending` row may be leased by a retry sweep at this instant, and that
        sweep's `record_delivery` would then write its own outcome over this one. It is not worth
        machinery: `QueueSink` — what every deployment runs — reaches a terminal state on the
        first attempt, so a `pending` row only exists at all where a sink is failing, and the mark
        can simply be repeated. The failure it would cause is a duplicate ticket, which is visible
        and cheap, never a lost report.
        """
        try:
            return await asyncio.wait_for(
                self._mark_filed(ref, ticket_id, ticket_url), timeout=STORAGE_TIMEOUT_S
            )
        except _STORAGE_FAILURES as exc:
            raise StorageUnavailable("the filed ticket could not be recorded") from exc

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
            report.ticket_id = _clamped(ref, "ticket_id", ticket_id, TICKET_ID_MAX_LENGTH)
            report.ticket_url = _clamped(ref, "ticket_url", ticket_url, TICKET_URL_MAX_LENGTH)
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
    async def _awaiting_triage(limit: int) -> tuple[TriageReport, ...]:
        rows = await Report.filter(delivery_state="queued").order_by("-created_at").limit(limit)
        return tuple(_triage(row) for row in rows)

    @staticmethod
    async def _read_for_triage(ref: str) -> TriageReport | None:
        row = await Report.get_or_none(ref=ref)
        return _triage(row) if row is not None else None

    @staticmethod
    async def _mark_filed(ref: str, ticket_id: str, ticket_url: str) -> TriageReport | None:
        # Named columns, exactly as `_record_delivery` does, so recording a ticket cannot rewrite
        # `payload` or move `created_at`. `attempts` is deliberately NOT among them — see the
        # public method. `updated_at` is `auto_now` and is listed so `save` refreshes it.
        report = await Report.get_or_none(ref=ref)
        if report is None:
            return None
        report.delivery_state = "delivered"
        report.ticket_id = ticket_id
        report.ticket_url = ticket_url
        await report.save(update_fields=["delivery_state", "ticket_id", "ticket_url", "updated_at"])
        return _triage(report)

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
