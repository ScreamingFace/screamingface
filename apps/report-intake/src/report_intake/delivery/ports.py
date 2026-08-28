r"""The `TicketSink` port — the seam between "the report is stored" and "somebody can act on it".

**A sink receives already-rendered strings and never a report object** (plan §2.2). That is the
strong form of spec §4's content rule: an adapter cannot leak a payload it was never handed, so
the guarantee is a property of this signature rather than of a convention every future adapter is
trusted to keep. `PersistedReport` stays inside the store and does not cross here, and the one
thing that decides what a ticket carries is `delivery/render.py` — one module to audit, however
many sinks there eventually are.

The error taxonomy lives in this module rather than in a `delivery/errors.py`, for the same
reason `reports/pipeline.py` keeps `StorageUnavailable` beside its Protocol: one place to look for
"what can this seam do to me". The split between the two classes is the retry policy's only
input — `OME-1010` re-attempts a `pending` row and never a `failed` one — so an adapter that
raises `Permanent` for a transient outage silently drops reports, and one that raises `Retryable`
for a body the tracker will never accept spends six attempts reaching the same answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TicketContent:
    """Everything a sink is allowed to know about a report: strings, already rendered.

    `title` and `body` are the ticket. The scalars beside them are carried separately because a
    sink legitimately routes on them — a subscriber, a label, a search key — and digging them back
    out of the body with a regex is how a change to the renderer becomes a bug in every adapter.
    """

    ref: str
    title: str
    body: str
    trace_id: str | None = None
    reply_to: str | None = None
    """Self-asserted by the reporter and never identity (spec §2.1)."""
    caller_email: str | None = None
    """Present only when the mesh injected it, which is the only case anything may believe it."""

    def texts(self) -> tuple[str, ...]:
        r"""Every string that would travel, for the fail-closed re-check on the rendered body.

        Returned SEPARATELY rather than joined. A join invents adjacencies no sink will ever see,
        and "\n\nhuman:" — one of the detectors' markers — is exactly the shape two innocent
        fields can manufacture between them when a title ending in a newline meets a body that
        starts with a word.
        """
        parts = (self.title, self.body, self.trace_id, self.reply_to, self.caller_email)
        return tuple(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class Delivered:
    """The ticket exists and this is where it is."""

    ticket_id: str
    ticket_url: str


@dataclass(frozen=True, slots=True)
class Queued:
    """The report is ready for a human or an agent to file, and no ticket id exists yet.

    Carries nothing, deliberately: spec §2.2's success shape already models "durable, not yet
    filed" as `state` plus a null `ticket`, and inventing a queue handle here would be a second
    identifier for a row that already has `ref`.
    """


SinkResult = Delivered | Queued
"""What a sink can answer with. Not `bool`, and not an optional ticket: `queued` is a real
terminal state (plan §2.3), so the two outcomes have to be distinguishable by type rather than by
whether a field came back null."""


@runtime_checkable
class TicketSink(Protocol):
    async def deliver(self, content: TicketContent) -> SinkResult:
        """File `content`, or raise from the taxonomy below.

        Async because every real sink is a network call. `QueueSink` is not, and implements this
        anyway rather than forcing the caller to hold two shapes — a sink that answers instantly
        is the degenerate case of one that answers slowly, not a different port.
        """
        ...


class RetryableDeliveryError(Exception):
    """The sink could not file this report *now*: a timeout, a 5xx, a rate limit.

    Leaves the row `pending`, which is the one state `OME-1010`'s due-scan picks up.
    """


class PermanentDeliveryError(Exception):
    """The sink will never accept this report: a rejected body, a deleted project, a revoked
    credential.

    Leaves the row `failed`, which is terminal and never re-attempted. Raising it for something
    transient is how a report is lost silently, so an adapter unsure which one it is holding
    raises :class:`RetryableDeliveryError` — six wasted calls are cheaper than a dropped bug
    report, and `failed` is alarmed on while `pending` is not.
    """


__all__ = [
    "Delivered",
    "PermanentDeliveryError",
    "Queued",
    "RetryableDeliveryError",
    "SinkResult",
    "TicketContent",
    "TicketSink",
]
