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
import re
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute

from screamingface_engine.auth import ProblemException
from screamingface_engine.community_cache.port import (
    CachePage,
    CachePageRequest,
    CommunityCache,
    CommunityCacheError,
)
from screamingface_engine.rest.gateway_route import caller_from_request, problem_responses
from screamingface_engine.rest.selector import X_PROFILE_PARAMETER, refuse_selector

logger = logging.getLogger(__name__)

# INVARIANT: every answer this route's handler gives is private to its caller — refusals included —
# so a shared cache in front of the Engine never serves one caller's answer to another. Router-level
# answers (a 405 for another method) carry no caller data and are not covered.
_PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Vary": "X-User-Email"}
# RFC 9110 §12.4.2 qvalue: "0" with up to three decimals, or "1" with up to three zeros.
_QVALUE = re.compile(r"0(\.[0-9]{0,3})?|1(\.0{0,3})?")


class _CommunityCacheRoute(APIRoute):
    """The route's boundary: refuse a stated selector before anything else."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        route_handler = super().get_route_handler()

        async def community_cache_route_handler(request: Request) -> Response:
            # INVARIANT (OME-1381): refused BEFORE `route_handler`, so a stated `X-Profile` is
            # answered 400 ahead of the 503 for an unconfigured cache.
            refuse_selector(request.headers, problem_headers=_PRIVATE_HEADERS)
            return await route_handler(request)

        return community_cache_route_handler


router = APIRouter(tags=["Community cache"], route_class=_CommunityCacheRoute)

_ERROR_DESCRIPTIONS = {
    400: "The request states the unsupported `X-Profile` header (`code: x_profile_unsupported`).",
    401: "The caller has no verified identity, or AI Gateway rejected it.",
    406: "The caller accepts neither a gzip nor an unencoded page.",
    422: "A query parameter is invalid.",
    429: "AI Gateway is rate limiting community-cache reads; see Retry-After.",
    502: "AI Gateway returned an unusable response.",
    503: "The community cache or AI Gateway is unavailable.",
    504: "AI Gateway did not respond in time.",
}
_PAGE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "One NDJSON page: a header line, one line per row, a trailer line with `next`."
        ),
        "content": {"application/x-ndjson": {"schema": {"type": "string"}}},
        "headers": {
            "Content-Encoding": {
                "description": "`gzip` when the caller accepted it; absent otherwise.",
                "schema": {"type": "string"},
            },
            "Cache-Control": {"schema": {"type": "string", "example": "private, no-store"}},
            "Vary": {"schema": {"type": "string", "example": "Accept-Encoding, X-User-Email"}},
        },
    }
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


# WHY declared here and not as handler parameters: FastAPI validates typed parameters before the
# handler runs, which would answer an anonymous caller's bad value 422 where the gateway answers
# 401. The values are forwarded raw (`CachePageRequest`); these schemas document the gateway's
# rules for clients without enforcing them on the Engine.
_QUERY_PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "after",
        "in": "query",
        "description": "The `next` cursor of the previous page; absent for the first page.",
        "schema": {"type": "string", "maxLength": 256},
    },
    {
        "name": "limit",
        "in": "query",
        "description": "Rows per page.",
        "schema": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 5000},
    },
    {
        "name": "count",
        "in": "query",
        "description": "Add `remaining`, the rows left from this cursor, to the header line.",
        "schema": {"type": "boolean", "default": False},
    },
    {
        "name": "model",
        "in": "query",
        "description": "Only these models' rows, exactly as the cache names them (repeatable).",
        "schema": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 255}},
        "style": "form",
        "explode": True,
    },
]


def _coding(request: Request) -> str | None:
    """``gzip`` or ``identity``, whichever the caller accepts (gzip first), or None for neither.

    RFC 9110 §12.5.3: codings are case-insensitive, `q=0` refuses one, and `*` stands for every
    coding not listed by name. A malformed weight refuses. Identity is acceptable unless refused
    by name or by `*;q=0`; gzip only when asked for, by name or by `*`.
    """
    weights: dict[str, float] = {}
    for part in request.headers.get("accept-encoding", "").split(","):
        coding, *params = (piece.strip() for piece in part.split(";"))
        if coding:
            weights[coding.lower()] = _weight(params)
    if weights.get("gzip", weights.get("*", 0.0)) > 0:
        return "gzip"
    if weights.get("identity", weights.get("*", 1.0)) > 0:
        return "identity"
    return None


def _weight(params: list[str]) -> float:
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() == "q":
            value = value.strip()
            return float(value) if _QVALUE.fullmatch(value) else 0.0
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
        # INVARIANT: a failed close is logged, never raised — it must not turn a complete body
        # into an error, or replace the stream failure the caller is being told about.
        with anyio.CancelScope(shield=True):
            try:
                await page.aclose()
            except Exception as exc:  # noqa: BLE001 — logged; the stream's outcome stands
                logger.warning("community-cache page failed to close (%s)", type(exc).__name__)


@router.get(
    "/v1/cache/entries",
    summary="Read one page of the community cache",
    description=(
        "Proxies AI Gateway's `GET /v1/cache/entries`: one NDJSON page of the shareable "
        "community request cache (a header line, one line per row, a trailer line with the "
        "next cursor), passed through unchanged and still compressed when gzip was accepted."
    ),
    response_class=StreamingResponse,
    responses={**_PAGE_RESPONSE, **problem_responses(_ERROR_DESCRIPTIONS)},
    openapi_extra={"parameters": _QUERY_PARAMETERS},
)
async def community_cache_entries(
    request: Request,
    _x_profile: Annotated[str | None, X_PROFILE_PARAMETER] = None,
) -> StreamingResponse:
    service = _service(request)
    coding = _coding(request)
    if coding is None:
        raise ProblemException(
            status=406,
            title="Not Acceptable",
            detail="accept gzip or identity",
            headers={**_PRIVATE_HEADERS, "Vary": "Accept-Encoding, X-User-Email"},
        )
    query = request.query_params
    page_request = CachePageRequest(
        after=query.get("after"),
        limit=query.get("limit"),
        count=query.get("count"),
        models=tuple(query.getlist("model")),
        gzip=coding == "gzip",
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
