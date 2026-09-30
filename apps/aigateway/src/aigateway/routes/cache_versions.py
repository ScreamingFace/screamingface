"""``POST /v1/cache-versions``: freeze a traced run (OME-1307, GW-freeze; contract C2b).

FEATURE: OME-1307 (E14) - the caller sends a trace id and gets a signed receipt for the frozen
version of that run.

INVARIANT: imports the ``core.cache_versions`` ports only. Never a model, never an adapter.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..core.auth.middleware import CurrentAccount
from ..core.cache_versions import CacheVersionFreezer, CacheVersionTooLarge, TraceNotCaptured

router = APIRouter()


class FreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class FreezeResponse(BaseModel):
    receipt: str
    cache_version_id: UUID
    entry_count: int
    call_count: int
    missing_count: int
    coverage_status: Literal["complete", "partial"]
    archive_sha256: str


@router.post("/v1/cache-versions", response_model=FreezeResponse, status_code=201)
async def freeze_cache_version(
    body: FreezeRequest, request: Request, response: Response, current: CurrentAccount
) -> FreezeResponse:
    freezer: CacheVersionFreezer | None = getattr(request.app.state, "cache_version_freezer", None)
    if not request.app.state.settings.cache_versions_enabled or freezer is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "capture_disabled",
                "message": "cache versions are disabled on this gateway",
            },
        )
    try:
        result = await freezer.freeze(
            account_id=str(current.id), subject=current.username, trace_id=body.trace_id
        )
    except TraceNotCaptured:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "trace_not_captured",
                "message": "no captured calls for this trace on this account",
            },
        ) from None
    except CacheVersionTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "cache_version_too_large",
                "limit": exc.limit,
                "message": "the trace is too large to freeze as one cache version",
            },
        ) from None
    if not result.created:
        response.status_code = 200
    return FreezeResponse(
        receipt=result.receipt,
        cache_version_id=result.version_id,
        entry_count=result.entry_count,
        call_count=result.call_count,
        missing_count=result.missing_count,
        coverage_status=result.coverage_status,
        archive_sha256=result.archive_sha256,
    )
