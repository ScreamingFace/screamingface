"""SF Engine freeze proxy route backed by AI Gateway (`POST /v1/cache-versions`).

FEATURE: OME-1307 (E14), contract C2a (SDK -> engine, the engine side). The SDK sends the
`trace_id` of a captured run; the Engine forwards it with the caller identity and gives the
gateway's signed receipt back unchanged.

INVARIANT: never log the `trace_id`, the receipt or the identity — only an error class name.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, field_validator

from screamingface_engine import job_env
from screamingface_engine.auth import PROBLEM_MEDIA_TYPE, ProblemException
from screamingface_engine.cache_versions.port import CacheVersionError, CacheVersions
from screamingface_engine.connections.port import Caller
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER, refuse_selector
from url4.streaming.trace import valid_traceparent

logger = logging.getLogger(__name__)

_TRACE_ID = re.compile(r"[0-9a-f]{32}")
_ZERO_TRACE_ID = "0" * 32


class _ProblemRoute(APIRoute):
    """The freeze route's boundary: refuse a stated selector before anything else, then replace
    FastAPI's input-bearing validation errors with a fixed problem."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        route_handler = super().get_route_handler()

        async def problem_route_handler(request: Request) -> Response:
            # INVARIANT (OME-1381): refused BEFORE `route_handler`, so a stated `X-Profile` is
            # answered 400 ahead of any 422 and ahead of the 503 for an unconfigured service.
            refuse_selector(request.headers)
            try:
                return await route_handler(request)
            except RequestValidationError:
                logger.info("cache version freeze request validation failed")
                raise ProblemException(
                    status=422,
                    title="Unprocessable Content",
                    detail="the freeze request is invalid",
                    code="invalid_freeze_request",
                ) from None

        return problem_route_handler


def _declare_x_profile(_x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None) -> None:
    """Document the retired header on the route; `_ProblemRoute` refuses it."""


router = APIRouter(
    tags=["Cache versions"],
    route_class=_ProblemRoute,
    dependencies=[Depends(_declare_x_profile)],
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
    responses: dict[int | str, dict[str, Any]] = {
        status: {
            "description": description,
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status, description in _ERROR_DESCRIPTIONS.items()
    }
    responses[200] = {
        "description": "Idempotent re-freeze: the same receipt as the first freeze.",
        "model": CacheVersionReceiptResponse,
    }
    return responses


def _caller(request: Request) -> Caller:
    # INVARIANT (OME-1381): selector-less. `_ProblemRoute` has already refused a stated
    # `X-Profile`, so the `Caller` built below never carries one.
    # WHY `valid_traceparent` and not the raw header (OME-1119): this value is forwarded to
    # aigateway, and a malformed one is worse than none. Invalid degrades to absent, never to an
    # error.
    return Caller(
        job_env.identity_from_headers(request.headers),
        traceparent=valid_traceparent(request.headers.get("traceparent")),
    )


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


def _mark_private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "X-User-Email"


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
        frozen = await _service(request).freeze(_caller(request), body.trace_id)
    except CacheVersionError as exc:
        logger.info("cache version freeze failed: %s", type(exc).__name__)
        raise ProblemException(
            status=exc.status, title=exc.title, detail=exc.detail, code=exc.code
        ) from exc
    response.status_code = 201 if frozen.created else 200
    _mark_private(response)
    return CacheVersionReceiptResponse(
        receipt=frozen.receipt,
        cache_version_id=frozen.cache_version_id,
        entry_count=frozen.entry_count,
        call_count=frozen.call_count,
        missing_count=frozen.missing_count,
        coverage_status=frozen.coverage_status,
        archive_sha256=frozen.archive_sha256,
    )


__all__ = ["CacheVersionReceiptResponse", "FreezeRequest", "router"]
