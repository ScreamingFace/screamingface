"""Discovery for the installed combine operators (OME-1289 E4a).

FEATURE: ``GET /v1/operators`` lists every operator the combine endpoint can resolve.
STORY: as the SDK, I read the catalog once per session and compile a reducer only from ids this
Engine runs, so an unknown operator is a clear error at compile time, not at run time.

INVARIANT: the catalog and the endpoint share ONE registry (``app.state.operators``), so a listed
id always resolves. Same conditional-read policy and no auth, like ``GET /v1/benchmarks``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response

from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.rest.conditional import validator_matches

router = APIRouter()

_CACHE_CONTROL = "public, max-age=300, must-revalidate"


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _response(value: object, if_none_match: str | None) -> Response:
    body = _json_bytes(value)
    etag = hashlib.sha256(body).hexdigest()[:32]
    headers = {"ETag": f'"{etag}"', "Cache-Control": _CACHE_CONTROL}
    if validator_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


def _registry(request: Request) -> OperatorRegistry:
    return request.app.state.operators


@router.get(
    "/v1/operators",
    tags=["Catalog"],
    summary="List the installed combine operators",
)
async def list_operators(
    request: Request,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    return _response({"object": "list", "data": _registry(request).describe()}, if_none_match)


__all__ = ["router"]
