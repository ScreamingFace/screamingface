"""Spec §6's retry queue: the sweep that gives a `pending` report the attempts it is still owed.

Same shape as `reports/retention.py`, for the same reasons: `sweep()` is one pass and does no
waiting, so every policy question below is answered by a test that runs in milliseconds, and
`run()` is the forever-loop the ASGI lifespan owns. **It is started inside `_lifespan`, never
`app.router.on_startup`** (plan §11 conflict 12) — on the pinned starlette an appended startup
handler is dropped with no exception and no warning, so this loop would never run in production
while its unit tests kept passing. That failure is quieter here than it is for retention: nothing
in the response tells a reporter whether their `pending` report was ever tried again.

Four decisions carry the weight.

**The due-scan reads `pending` and nothing else** (plan §2.3, §11 conflict 8). `queued` is
terminal SUCCESS — the row is in `queue list` for an agent to file — and a sweep that read it as
"no attempt is scheduled" would re-deliver every successfully queued report six times and then
alarm on it as permanently failed.

**A row is claimed, not merely selected.** :meth:`ReportStore.claim_due` takes it with a
conditional UPDATE against `lease_expires_at`, so the database arbitrates between replicas. The
lease is also what makes a replica dying mid-attempt survivable: the row is claimable again once
it expires, rather than being stranded in somebody else's memory.

**The batch is the rate limit, not the backoff.** Spec §6 says retries must not stampede the
sink, and the backoff alone does not achieve that: a sink outage makes every row fail in the same
sweep, which schedules all of their next attempts into the same instant. `BATCH_LIMIT` rows per
`SWEEP_INTERVAL` is a ceiling that holds no matter how large the backlog is.

**A report is re-rendered from its stored payload, through the same dispatcher the request path
used.** Not a second delivery path: the retry attempt gets the same renderer, the same
fail-closed re-check and the same deadline, because a body that differs between the inline
attempt and the retry is a body nobody has reviewed.

**The budget counts the inline attempt**, because `attempts` is one column and an operator
reading it has been told how hard this report was tried, not how hard one component tried. That
has a visible consequence: the request path leaves the row `pending` with `attempts = 1` and its
deadline still at `created_at` — `OME-1009` left it there deliberately, so this sweep would find
it — which means the FIRST retry happens once the grace has passed rather than twelve minutes
later. That is the right answer for the case it comes from: the inline attempt was cut off by a
3 s deadline, and a sink that merely took four seconds deserves a prompt second try rather than a
twelve-minute wait. The remaining gaps are the schedule's, so a report that never lands is tried
six times across a little under 24 h and is then terminally `failed`. The narrow case where even
the inline OUTCOME could not be written — `attempts = 0` at the first claim — gets the full
schedule, all 24 h of it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

from pydantic import ValidationError

from ..delivery.dispatch import DeliveryOutcome, TicketDispatcher
from .pipeline import DeliveryState, StorageUnavailable
from .schema import ReportDocument
from .store import Clock, DueReport, ReportStore, utc_now

logger = logging.getLogger(__name__)

RETRY_BACKOFF: tuple[timedelta, ...] = tuple(
    timedelta(seconds=seconds) for seconds in (720, 2160, 6480, 19440, 57600)
)
"""Spec §6's exponential backoff, as the gaps BETWEEN attempts: 12 min, 36 min, 1.8 h, 5.4 h,
16 h. They sum to exactly 86 400 s — six attempts spanning 24 h, which is what "6 attempts over
roughly 24 h" means. The last step is trimmed from a clean ×3 (58 320 s) so the total is the day
rather than a day and twelve minutes; the arithmetic is asserted by a test rather than left as a
claim in a comment."""

MAX_ATTEMPTS = len(RETRY_BACKOFF) + 1
"""Six attempts, five gaps. Derived rather than written twice: a schedule and a budget that can
drift apart is how a report is either abandoned early or retried after the last gap has passed.

This counts EVERY attempt the service made, the inline one included — `attempts` is one column,
and an operator reading `attempts = 6` has been told the truth about how hard this report was
tried."""

SWEEP_INTERVAL = timedelta(seconds=60)
BATCH_LIMIT = 20
"""Together, the ceiling on how fast this service can talk to a sink: 20 attempts a minute,
whatever the backlog. Deliberately not environment variables — plan §2.4 fixes the set the chart
renders, and a knob nobody would turn is one more name that can drift out of `Settings`."""

LEASE = timedelta(minutes=5)
"""How long a claim holds. Comfortably longer than one attempt can take (a 3 s dispatch and two
5 s storage deadlines) and short enough that a pod killed mid-attempt does not strand the report
for the rest of its backoff."""

CLAIM_GRACE = timedelta(seconds=30)
"""How long a due row is left alone before the sweep will touch it.

**The inline attempt holds no lease.** `StorePipeline` commits the row — `pending`, due at
`created_at`, unleased — and only then calls the sink, so for the length of that attempt there is
a window in which a sweeper on another replica would happily claim a report the request path is
already delivering. The result would be two tickets for one bug report, which is the exact
failure the lease exists to prevent, arriving through the one door the lease does not cover.

