"""What happens to a report once it is bounded — behind a port, so the route never grows one.

`OME-1008`'s :class:`~report_intake.reports.store_pipeline.StorePipeline` is what the composition
root installs here; :class:`BindOnlyPipeline` remains as the seam's honest null implementation,
used by tests that are about the route rather than about storage. That substitution is the whole
point of the port: persist-before-deliver, idempotent replay, and the storage-down `503` arrive
as one assignment in `create_app` rather than as an edit to the route.

The port's failure mode is declared here too. :class:`StorageUnavailable` lives beside the
Protocol rather than in a `reports/errors.py`, for the same reason plan §2.2 keeps the delivery
error taxonomy inside `delivery/ports.py`: one place to look for "what can this seam do to me".
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..classification.content import Classification
from .schema import BoundedReport

DeliveryState = Literal["pending", "queued", "delivered", "failed"]
"""`queued` is a real state, not the absence of a timestamp: `QueueSink` succeeding is terminal
success, and a retry loop that reads it as "no attempt scheduled" retries every delivered report
six times and then alarms."""


def mint_ref() -> str:
    """A report's public reference. Server-minted, never derived from client input.

    Longer than the spec's illustrative `r_8f21c0`: three bytes collide at a few thousand rows by
    the birthday bound, and this value is a primary key.
    """
    return f"r_{secrets.token_hex(6)}"


def request_fingerprint(payload: Mapping[str, Any]) -> str:
    """A stable digest of the stored payload.

    Written into the `request_fingerprint` COLUMN as a diagnostic and never consulted to resolve a
    replay from it — that is `OME-970`'s lesson and `reports/store.py`'s module docstring states
    it. :func:`scoped_dedup_key` uses the same digest for a different job: not "have we seen this
    content" but "is this the same submission the key claims", which is the opposite direction and
    is only ever a NARROWING of an `Idempotency-Key` that already had to match.

    Deliberately strict about what it will serialize: `payload` came from `json.loads` and a
    truncator that only ever shortens strings, so a value this cannot encode is a bug worth a
    traceback rather than something to stringify quietly into a column.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def scoped_dedup_key(
    scope: str, idempotency_key: str | None, *, unverified_payload: Mapping[str, Any] | None
) -> str | None:
    """What actually goes in the `idempotency_key` column: the client's key, namespaced.

    **An `Idempotency-Key` is a claim, not a credential** — the same rule spec §7 states for
    `trace_id` and `run_id`, and it applies here for the same reason: `POST /v1/reports` is
    unauthenticated, so a client chooses the string and nothing stops it choosing one somebody
    else already chose. Resolving a replay from the raw string across every caller made a key a
    bearer lookup: `Idempotency-Key: 1` from a stranger answered `200` with the previous
    caller's `ref`, and that stranger's own report was never stored. Enumeration in one
    direction, silent suppression in the other.

    **`unverified_payload` is what closes that hole for the caller class `scope` cannot separate,
    and it is required rather than defaulted so no caller can omit it by forgetting.** Pass the
    bounded payload for a caller with no verified identity; pass `None` for a mesh-verified one.
    The scope alone was never enough on the public route: `gate.admit` scopes an anonymous caller
    by `rate_limit_key`, which is the TCP peer — and in the cluster the mesh proxy is the peer on
    every request while `httproute-public.yaml` strips `CF-Connecting-IP` unconditionally, so
    every anonymous caller on earth shares one scope. The bearer lookup survived there in full:
    a guessed key answered `200` carrying somebody else's `ref` and, once a sink files tickets,
    their `ticket.id` and the private issue url beside it; and a key registered ahead of time made
    a real reporter's report replay a stranger's row and never be stored, which is the silent
    report loss spec §8 exists to promise against.

    Mixing the payload digest in binds the replay to something the caller cannot share. Spec §5's
    guarantee is unchanged for the case it is about — a double-click and a client retry both send
    the SAME bytes, so they still resolve to one row and one ticket — while a guessed key from a
    stranger, whose report differs by so much as a trace id, now matches nothing and is stored as
    the new report it is. A mesh-verified caller keeps the plain scope: the mesh verified the
    address, so their key is already theirs, and narrowing it would break the honest case of one
    submitter retrying a corrected report under the key they already used.

    Hashed rather than concatenated so the column stays one unique varchar — `_replay` keeps its
    single-column lookup and no migration to a composite constraint is needed — and so the raw
    client string, which is free text on an unauthenticated request, never lands in the database
    at all. The NUL separator is what stops `("a", "bc")` and `("ab", "c")` sharing a digest.
    """
    if idempotency_key is None:
        return None
    material = f"{scope}\x00{idempotency_key}"
    if unverified_payload is not None:
        material = f"{material}\x00{request_fingerprint(unverified_payload)}"
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Ticket:
    id: str
    url: str


