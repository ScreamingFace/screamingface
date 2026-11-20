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

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ..call_context import current_call_id, current_trace_id
from ..core.auth.middleware import CurrentAccount
from ..core.frozen_copy.headers import STORED_HEADERS_FIELD, MalformedCallKey, parse_call_key
from ..core.frozen_copy.models import STATUS_OPEN, STATUS_SEALED, FrozenCopy
from ..core.frozen_copy.store import (
    FrozenCopySealed,
    frozen_copy_store_for,
    log_capture_failure,
)
from ..core.request_cache.canonical import CanonicalizationError
from ..core.request_hardening import chat_body_shape_error, prepare_ingress_body
from ..plugins.taxonomy import new_gateway_call_id
from ..plugins.taxonomy.entry_metadata import cache_reference_from_captured_aigw
from ..plugins.taxonomy.render import (
    METADATA_KEY,
    attach_metadata,
    merged_error_detail,
    render_aigw_metadata,
)

router = APIRouter()

_REPLAY_HEADER = "X-AIGW-Replay"


class ToolResultRequest(BaseModel):
    description: dict[str, Any]
    result: str


class ToolLookupRequest(BaseModel):
    description: dict[str, Any]


class RouterRevision(BaseModel):
    """One Router of a run manifest (C9): its binding and the revision the run recomputed."""

    model_config = ConfigDict(extra="forbid", strict=True)

    binding: str = Field(pattern=r"^router_[0-9]+$")
    revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


EngineVersion = Annotated[str, Field(min_length=1, max_length=64)]
RouterManifest = Annotated[list[RouterRevision], Field(min_length=1, max_length=256)]


class Provenance(BaseModel):
    """Q28: the engine's version, stored on the copy at seal.

    FEATURE: Router Recipe extension (C9) — a Router capture also seals its run manifest, which a
    replay run reads back through ``read_provenance`` to refuse a changed Router definition.
    INVARIANT: the list is stored as sent; the Engine sorts it and compares it exactly.
    """

    model_config = ConfigDict(extra="forbid")

    engine_version: EngineVersion
    # WHY null is accepted: as for ``SealRequest.provenance``, an explicit null means "none sent".
    routers: RouterManifest | None = None


class ProvenanceRead(BaseModel):
    """The C9 read of a sealed copy's provenance: the version, or null, and the manifest, or [].

    INVARIANT: a closed record, like every C9 record: its schema publishes no other key, and a
    key this model does not list is refused, never dropped.
    """

    model_config = ConfigDict(extra="forbid")

    engine_version: EngineVersion | None
    routers: list[RouterRevision] = Field(max_length=256)


_ENGINE_VERSION: TypeAdapter[str] = TypeAdapter(EngineVersion)
_ROUTER_MANIFEST: TypeAdapter[list[RouterRevision]] = TypeAdapter(RouterManifest)


def _read_stored(stored: object) -> ProvenanceRead:
    """The stored provenance as the seal would have accepted it, field by field.

    INVARIANT: a stored value the seal refuses today is absent, never an error and never raw JSON:
    no engine version reads null, and no valid manifest reads ``[]``, so a replay run with a
    Router meets a manifest mismatch rather than a broken row.
    """
    if not isinstance(stored, dict):
        return ProvenanceRead(engine_version=None, routers=[])
    try:
        version: str | None = _ENGINE_VERSION.validate_python(stored.get("engine_version"))
    except ValidationError:
        version = None
    try:
        routers = _ROUTER_MANIFEST.validate_python(stored.get("routers"))
    except ValidationError:
        routers = []
    return ProvenanceRead(engine_version=version, routers=routers)


class SealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: Provenance | None = None


def _call_key(request: Request) -> tuple[str, int]:
    """The request's call key (Q27). A bad or missing key is a 400, never a fallback."""
    try:
        return parse_call_key(request.headers)
    except MalformedCallKey as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "malformed_call_key",
                "message": f"{exc} is missing or malformed",
            },
        ) from None


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


