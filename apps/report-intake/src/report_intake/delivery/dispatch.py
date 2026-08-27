"""One inline delivery attempt: render, re-check, call the sink under a deadline, answer a state.

Three rules from spec §6 and plan §7 live here rather than in the pipeline, because all three are
about the sink and none of them is about storage.

**A sink never fails a reporter's request.** Everything below returns a `DeliveryOutcome`; nothing
propagates. The row is already committed by the time this runs, so an exception escaping here
would turn a durable `202` into a `500` — and a client that reads `500` files the same report
again. A slow or dead sink is a `pending` row, which is what the retry queue is for.

**The deadline is spec §6's 3 s** (plan §11 conflict 18 — not the drafting pass's 10 s), injected
rather than a constant here, because it is a `Settings` field and a test must be able to make it
expire without waiting three seconds.

**The rendered body is re-checked fail-closed, with `scan_text` and never `classify_report`**
(plan §2.7). `classify_report` is scoped by JSON pointer; handing it one rendered string marks
every report as content, so nothing would ever be delivered and the retry path would be
short-circuited as permanent. The re-check should never fire — the route already classified this
report and refused a `content` verdict with a `422` — which is exactly why it is worth having: it
is the backstop for the case the route cannot see, a marker that only exists once two innocent
fields are rendered next to each other.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ..classification.content import scan_text
from ..reports.pipeline import DeliveryState
from ..reports.schema import ReportDocument
from .ports import (
    Delivered,
    PermanentDeliveryError,
    RetryableDeliveryError,
    SinkResult,
    TicketContent,
    TicketSink,
)
from .render import render_ticket

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """What one attempt decided, in the vocabulary of the `delivery_state` column.

    `pending` is not a failure to report to the client: it is "durable, not filed yet", which is
    what `202` means. Only `failed` is terminal, and it is the one an operator is alarmed on.
    """

    state: DeliveryState
    ticket_id: str | None = None
    ticket_url: str | None = None


class TicketDispatcher:
    def __init__(self, sink: TicketSink, timeout: float) -> None:
        self._sink = sink
        self._timeout = timeout

    async def dispatch(
        self, *, ref: str, document: ReportDocument, caller_email: str | None
    ) -> DeliveryOutcome:
        """Render this report and try to file it once. Never raises."""
        content = render_ticket(ref=ref, document=document, caller_email=caller_email)
        refusal = _content_in(content)
        if refusal is None:
            return await self._attempt(content)
        # Terminal, not retryable: a retry renders the same body from the same row and reaches the
        # same refusal, so `pending` here would be six identical refusals over 24 h. `failed` is
        # also the state that gets looked at, which is right — this means the renderer and the
        # classifier disagree about one report, and somebody should read it.
        logger.error(
            "refusing to deliver report %s: the rendered ticket %s. Nothing was sent to the "
            "sink; the report is still in the table for a human to read.",
            ref,
            refusal,
        )
        return DeliveryOutcome("failed")

    async def _attempt(self, content: TicketContent) -> DeliveryOutcome:
        try:
            result = await asyncio.wait_for(self._sink.deliver(content), timeout=self._timeout)
        except PermanentDeliveryError as exc:
            logger.error(
                "report %s will never be accepted by this ticket sink and is being marked "
                "failed (%s)",
                content.ref,
                exc,
            )
            return DeliveryOutcome("failed")
        except Exception as exc:  # noqa: BLE001 — see _log_retryable
            _log_retryable(content.ref, exc)
            return DeliveryOutcome("pending")
        return _outcome(result)


def _outcome(result: SinkResult) -> DeliveryOutcome:
    if isinstance(result, Delivered):
        return DeliveryOutcome(
            "delivered", ticket_id=result.ticket_id, ticket_url=result.ticket_url
        )
    return DeliveryOutcome("queued")


def _content_in(content: TicketContent) -> str | None:
    """The reason a rendered ticket carries content, or None.

    Each string is scanned on its own (`TicketContent.texts`), so the answer is about what a sink
    would actually receive rather than about a join this code invented.
    """
    for text in content.texts():
        reason = scan_text(text)
        if reason is not None:
            return reason
    return None


def _log_retryable(ref: str, exc: BaseException) -> None:
    """Why the broad `except` above is deliberate rather than lazy.

    An adapter is third-party-shaped code: an HTTP client raises its own errors, a JSON decode
    raises `ValueError`, a bad response raises `KeyError`. The row is already committed when any
    of that happens, so letting it out is a `500` for a report that IS stored — and a reporting
    client answers `500` by filing again. Treating it as retryable keeps the `202` honest and puts
    the report in front of `OME-1010`'s sweep.

    `asyncio.CancelledError` derives from `BaseException` and is NOT caught, so a shutdown still
    cancels the request rather than being logged as a sink bug.

    The two log levels are the difference between "expected, will retry" and "an adapter is
    broken": the second gets a traceback, because it is a defect in this repo.
    """
    if isinstance(exc, RetryableDeliveryError | TimeoutError):
        logger.warning("report %s was not filed and stays pending for retry (%s)", ref, exc)
        return
    logger.error(
        "report %s: the ticket sink raised outside its declared taxonomy; treating it as "
        "retryable so a stored report is not answered with a 500",
        ref,
        exc_info=exc,
    )


__all__ = ["DeliveryOutcome", "TicketDispatcher"]
