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

from aigateway.call_context import current_call_id, current_trace_id
from aigateway.core.auth.middleware import CurrentAccount
from aigateway.core.frozen_copy.models import STATUS_SEALED, FrozenCopy
from aigateway.core.frozen_copy.store import FrozenCopyStore
from aigateway.core.request_cache.canonical import CanonicalizationError
from aigateway.core.request_hardening import chat_body_shape_error
from aigateway.plugins.taxonomy import new_gateway_call_id
from aigateway.plugins.taxonomy.render import attach_metadata, render_aigw_metadata

from .chat import prepare_ingress_body

router = APIRouter()

_OCCURRENCE_HEADER = "X-AIGW-Replay-Occurrence"
_REPLAY_HEADER = "X-AIGW-Replay"
_MAX_OCCURRENCE_DIGITS = 18


def _store(request: Request) -> FrozenCopyStore:
    return FrozenCopyStore(max_entry_bytes=request.app.state.settings.frozen_copy_max_entry_bytes)


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


async def _sealed_copy(request: Request, copy_id: UUID) -> FrozenCopy:
    copy = await _store(request).get(copy_id)
    if copy is None or copy.status != STATUS_SEALED:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "frozen_copy_unavailable",
                "message": "the frozen copy does not exist or is not sealed",
            },
        )
    return copy


def _zero_cost(body: dict[str, Any]) -> dict[str, Any]:
    """The captured body with ``_aigw`` replaced by the block of a free cache hit.

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
    return attach_metadata(body, metadata)


@router.post("/v1/frozen-copies/{copy_id}/chat/completions")
async def replay_chat_completions(
    copy_id: UUID, request: Request, response: Response, current: CurrentAccount
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
        entry = await _store(request).find(copy, "chat", body, occurrence)
    except (CanonicalizationError, UnicodeError):
        # A request that cannot be digested was never captured (the capture would have failed).
        entry = None
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "frozen_copy_miss",
                "message": "the frozen copy holds no answer for this request",
            },
        )
    if entry.status_code != 200:
        raise HTTPException(
            status_code=entry.status_code,
            detail=entry.response_json["detail"],
            headers={_REPLAY_HEADER: "error"},
        )
    response.headers[_REPLAY_HEADER] = "hit"
    return _zero_cost(entry.response_json)
