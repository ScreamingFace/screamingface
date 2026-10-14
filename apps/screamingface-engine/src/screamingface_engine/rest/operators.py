"""Discovery for the installed combine operators (OME-1289 E4a).

FEATURE: ``GET /v1/operators`` lists every operator the combine endpoint can resolve.
STORY: as the SDK, I read the catalog once per session and compile a reducer only from ids this
Engine runs, so an unknown operator is a clear error at compile time, not at run time.

AIDEV-NOTE: the catalog reads ``app.state.operators`` (the ``create_app`` parameter), while the
runner's world factory installs ``BUILTIN_OPERATORS`` on the combine route. They agree because both
default to that one constant; the App parameter is a test-only seam, so an App built with another
registry lists operators the runner does not run. Same conditional-read policy and no auth, like
``GET /v1/benchmarks``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response

from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.rest.conditional import conditional_json_response

router = APIRouter()


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
    return conditional_json_response(
        {"object": "list", "data": _registry(request).describe()}, if_none_match
    )


__all__ = ["router"]
