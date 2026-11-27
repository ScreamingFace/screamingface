"""Capability discovery for this Engine fleet (C12, Unit 6).

FEATURE: Router Recipe extension, capability gate. ``GET /v1/capabilities`` answers the closed
``engine-capabilities-v1`` document: the capability IDs this fleet can run, as the validated
``Settings.advertised_capabilities`` states them. This release advertises none.
STORY: as the SDK, I read it fresh before a submission that needs a capability, and refuse that
submission before any run exists when an ID I need is absent.

INVARIANT: ``Cache-Control: private, no-store`` and no validator (no ETag, never a 304).
WHY not the conditional read ``/v1/operators`` uses: an ID can be withdrawn, and a cached positive
would let a reader submit work the fleet no longer runs.
INVARIANT: no run token, mint, scheduling or Gateway call. Discovery reads one process setting and
shares ``/v1/operators``' ingress exposure.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from screamingface_engine.config import Settings

router = APIRouter()

_CONTRACT = "engine-capabilities-v1"


@router.get(
    "/v1/capabilities",
    tags=["Catalog"],
    summary="List the capabilities this Engine fleet advertises",
)
async def list_capabilities(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    # INVARIANT (C12): exactly these three keys, and the IDs in lexical order.
    return JSONResponse(
        {
            "object": "engine_capabilities",
            "contract": _CONTRACT,
            "capabilities": sorted(settings.advertised_capabilities),
        },
        headers={"Cache-Control": "private, no-store"},
    )


__all__ = ["router"]