The grace closes it: nothing is a candidate until longer than a whole inline attempt has passed.
It costs 30 s off a 12-minute first backoff, and a test asserts it still exceeds the worst-case
inline attempt if either deadline is raised.
"""


def _document(due: DueReport) -> ReportDocument | None:
    """The stored payload as a typed report, or None when it no longer validates.

    A row survives 90 days and this model changes; a payload written against an older shape must
    not be an exception in the middle of a sweep. It cannot be delivered either — the renderer
    reads named attributes — so it is terminal rather than retryable: five more attempts would
    re-validate the same bytes and reach the same answer.

    INVARIANT: the log line names the failing locations and never the error object, whose `input`
    carries the offending value. That is `binding.py`'s rule, and it does not stop applying
    because this is a log rather than a response.
    """
    try:
        return ReportDocument.model_validate(due.payload)
    except ValidationError as exc:
        logger.error(
            "report %s can no longer be read back from its stored payload and will not be "
            "retried; the row is marked failed for a human to read (%d violation(s) at %s)",
            due.ref,
            exc.error_count(),
            ", ".join(_locations(exc)),
        )
        return None


def _locations(exc: ValidationError) -> Iterable[str]:
    return sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})


class RetryQueue:
    """The policy object. Everything about *when* a report is tried again lives here."""

    def __init__(
        self,
        store: ReportStore,
        dispatcher: TicketDispatcher,
        *,
        interval: timedelta = SWEEP_INTERVAL,
        batch: int = BATCH_LIMIT,
        lease: timedelta = LEASE,
        clock: Clock = utc_now,
    ) -> None:
        self._store = store
        self._dispatcher = dispatcher
        self._interval = interval
        self._batch = batch
        self._lease = lease
        self._clock = clock

    async def sweep(self) -> int:
        """One pass: claim what is due and attempt each of it. Returns how many were attempted.

        Never raises, for the same reason the retention sweep does not: a database that is
        briefly unreachable is what `/readyz` is for, and an exception escaping here would end
        the loop for the life of the process — silently, since nothing in a response mentions
        retry. Logged at warning so a queue that has been stuck for a week is visible rather than
        merely quiet.
        """
        now = self._clock()
        try:
            due = await self._store.claim_due(
                due_before=now - CLAIM_GRACE, lease_until=now + self._lease, limit=self._batch
            )
        except StorageUnavailable as exc:
            logger.warning(
                "retry sweep could not claim any report; will retry next sweep (%s)", exc
            )
            return 0
        for report in due:
            # Sequentially, never gathered. One report in flight at a time is the second half of
            # "retries must not stampede the sink" — the batch bounds how many an interval may
            # attempt, this bounds how many arrive at once.
            await self._attempt(report)
        return len(due)

    async def run(self) -> None:
        """Sweep, then sweep again every interval, until cancelled.

        The first pass runs immediately rather than after a wait: a pod restarted more often than
        the interval would otherwise never retry anything, and that is the ordinary life of a pod
        during a rollout.
        """
        while True:
            await self.sweep()
            await asyncio.sleep(self._interval.total_seconds())

    async def _attempt(self, due: DueReport) -> None:
        document = _document(due)
        if document is None:
            await self._record(due, DeliveryOutcome("failed"))
            return
        outcome = await self._dispatcher.dispatch(
            ref=due.ref, document=document, caller_email=due.caller_email
        )
        await self._record(due, outcome)

    async def _record(self, due: DueReport, outcome: DeliveryOutcome) -> None:
        state, next_attempt_at = self._schedule(due.ref, outcome, due.attempts + 1)
        try:
            await self._store.record_delivery(
                due.ref,
                state=state,
                ticket_id=outcome.ticket_id,
                ticket_url=outcome.ticket_url,
                next_attempt_at=next_attempt_at,
            )
        except StorageUnavailable as exc:
            # The row keeps this sweep's lease and is re-claimed once it expires, so the report is
            # tried again rather than lost. The cost of that is one duplicate attempt when the
            # outcome that could not be written was a success — the same accepted imprecision the
            # inline path documents, and the same reasoning: a duplicate ticket is visible and
            # cheap, a dropped bug report is neither.
            logger.warning(
                "report %s: retry answered %r but the outcome could not be recorded (%s)",
                due.ref,
                outcome.state,
                exc,
            )

    def _schedule(
        self, ref: str, outcome: DeliveryOutcome, attempts: int
    ) -> tuple[DeliveryState, datetime]:
        """What this attempt leaves behind: the state to write, and when the next one is due.

        A terminal outcome needs no deadline — the due-scan filters on the state — but one is
        written anyway so the row is never left leased by a sweep that has finished with it.
        """
        now = self._clock()
        if outcome.state != "pending":
            return outcome.state, now
        if attempts >= MAX_ATTEMPTS:
            # Spec §6: a report we permanently failed to file is an operational event, not a
            # shrug. `failed` is the state an alert is built on and this is the line it reads;
            # the report itself is still in the table, and still readable behind Access.
            logger.error(
                "report %s could not be filed in %d attempts across a %s backoff and is now "
                "terminally failed; nothing will try it again",
                ref,
                attempts,
                sum(RETRY_BACKOFF, timedelta()),
            )
            return "failed", now
        return "pending", now + RETRY_BACKOFF[attempts - 1]


__all__ = [
    "BATCH_LIMIT",
    "CLAIM_GRACE",
    "LEASE",
    "MAX_ATTEMPTS",
    "RETRY_BACKOFF",
    "SWEEP_INTERVAL",
    "RetryQueue",
]