@dataclass(frozen=True, slots=True)
class Submission:
    """The bounded report plus the request facts that are not part of it."""

    bound: BoundedReport
    classification: Classification
    """The server's verdict, decided before this seam (spec §4). Only `envelope` ever reaches a
    pipeline — a `content` verdict is a 422 at the route and is never persisted — but it travels
    as the decided value rather than as a literal, so `OME-1008`'s `classification` column and
    the response echo one source instead of two."""

    dedup_key: str | None
    """:func:`scoped_dedup_key`'s digest, or None when the client sent no `Idempotency-Key`.

    Deliberately NOT the header value: the column is a namespace shared by every caller of an
    unauthenticated endpoint, and the name says which of the two this is. For a caller with no
    verified identity the digest also covers the report itself, so a replay resolves only against
    a byte-identical submission — see :func:`scoped_dedup_key`."""

    caller_email: str | None
    """Mesh-injected identity, or None. Unconditionally None until `OME-1011`, which is the one
    module allowed to read the header it comes from."""


@dataclass(frozen=True, slots=True)
class Accepted:
    """Spec §2.2's one success shape, for both new reports and replays."""

    ref: str
    classification: str
    delivery_state: DeliveryState
    ticket: Ticket | None = None
    replayed: bool = False
    """True for an idempotent replay, which answers `200` rather than `202`."""


class StorageUnavailable(RuntimeError):
    """Nothing was stored, and the caller must be told so (spec §2.3, §8).

    This is the one failure a reporting client has to distinguish from every other: a `503` means
    the report does not exist anywhere, so the client keeps it on disk and retries rather than
    assuming delivery. Raised by a pipeline that could not commit; mapped to
    `storage_unavailable()` at the route, which is the only place that knows about statuses.

    INVARIANT: never raised after a successful commit. A report that was stored and then failed
    to deliver is a `202` with `delivery.state = "pending"` — that is what the retry queue is
    for, and answering `503` there would make a client file the same report twice.
    """


class ReportPipeline(Protocol):
    async def submit(self, submission: Submission) -> Accepted:
        """Persist, dedupe, and (from `OME-1009`) deliver. Raises :class:`StorageUnavailable`."""
        ...


class BindOnlyPipeline:
    """The scaffold pipeline: bounding happened, nothing else has been built yet.

    Nothing installs this any more — `create_app` builds a `StorePipeline` — and it is kept
    rather than deleted because it is the port's null implementation: a route test that is about
    routing, not about storage, has something to put on the seam that needs no database. It is
    NOT a fallback, and `create_app` must never reach for it: a service that answers `202` while
    storing nothing is the exact failure spec §2.3's `503` exists to make visible.
    """

    async def submit(self, submission: Submission) -> Accepted:
        # The verdict is the server's and was decided before this seam, so it is echoed rather
        # than re-invented here. The `ref` is not: it is minted per call, which is exactly the
        # tell that nothing is stored yet — two replays of one `Idempotency-Key` get two refs
        # until `OME-1008` puts a store behind this.
        return Accepted(
            ref=mint_ref(),
            classification=submission.classification,
            delivery_state="pending",
        )
