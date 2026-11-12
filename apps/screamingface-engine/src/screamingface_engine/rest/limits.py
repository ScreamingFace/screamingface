"""The caller's run limits (OME-1314).

FEATURE: ``GET /v1/limits`` returns the per-caller in-flight cap that admission enforces, so the
Client sizes its Candidate fan-out from the Engine and never sends more runs at once than the
Engine admits for the caller (spec 2026-11-10-per-user-parallel-runs D3).

WHY read from the runner: the runner is the component that enforces the cap (the
``CallerLimits`` port below, implemented by the runner adapters); a copy of the setting could
disagree with it. A runner without the port falls back to the setting. Same no-auth policy as
``GET /v1/operators``: the edge authenticates.

WHY a dedicated route and not a Run field: Run records are also returned by run listings, and a
per-caller limit is not a property of one Run.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


@runtime_checkable
class CallerLimits(Protocol):
    """The port: a runner that enforces a per-caller in-flight cap."""

    @property
    def caller_inflight_cap(self) -> int: ...


class CallerLimitsBody(BaseModel):
    """The caller's run limits."""

    caller_inflight_cap: int = Field(
        description="How many runs one caller may have admitted at once. A start beyond it is "
        "refused with 503 and Retry-After.",
        ge=1,
    )


def _caller_inflight_cap(request: Request) -> int:
    runner = getattr(request.app.state, "job_runner", None)
    if isinstance(runner, CallerLimits):
        return runner.caller_inflight_cap
    return request.app.state.settings.run_queue_caller_inflight_cap


@router.get(
    "/v1/limits",
    tags=["Catalog"],
    summary="The caller's run limits",
    response_model=CallerLimitsBody,
)
async def get_limits(request: Request) -> CallerLimitsBody:
    return CallerLimitsBody(caller_inflight_cap=_caller_inflight_cap(request))


__all__ = ["CallerLimits", "CallerLimitsBody", "router"]
