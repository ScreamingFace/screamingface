"""`POST /v1/reports` — the service's only write.

The route does six things and delegates everything else: admit the caller, bound the body,
classify it, read the headers it is allowed to read, hand a :class:`Submission` to the pipeline
on `app.state`, and render spec §2.2's success shape. It holds no storage, no sink, and no
identity logic of its own.

Admission runs **first**, before a byte of the body is looked at. Every one of its refusals is a
status the client has to be able to trust means *nothing was stored* (spec §8), and the cheapest
way to keep that true is for nothing capable of storing to have been reached yet.

Classification sits between binding and the pipeline, and not inside a pipeline: spec §4 rejects
content rather than storing it, and the only structural way to guarantee that is for the refusal
to happen before anything capable of persisting is reached. A classifier called from inside the
store's own pipeline is one edit away from persist-then-classify.

INVARIANT: this module never names the mesh identity header. `caller_email` comes back from
`identity.gate.admit`, which reads it in the one module allowed to and only after the peer check.
A route that read the header itself would trust whatever a client sent, which is the whole
failure this service is built to avoid.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..classification.content import classify_report
from ..core.headers import read_allowed
from ..core.problem_catalogue import content_rejected, malformed_body, storage_unavailable
from ..identity.gate import admit
from ..reports.binding import bind
from ..reports.models import IDEMPOTENCY_KEY_MAX_LENGTH
from ..reports.pipeline import (
    Accepted,
    DeliveryState,
    ReportPipeline,
    StorageUnavailable,
    Submission,
    scoped_dedup_key,
)

router = APIRouter()

_JSON_MEDIA_TYPE = "application/json"

_IDEMPOTENCY_KEY_HEADER = "idempotency-key"


class TicketBody(BaseModel):
    id: str
    url: str


class DeliveryBody(BaseModel):
    state: str
    """`delivered` | `pending` | `failed` — spec §2.2's enum and nothing else. See
    :func:`_wire_state` for why the storage vocabulary is one value wider."""

    ticket: TicketBody | None = None


class SubmissionBody(BaseModel):
    """One shape for both new reports and replays (spec §2.2)."""

    ref: str
    classification: str
    delivery: DeliveryBody


@router.post("/v1/reports", status_code=202, response_model=SubmissionBody)
async def submit_report(request: Request) -> Response:
    admission = await admit(request)
    _require_json(request)
    bound = bind(await request.body())
    # `scanned`, never `payload`: the classifier reads the pre-truncation text, so pushing a
    # prompt past a field's cap is not a way past this check.
    verdict = classify_report(bound.scanned)
    if verdict.detail is not None:
        raise content_rejected(verdict.detail)
    headers = read_allowed(request.headers)
    pipeline: ReportPipeline = request.app.state.report_pipeline
    submission = Submission(
        bound=bound,
        classification=verdict.classification,
        # Scoped to the caller HERE rather than in the store, so the raw header never travels
        # past the one function that has both halves of the pair.
        dedup_key=scoped_dedup_key(admission.dedup_scope, _idempotency_key(headers)),
        caller_email=admission.caller_email,
    )
    try:
        accepted = await pipeline.submit(submission)
    except StorageUnavailable as exc:
        # The status a reporting client has to be able to tell apart from every other: nothing
        # was stored, so it keeps the report on disk and retries rather than assuming delivery.
        # Mapped HERE because the route is the only layer that knows about statuses.
        raise storage_unavailable() from exc
    return JSONResponse(
        _rendered(accepted).model_dump(),
        status_code=200 if accepted.replayed else 202,
    )


def _require_json(request: Request) -> None:
    """`Content-Type: application/json` only — no form encoding, from any client.

    Two reasons, and the second is the security one. In a notebook an HTML `<form>` would
    serialize the report body and any credential into the saved `.ipynb`. And a cross-site form
    POST is not preflighted: `enctype="text/plain"` can be coaxed into producing a JSON-shaped
    body, so a browser holding a live mesh session could be made to file a report as its user.
    Requiring a media type only `fetch` can set means the request is preflighted and the origin
    allowlist gets to answer first.

    `400` rather than `415`, because spec §2.3's table is the contract an SDK codes against and it
    lists no `415`. A new status is a spec amendment, not a route decision.
    """
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != _JSON_MEDIA_TYPE:
        raise malformed_body(
            f"reports must be sent as {_JSON_MEDIA_TYPE}; this request declared "
            f"{media_type or 'no content type'}"
        )


def _idempotency_key(headers: dict[str, str]) -> str | None:
    """The client's replay key, or the catalogued `400` when it cannot fit the column.

    Bounded HERE, not at the INSERT. The column is `varchar(255)`, tortoise's own validator
    raises on a longer value, and every ORM failure leaves the store as `StorageUnavailable` —
    so without this check a 256-character key is answered `503`. Spec §8 tells a client that
    `503` means *keep the report and retry unchanged*, which for a permanent, client-fixable
    input error is an infinite loop that also burns the anonymous rate budget on every pass.

    `400` because spec §2.3's table is the contract an SDK codes against and already carries it;
    a bad header is the same class of thing as the wrong `Content-Type` above.
    """
    key = headers.get(_IDEMPOTENCY_KEY_HEADER)
    if key is not None and len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise malformed_body(
            f"Idempotency-Key is {len(key)} characters; the limit is "
            f"{IDEMPOTENCY_KEY_MAX_LENGTH}. Nothing was stored: shorten the key and retry."
        )
    return key


def _rendered(accepted: Accepted) -> SubmissionBody:
    ticket = accepted.ticket
    return SubmissionBody(
        ref=accepted.ref,
        classification=accepted.classification,
        delivery=DeliveryBody(
            state=_wire_state(accepted.delivery_state),
            ticket=TicketBody(id=ticket.id, url=ticket.url) if ticket is not None else None,
        ),
    )


def _wire_state(state: DeliveryState) -> str:
    """The stored state as spec §2.2's enum spells it — `delivered | pending | failed`.

    `queued` is a STORAGE state and not a wire one (plan §2.3 introduces it as a `delivery_state`
    COLUMN value, so the retry sweep can tell terminal success from an attempt still owed). Spec
    §9 says what the reporter sees for the same row: with `QueueSink` "the reporter gets a `ref`
    but no ticket id, which the success shape already models as `delivery.state: \"pending\"`".

    Both readings are right for their own reader, and this function is where they meet. `QueueSink`
    is the only v1 sink and it always succeeds, so leaking `queued` would put an undocumented
    value on EVERY successful submission — a typed SDK that codes §2.2's enum as a `Literal`, a
    `match`, or an enum parse breaks on the happy path rather than on an edge case.
    """
    return "pending" if state == "queued" else state