def _replay_metadata(captured: Any = None) -> dict[str, Any]:
    """The ``_aigw`` block of a replayed answer: a free cache hit, marked as a replay.

    WHY the renderer and not an edit of the captured block: the captured ``_aigw`` describes the
    ORIGINAL call (its attempts and cost). The engine prices a call as $0 only for the shape a
    cache hit renders — ``direct_cost_status: not_applicable`` with ``cache.status: hit`` — so the
    block is rendered by the same function, with no attempts, and then marked.

    FEATURE (E4c ans:Q21b, OME-1291): like any hit, the block carries the original call's price
    as ``cache.reference``, so a budget Gate on replay takes the branch the live run took.
    """
    metadata = render_aigw_metadata(
        trace_id=current_trace_id(),
        collector=None,
        supported=True,
        cache_status="hit",
        gateway_call_id=current_call_id() or new_gateway_call_id(),
        cache_reference=cache_reference_from_captured_aigw(captured),
    )
    metadata["frozen_copy_replay"] = True
    return metadata


@router.post("/v1/frozen-copies/{copy_id}/chat/completions")
async def replay_chat_completions(
    copy_id: str, request: Request, response: Response, current: CurrentAccount
) -> Any:
    case_key, occurrence = _call_key(request)
    copy = await _sealed_copy(request, copy_id)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="request body must be valid JSON") from None
    shape_error = chat_body_shape_error(body)
    if shape_error is not None:
        raise HTTPException(status_code=400, detail=shape_error)
    body, controls = prepare_ingress_body(body)
    try:
        entry = await frozen_copy_store_for(request.app).find(
            copy,
            "chat",
            body,
            attempt=controls.attempt,
            case_key=case_key,
            occurrence=occurrence,
        )
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
            headers={
                **entry.response_json.get(STORED_HEADERS_FIELD, {}),
                _REPLAY_HEADER: "error",
            },
        )
    response.headers[_REPLAY_HEADER] = "hit"
    return attach_metadata(
        entry.response_json, _replay_metadata(entry.response_json.get(METADATA_KEY))
    )


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
    copy_id: UUID, request: Request, current: CurrentAccount, body: SealRequest | None = None
) -> dict[str, Any]:
    provenance = (
        None
        if body is None or body.provenance is None
        # WHY exclude_none: a seal without routers stores exactly what it stored before C9.
        else body.provenance.model_dump(exclude_none=True)
    )
    copy = await frozen_copy_store_for(request.app).seal(copy_id, current.id, provenance)
    if copy is None:
        raise _not_found()
    return {"id": str(copy.id), "status": copy.status, "entries": copy.entries}


@router.get("/v1/frozen-copies/{copy_id}/provenance")
async def read_provenance(
    copy_id: str, request: Request, current: CurrentAccount
) -> ProvenanceRead:
    """The provenance a sealed copy was sealed with (C9).

    INVARIANT: the chat replay route's lookup and caller auth: any authenticated account that may
    replay the copy may read this, and an unknown, open or malformed id is the same 404. It returns
    the provenance alone, never a stored request (design F2).
    """
    copy = await _sealed_copy(request, copy_id)
    return _read_stored(copy.provenance)


@router.post("/v1/frozen-copies/{copy_id}/tool-results")
async def capture_tool_result(
    copy_id: UUID, body: ToolResultRequest, request: Request, current: CurrentAccount
) -> dict[str, str]:
    case_key, occurrence = _call_key(request)
    store = frozen_copy_store_for(request.app)
    # Best effort (design Q18): a store or database failure is `failed` (the engine then marks the
    # run partial), never an error. Ownership and sealed state still answer 404 and 409.
    try:
        copy = await store.get(copy_id)
        if copy is not None and copy.account_id == current.id and copy.status == STATUS_OPEN:
            await store.capture(
                copy,
                "tool",
                body.description,
                {"result": body.result},
                200,
                case_key=case_key,
                occurrence=occurrence,
            )
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
    case_key, occurrence = _call_key(request)
    copy = await _sealed_copy(request, copy_id)
    try:
        entry = await frozen_copy_store_for(request.app).find(
            copy,
            "tool",
            body.description,
            attempt=None,
            case_key=case_key,
            occurrence=occurrence,
        )
    except (CanonicalizationError, UnicodeError):
        entry = None
    if entry is None:
        raise _miss()
    return {"result": entry.response_json["result"]}
