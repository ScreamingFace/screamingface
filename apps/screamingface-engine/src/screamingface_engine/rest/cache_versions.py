"""SF Engine freeze proxy route backed by AI Gateway (`POST /v1/cache-versions`).

FEATURE: OME-1307 (E14), contract C2a (SDK -> engine, the engine side). The SDK sends the
`trace_id` of a captured run; the Engine forwards it with the caller identity and gives the
gateway's signed receipt back unchanged.

INVARIANT: never log the `trace_id`, the receipt or the identity — only an error class name.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator

from screamingface_engine.auth import ProblemException
from screamingface_engine.cache_versions.port import CacheVersionError, CacheVersions
from screamingface_engine.rest.boundary import (
    boundary_route_class,
    caller,
    declare_x_profile,
    mark_private,
    problem_responses,
)

logger = logging.getLogger(__name__)

_TRACE_ID = re.compile(r"[0-9a-f]{32}")
_ZERO_TRACE_ID = "0" * 32


_ProblemRoute = boundary_route_class(
    logger=logger,
    log_message="cache version freeze request validation failed",
    detail="the freeze request is invalid",
    code="invalid_freeze_request",
)


router = APIRouter(
    tags=["Cache versions"],
    route_class=_ProblemRoute,
    dependencies=[Depends(declare_x_profile)],
)


class FreezeRequest(BaseModel):
    """Freeze the calls of one captured run trace as an immutable cache version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str

    @field_validator("trace_id")
    @classmethod
    def _w3c_trace_id(cls, value: str) -> str:
        # WHY: the SDK sends the lowercase hex id it minted; W3C trace-id rules forbid all zeros.
        if _TRACE_ID.fullmatch(value) is None or value == _ZERO_TRACE_ID:
            raise ValueError("trace_id must be 32 lowercase hex characters, not all zeros")
        return value


class CacheVersionReceiptResponse(BaseModel):
    """AI Gateway's signed freeze receipt and the version's counts, relayed unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: str
    cache_version_id: str
    entry_count: int
    call_count: int
    missing_count: int
    coverage_status: Literal["complete", "partial"]
    archive_sha256: str


_ERROR_DESCRIPTIONS = {
    400: ("The request states the unsupported `X-Profile` header (`code: x_profile_unsupported`)."),
    401: "AI Gateway did not accept the caller identity.",
    403: "AI Gateway refused the freeze for this caller.",
    404: "No captured calls exist for this trace (`code: trace_not_captured`).",
    413: "The trace is too large to freeze (`code: cache_version_too_large`).",
    422: "The freeze request is invalid (`code: invalid_freeze_request`).",
    429: "Cache version requests are rate limited.",
    502: "AI Gateway returned an unusable response.",
    503: (
        "Cache versions are not configured on this Engine (`code: cache_versions_unconfigured`), "
        "capture is disabled on AI Gateway (`code: capture_disabled`), or AI Gateway is "
        "unavailable."
    ),
    504: "AI Gateway did not answer the freeze in time.",
}


def _error_responses() -> dict[int | str, dict[str, Any]]:
    responses = problem_responses(_ERROR_DESCRIPTIONS)
    responses[200] = {
        "description": "Idempotent re-freeze: the same receipt as the first freeze.",
        "model": CacheVersionReceiptResponse,
    }
    return responses


def _service(request: Request) -> CacheVersions:
    service = getattr(request.app.state, "cache_versions", None)
    if service is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="cache versions are not configured on this Engine",
            code="cache_versions_unconfigured",
        )
    return service


@router.post(
    "/v1/cache-versions",
    status_code=201,
    summary="Freeze a run's cache version",
    response_model=CacheVersionReceiptResponse,
    responses=_error_responses(),
)
async def freeze_cache_version(
    request: Request, body: FreezeRequest, response: Response
) -> CacheVersionReceiptResponse:
    try:
        frozen = await _service(request).freeze(caller(request), body.trace_id)
    except CacheVersionError as exc:
        logger.info("cache version freeze failed: %s", type(exc).__name__)
        raise ProblemException(
            status=exc.status, title=exc.title, detail=exc.detail, code=exc.code
        ) from exc
    response.status_code = 201 if frozen.created else 200
    mark_private(response)
    return CacheVersionReceiptResponse.model_validate(frozen, from_attributes=True)


__all__ = ["CacheVersionReceiptResponse", "FreezeRequest", "router"]
