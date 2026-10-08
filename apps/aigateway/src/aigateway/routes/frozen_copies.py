"""Frozen-copy replay and management routes (OME-1307, design §4.3 and §4.4).

A replay answers from a SEALED copy and from nothing else. INVARIANT: the replay routes resolve no
credential, call no provider and no plugin, validate no model and read or write no cache — a replay
must keep working after a model is retired or a provider plugin is removed. The only collaborators
are the frozen-copy store and the shared ingress preparation, so the digest of a replayed request
is the digest the capture took.

Replay is open to any authenticated account that holds the copy id and sends the exact request
(design Q16). No route here lists or reads back a stored request (design F2).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..call_context import current_call_id, current_trace_id
from ..core.auth.middleware import CurrentAccount
from ..core.frozen_copy.models import STATUS_OPEN, STATUS_SEALED, FrozenCopy
from ..core.frozen_copy.store import (
    FrozenCopySealed,
    frozen_copy_store_for,
    log_capture_failure,
)
from ..core.request_cache.canonical import CanonicalizationError
from ..core.request_hardening import chat_body_shape_error, prepare_ingress_body
from ..plugins.taxonomy import new_gateway_call_id
from ..plugins.taxonomy.render import attach_metadata, merged_error_detail, render_aigw_metadata

router = APIRouter()

_OCCURRENCE_HEADER = "X-AIGW-Replay-Occurrence"
_REPLAY_HEADER = "X-AIGW-Replay"
_MAX_OCCURRENCE_DIGITS = 18


class ToolResultRequest(BaseModel):
    description: dict[str, Any]
    result: str


class ToolLookupRequest(BaseModel):
    description: dict[str, Any]


def _occurrence(request: Request) -> int:
    raw = request.headers.get(_OCCURRENCE_HEADER)
    if raw is None:
        return 0
    if not (raw.isascii() and raw.isdecimal() and len(raw) <= _MAX_OCCURRENCE_DIGITS):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "malformed_replay_occurrence",
                "message": f"{_OCCURRENCE_HEADER} must be a non-negative integer",
            },
        )
    return int(raw)


def _miss() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "frozen_copy_miss",
            "message": "the frozen copy holds no answer for this request",
        },
    )


async def _sealed_copy(request: Request, raw_copy_id: str) -> FrozenCopy:
    """The sealed copy, or the one 404 for unknown, open and malformed ids alike."""
    unavailable = HTTPException(
        status_code=404,
        detail={
            "code": "frozen_copy_unavailable",
            "message": "the frozen copy does not exist or is not sealed",
        },
    )
    try:
        copy_id = UUID(raw_copy_id)
    except ValueError:
        raise unavailable from None
    copy = await frozen_copy_store_for(request.app).get(copy_id)
    if copy is None or copy.status != STATUS_SEALED:
        raise unavailable
    return copy


def _replay_metadata() -> dict[str, Any]:
    """The ``_aigw`` block of a replayed answer: a free cache hit, marked as a replay.

    WHY the renderer and not an edit of the captured block: the captured ``_aigw`` describes the
    ORIGINAL call (its attempts and cost). The engine prices a call as $0 only for the shape a
    cache hit renders — ``direct_cost_status: not_applicable`` with ``cache.status: hit`` — so the
    block is rendered by the same function, with no attempts, and then marked.
    """
    metadata = render_aigw_metadata(
        trace_id=current_trace_id(),
        collector=None,
        supported=True,
        cache_status="hit",
        gateway_call_id=current_call_id() or new_gateway_call_id(),
    )
    metadata["frozen_copy_replay"] = True
    return metadata


@router.post("/v1/frozen-copies/{copy_id}/chat/completions")
async def replay_chat_completions(
    copy_id: str, request: Request, response: Response, current: CurrentAccount
) -> Any:
    occurrence = _occurrence(request)
    copy = await _sealed_copy(request, copy_id)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="request body must be valid JSON") from None
    shape_error = chat_body_shape_error(body)
    if shape_error is not None:
        raise HTTPException(status_code=400, detail=shape_error)
    body, _ = prepare_ingress_body(body)
    try:
        entry = await frozen_copy_store_for(request.app).find(copy, "chat", body, occurrence)
    except (CanonicalizationError, UnicodeError):
        # A request that cannot be digested was never captured (the capture would have failed).
        entry = None
    if entry is None:
        raise _miss()
    if entry.status_code != 200:
        # The body shape of a live error: `detail` with `_aigw` beside it (see
        # `main._accounted_http_exception`), here the zero-cost replay block.
        return JSONResponse(
            status_code=entry.status_code,
            content=merged_error_detail(entry.response_json["detail"], _replay_metadata()),
            headers={_REPLAY_HEADER: "error"},
        )
    response.headers[_REPLAY_HEADER] = "hit"
    return attach_metadata(entry.response_json, _replay_metadata())


@router.post("/v1/frozen-copies", status_code=201)
async def open_frozen_copy(request: Request, current: CurrentAccount) -> dict[str, str]:
    copy = await frozen_copy_store_for(request.app).open(current.id)
    return {"id": str(copy.id), "status": copy.status}


def _not_found() -> HTTPException:
    # INVARIANT: an unknown copy and another account's copy answer identically, so a caller
    # cannot learn that a copy id exists.
    return HTTPException(
        status_code=404,
        detail={"code": "frozen_copy_not_found", "message": "no such frozen copy"},
    )


def _sealed() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "frozen_copy_sealed", "message": "the frozen copy is sealed"},
    )


@router.post("/v1/frozen-copies/{copy_id}/seal")
async def seal_frozen_copy(
    copy_id: UUID, request: Request, current: CurrentAccount
) -> dict[str, Any]:
    copy = await frozen_copy_store_for(request.app).seal(copy_id, current.id)
    if copy is None:
        raise _not_found()
    return {"id": str(copy.id), "status": copy.status, "entries": copy.entries}


@router.post("/v1/frozen-copies/{copy_id}/tool-results")
async def capture_tool_result(
    copy_id: UUID, body: ToolResultRequest, request: Request, current: CurrentAccount
) -> dict[str, str]:
    store = frozen_copy_store_for(request.app)
    # Best effort (design Q18): a store or database failure is `failed` (the engine then marks the
    # run partial), never an error. Ownership and sealed state still answer 404 and 409.
    try:
        copy = await store.get(copy_id)
        if copy is not None and copy.account_id == current.id and copy.status == STATUS_OPEN:
            await store.capture(copy, "tool", body.description, {"result": body.result}, 200)
    except FrozenCopySealed:
        raise _sealed() from None
    except Exception as exc:
        log_capture_failure("tool", exc, copy_id=copy_id, request=body.description)
        return {"outcome": "failed"}
    if copy is None or copy.account_id != current.id:
        raise _not_found()
    if copy.status != STATUS_OPEN:
        raise _sealed()
    return {"outcome": "stored"}


@router.post("/v1/frozen-copies/{copy_id}/tool-results/lookup")
async def look_up_tool_result(
    copy_id: str, body: ToolLookupRequest, request: Request, current: CurrentAccount
) -> dict[str, str]:
    occurrence = _occurrence(request)
    copy = await _sealed_copy(request, copy_id)
    try:
        entry = await frozen_copy_store_for(request.app).find(
            copy, "tool", body.description, occurrence
        )
    except (CanonicalizationError, UnicodeError):
        entry = None
    if entry is None:
        raise _miss()
    return {"result": entry.response_json["result"]}
