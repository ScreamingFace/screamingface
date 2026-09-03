"""Readiness, behind one seam.

`/readyz` answers from whatever callable sits at ``app.state.readiness_check``. The scaffold
installs :func:`not_ready`, so a service with no storage wired reports itself unready rather than
reporting a readiness it cannot possibly know. Installing a real probe is one assignment in
``create_app``.

INVARIANT: this module is complete and is not edited again. There is exactly one `/readyz` in
this service. A second registration — say, one added next to a storage module because this one
looked like a stub — is not an error at import time: FastAPI accepts both and serves whichever
was registered first, so the probe silently answers from the wrong place.

The failure body is plain JSON, not `application/problem+json`. A kubelet reads a status code and
nothing else, and the problem catalogue exists for a client that has to decide what to do next —
which a probe never does.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

ReadinessCheck = Callable[[], Awaitable[bool]]
"""What ``app.state.readiness_check`` holds: can this process serve a request right now?"""


async def not_ready() -> bool:
    """The scaffold's fail-closed default, replaced once there is storage to probe."""
    return False


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    check: ReadinessCheck = request.app.state.readiness_check
    if await check():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not ready"}, status_code=503)
