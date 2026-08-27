"""The pipeline the deployed service runs: bound report in, committed row out, ticket attempted.

The order of the two lines in :meth:`StorePipeline.submit` is the whole of spec §5's
persist-before-deliver rule, and it is enforced by the call graph rather than by a comment: the
dispatcher is reached only through a `Recorded` that a committed row produced. Calling the sink
first and storing on success is the single most common way a service like this drops reports, and
it is prohibited here.

INVARIANT: a delivery failure is never a request failure. Everything the dispatcher can answer is
a `DeliveryOutcome`, and failing to record that outcome is caught below — the report is durable
either way, and `202` with `delivery.state = "pending"` is the honest answer for one whose ticket
does not exist yet. A `503` there would tell the client nothing was stored, and it would file the
same report again.

INVARIANT: this class does not classify. Spec §4 rejects content rather than storing it, and the
only structural guarantee of that is that the refusal happens at the route, before anything
capable of persisting is reached (plan §2.7). A classify call added here would be one edit away
from persist-then-classify.
"""

from __future__ import annotations

import logging

from ..delivery.dispatch import TicketDispatcher
from .pipeline import Accepted, StorageUnavailable, Submission, Ticket
from .store import PersistedReport, ReportStore

logger = logging.getLogger(__name__)


class StorePipeline:
    def __init__(self, store: ReportStore, dispatcher: TicketDispatcher) -> None:
        self._store = store
        self._dispatcher = dispatcher

    async def submit(self, submission: Submission) -> Accepted:
        recorded = await self._store.record(
            # `payload`, never `scanned`: the truncated mapping is what spec §2.4 says this
            # service keeps, and `scanned` exists only so the classifier could not be walked
            # around by pushing text past a field cap.
            payload=submission.bound.payload,
            classification=submission.classification,
            caller_email=submission.caller_email,
            # Self-asserted by the reporter and never identity — it is a reply address, and the
            # column it lands in is not the one anything authorizes on.
            reply_to=submission.bound.document.reply_to,
            idempotency_key=submission.dedup_key,
        )
        if not recorded.created:
            # A replay is answered with the ORIGINAL record and delivers NOTHING: one report, one
            # ticket, regardless of double-clicks or client retries (spec §5). Re-dispatching here
            # would make the idempotency window a way to file the same bug twice — and the second
            # attempt would overwrite a `delivered` row's state with whatever it got.
            return _accepted(recorded.report, replayed=True)
        _log_truncations(recorded.report.ref, submission)
        return _accepted(await self._deliver(recorded.report, submission), replayed=False)

    async def _deliver(self, report: PersistedReport, submission: Submission) -> PersistedReport:
        """One inline attempt, inside spec §6's deadline, on a row that already exists."""
        outcome = await self._dispatcher.dispatch(
            ref=report.ref,
            # The typed view of what was persisted, never the report object: `PersistedReport`
            # does not cross the `TicketSink` seam (plan §2.2), and the dispatcher is what turns
            # this into the rendered strings a sink is allowed to see.
            document=submission.bound.document,
            caller_email=submission.caller_email,
        )
        try:
            return await self._store.record_delivery(
                report.ref,
                state=outcome.state,
                ticket_id=outcome.ticket_id,
                ticket_url=outcome.ticket_url,
            )
        except StorageUnavailable as exc:
            # ACCEPTED IMPRECISION: if the outcome was `delivered`, the row still says `pending`
            # and `OME-1010` will file it a second time. The alternatives are worse — answering
            # `503` would tell a client with a durable report that nothing was stored, and letting
            # this out would answer `500`. A duplicate ticket is visible and cheap; a lost bug
            # report is neither.
            logger.warning(
                "report %s: delivery answered %r but the outcome could not be recorded (%s)",
                report.ref,
                outcome.state,
                exc,
            )
            return report


def _log_truncations(ref: str, submission: Submission) -> None:
    """Give spec §2.4's out-of-band "mark" a reader, tied to the `ref` it belongs to.

    Most §2.4 rows mark IN BAND, so the mark survives into the payload and onto the ticket. Two
    cannot: a dropped `notes[]` item leaves nothing behind (a seventeenth note saying "and 4 more"
    would break the very cap that produced it), and the `error.details` re-serialization records
    its original size only here. Without this line those two marks exist in a tuple nothing ever
    reads, which is the same as not marking at all.

    A log line rather than a payload key or a ticket section, and both alternatives are ruled out
    by an invariant rather than by taste. `payload` is re-validated by `OME-1010` against a
    `ReportDocument` with `extra="forbid"`, so a namespaced sibling key would make every retry
    fail validation and mark the report terminally `failed`. A ticket section would break
    `render.py`'s invariant that a retry re-renders a byte-identical body from the stored payload,
    since `truncations` is deliberately not persisted.

    INVARIANT: pointers and sizes, never values. A pointer is a path and a size is a number; the
    text that was cut is exactly the material `classification/content.py` refuses to echo.
    """
    if not submission.bound.truncations:
        return
    logger.info(
        "report %s was truncated to the §2.4 caps: %s",
        ref,
        "; ".join(
            f"{mark.pointer} kept {mark.kept} of {mark.original} {mark.unit}"
            for mark in submission.bound.truncations
        ),
    )


def _accepted(report: PersistedReport, *, replayed: bool) -> Accepted:
    """Spec §2.2's one success shape, read back out of the row rather than rebuilt from the
    request — which is what makes a replay return the ORIGINAL record instead of a fresh echo of
    what the client just sent."""
    ticket = None
    if report.ticket_id is not None and report.ticket_url is not None:
        ticket = Ticket(id=report.ticket_id, url=report.ticket_url)
    return Accepted(
        ref=report.ref,
        classification=report.classification,
        delivery_state=report.delivery_state,
        ticket=ticket,
        replayed=replayed,
    )
