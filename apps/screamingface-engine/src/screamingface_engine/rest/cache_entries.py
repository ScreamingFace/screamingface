"""``GET /v1/cache/entries``: the community cache, proxied to the gateway (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, I page through the hosted community cache via the
hosted Engine, which is the only door to the gateway that has one.

The gateway owns the contract (NDJSON pages, the cursor, validation, who may read); this route
forwards the caller and streams the page back unchanged. Authentication is the gateway's: it
answers 401 to a caller without a verified identity, and that answer is passed through.

INVARIANT: the page is never decoded or held. A gzip page is passed through still compressed,
with its ``Content-Encoding``, one upstream chunk at a time.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute

from screamingface_engine.auth import ProblemException
from screamingface_engine.community_cache.port import (
    CachePage,
    CachePageRequest,
    CommunityCache,
    CommunityCacheError,
    CommunityCacheInvalidRequest,
)
from screamingface_engine.rest.gateway_route import caller_from_request, problem_responses
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER, refuse_selector

logger = logging.getLogger(__name__)

# INVARIANT: every answer this route gives is private to its caller — refusals included — so a
# shared cache in front of the Engine never serves one caller's answer to another.
_PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Vary": "X-User-Email"}


class _CommunityCacheRoute(APIRoute):
    """The route's boundary: refuse a stated selector before anything else, then turn FastAPI's
    input-echoing validation errors into the documented problem+json 422, private like every
    other answer."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        route_handler = super().get_route_handler()

        async def community_cache_route_handler(request: Request) -> Response:
            # INVARIANT (OME-1381): refused BEFORE `route_handler`, so a stated `X-Profile` is
            # answered 400 ahead of any 422 and of the 503 for an unconfigured cache.
            refuse_selector(request.headers, problem_headers=_PRIVATE_HEADERS)
            try:
                return await route_handler(request)
            except RequestValidationError:
                logger.info("community-cache page request validation failed")
                raise ProblemException(
                    status=422,
                    title="Unprocessable Content",
                    detail=CommunityCacheInvalidRequest.detail,
                    headers=_PRIVATE_HEADERS,
                ) from None

        return community_cache_route_handler


router = APIRouter(tags=["Community cache"], route_class=_CommunityCacheRoute)

_ERROR_DESCRIPTIONS = {
    400: "The request states the unsupported `X-Profile` header (`code: x_profile_unsupported`).",
    401: "The caller has no verified identity, or AI Gateway rejected it.",
    422: "A query parameter is invalid.",
    429: "AI Gateway is rate limiting community-cache reads; see Retry-After.",
    502: "AI Gateway returned an unusable response.",
    503: "The community cache or AI Gateway is unavailable.",
    504: "AI Gateway did not respond in time.",
}


def _service(request: Request) -> CommunityCache:
    service = getattr(request.app.state, "community_cache", None)
    if service is None:
        raise ProblemException(
            status=503,
            title="Service Unavailable",
            detail="the community cache is not configured on this Engine",
            headers=_PRIVATE_HEADERS,
        )
    return service


def _accepts_gzip(request: Request) -> bool:
    # RFC 9110 §12.5.3: codings are case-insensitive, `q=0` refuses one, and `*` stands for
    # every coding not listed by name. A malformed weight refuses, so the safe answer is identity.
    weights: dict[str, float] = {}
    for part in request.headers.get("accept-encoding", "").split(","):
        coding, *params = (piece.strip() for piece in part.split(";"))
        if coding:
            weights[coding.lower()] = _weight(params)
    return weights.get("gzip", weights.get("*", 0.0)) > 0


def _weight(params: list[str]) -> float:
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() == "q":
            try:
                return float(value.strip())
            except ValueError:
                return 0.0
    return 1.0


async def _body(page: CachePage) -> AsyncIterator[bytes]:
    # INVARIANT: the upstream response is closed however the stream ends — finished, failed,
    # or abandoned by a client that went away (the generator is closed then).
    try:
        async for chunk in page.aiter_raw():
            yield chunk
    except CommunityCacheError as exc:
        # WHY re-raise: the 200 is already sent, so aborting the connection is the only way the
        # caller's HTTP client can tell the page is incomplete; a clean end would hide it.
        logger.warning("community-cache page failed mid-stream: %s", type(exc).__name__)
        raise
    finally:
        # WHY shielded: on a disconnect Starlette cancels the stream's task group, and anyio
        # would cancel this close too, leaking the upstream connection back into the pool.
        with anyio.CancelScope(shield=True):
            await page.aclose()


@router.get(
    "/v1/cache/entries",
    summary="Read one page of the community cache",
    description=(
        "Proxies AI Gateway's `GET /v1/cache/entries`: one NDJSON page of the shareable "
        "community request cache (a header line, one line per row, a trailer line with the "
        "next cursor), passed through unchanged and still compressed when gzip was accepted."
    ),
    response_class=StreamingResponse,
    responses=problem_responses(_ERROR_DESCRIPTIONS),
)
async def community_cache_entries(
    request: Request,
    after: str | None = None,
    limit: int | None = None,
    count: bool = False,
    model: Annotated[list[str], Query()] = [],  # noqa: B006 — FastAPI copies defaults
    _x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None,
) -> StreamingResponse:
    service = _service(request)
    page_request = CachePageRequest(
        after=after, limit=limit, count=count, models=tuple(model), gzip=_accepts_gzip(request)
    )
    try:
        page = await service.open_page(caller_from_request(request), page_request)
    except CommunityCacheError as exc:
        logger.info("community-cache page request failed: %s", type(exc).__name__)
        headers = dict(_PRIVATE_HEADERS)
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        raise ProblemException(
            status=exc.status, title=exc.title, detail=exc.detail, headers=headers
        ) from exc
    # Only the page's body differs by encoding, so only the page varies on it.
    headers = {**_PRIVATE_HEADERS, "Vary": "Accept-Encoding, X-User-Email"}
    if page.content_encoding:
        headers["Content-Encoding"] = page.content_encoding
    return StreamingResponse(_body(page), media_type=page.content_type, headers=headers)


__all__ = ["router"]
