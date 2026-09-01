"""OME-1044 — ``/v1/retrieval/tavily/cache`` lookup and fill.

FEATURE: the Runner asks whether this exact Tavily retrieval was already answered, and
posts the answer back after paying for it once.

STORY: as a benchmark operator I re-run a web-augmented suite and neither Tavily nor the
model is paid again, because the retrieval result — and therefore the tool-loop
continuation that carries it — keys identically.

INVARIANT: aigateway never calls Tavily and never holds a Tavily credential. The Runner
keeps both; this route only keys and stores an opaque result string.

INVARIANT: a miss is a ``200`` ANSWER carrying a diagnostic status, never a ``404``. Same
reasoning as ``POST /v1/models/admit``: the caller's next move needs the body either way.

INVARIANT: the key is derived HERE, server-side, from the caller's description. A
client-supplied key would let two Runner versions with different normalization silently
split or share rows — the defect OME-777/D2 removed from the chat lane.

INVARIANT: this lane is UNCONDITIONAL (owner decision) — no operator switch, no chart
value, no env var. Retrieval results are always cached. The only bypass is a runtime store
failure, which is degradation rather than configuration.

INVARIANT: ``cache_unavailable`` is the ONLY cache reason this route publishes, and it is
imported rather than spelled, so ``PUBLISHED_CACHE_REASONS`` stays exact. Validation
refusals are ``422`` codes and are a different vocabulary.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..core.auth.middleware import CurrentAccount
from ..core.cache_ports import CACHE_UNAVAILABLE_REASON
from ..core.request_cache.store import CacheUnavailable
from ..core.request_cache.tavily_retrieval import (
    TAVILY_PROVIDER,
    TOOL_WEB_FETCH,
    TOOL_WEB_SEARCH,
    TavilyDescriptionError,
    build_tavily_retrieval_key,
    tavily_retrieval_key,
)
from ..core.request_cache.tavily_store import TavilyRetrievalCacheWrite
from .chat_cache_stage import CACHE_HEADER, KEY_HEADER, KEY_PREFIX_LENGTH, REASON_HEADER

router = APIRouter()

# The RFC 9211 field the spec (OME-1043 §Interface) promises alongside the legacy
# `X-AIGW-Cache*` triple. The Runner's parser reads this field FIRST and falls back to
# the triple, so both must be emitted — the standard field is the contract, the triple
# is the legacy fallback.
CACHE_STATUS_HEADER: Final = "Cache-Status"

# WHY a cap: the row is plaintext in a table shared with the chat lane and has no expiry,
# so an unbounded fill would let one caller grow every deployment's cache without limit.
# 256 KiB sits far above the Runner's own 32 KiB truncation cap, so no legitimate fill
# reaches it — it is a backstop, not a tuning knob.
MAX_RESULT_BYTES: Final = 256 * 1024


class _Description(BaseModel):
    """A retrieval request as the Runner describes it. Never a key, never a credential.

    INVARIANT: extra fields are FORBIDDEN, never ignored. This is a cache-key endpoint:
    every output-affecting field must either be in the key or be rejected. A silently
    ignored field would key a request WITHOUT a policy the caller actually sent — the
    wrong-hit path OME-1044 review F1 reproduced with Tavily's native
    ``exclude_domains`` spelling, which is not a member of this model and must be a
    ``422``, not a keyed request.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    tool: str
    query: str | None = None
    url: str | None = None
    search_depth: str | None = None
    max_results: int | None = None
    excluded_domains: list[str] = Field(default_factory=list)


class _FillRequest(_Description):
    result: str


def _refusal(code: str, message: str) -> HTTPException:
    # The app's own detail shape (`{"code", "message"}`), not RFC 9457 — matching the
    # codebase beats matching the standard here.
    return HTTPException(status_code=422, detail={"code": code, "message": message})


def _target(body: _Description) -> str:
    """The single addressed thing, and a refusal if the tool and the field disagree."""
    if body.tool == TOOL_WEB_SEARCH:
        if body.query is None or body.url is not None:
            raise _refusal("invalid_target", "web_search takes a `query` and no `url`")
        return body.query
    if body.tool == TOOL_WEB_FETCH:
        if body.url is None or body.query is not None:
            raise _refusal("invalid_target", "web_fetch takes a `url` and no `query`")
        return body.url
    raise _refusal("unknown_tool", f"unknown tavily tool: {body.tool!r}")


def _key_hash(body: _Description) -> str:
    """Derive the key server-side, or refuse the description."""
    if body.provider != TAVILY_PROVIDER:
        raise _refusal("unknown_provider", f"unknown retrieval provider: {body.provider!r}")
    target = _target(body)
    try:
        key = build_tavily_retrieval_key(
            tool=body.tool,
            target=target,
            search_depth=body.search_depth,
            max_results=body.max_results,
            excluded_domains=body.excluded_domains,
        )
    except TavilyDescriptionError as exc:
        raise _refusal(exc.code, str(exc)) from exc
    return tavily_retrieval_key(key)


def _cache_status_value(status: str, *, reason: str | None, key_hash: str | None) -> str:
    """The RFC 9211 ``Cache-Status`` member for this lane (spec §Interface).

    hit    → ``aigateway; hit; key=<prefix>``
    miss   → ``aigateway; fwd=miss``
    bypass → ``aigateway; fwd=bypass; detail=<reason>``

    The member name is the cache identity the Runner's parser selects, and every value
    is an RFC 8941 Token (hex prefix, ``fwd``/``detail`` keywords, the published reason
    vocabulary), so nothing needs quoting.
    """
    if status == "hit":
        assert key_hash is not None  # INVARIANT: a hit always publishes its key prefix
        return f"aigateway; hit; key={key_hash[:KEY_PREFIX_LENGTH]}"
    if status == "miss":
        return "aigateway; fwd=miss"
    if reason is not None:
        return f"aigateway; fwd=bypass; detail={reason}"
    return "aigateway; fwd=bypass"


def _publish(
    response: Response,
    status: str,
    *,
    reason: str | None = None,
    key_hash: str | None = None,
    age_seconds: int | None = None,
) -> None:
    """Emit the RFC 9211 ``Cache-Status`` member plus the legacy header triple.

    The Runner's parser reads ``Cache-Status`` FIRST and falls back to the triple, so
    both are emitted: the standard field is the contract, the triple is the legacy
    fallback an older Runner still understands.

    AIDEV-NOTE: the triple constants are imported from `chat_cache_stage` rather than
    respelled — the Runner's `read_cache_outcome` matches these names exactly, and a
    second spelling would read as "no cache information" rather than as an error.
    """
    response.headers[CACHE_STATUS_HEADER] = _cache_status_value(
        status, reason=reason, key_hash=key_hash
    )
    response.headers[CACHE_HEADER] = status
    if reason is not None:
        response.headers[REASON_HEADER] = reason
    if key_hash is not None:
        # A PREFIX only: enough to correlate two requests, never the whole digest.
        response.headers[KEY_HEADER] = key_hash[:KEY_PREFIX_LENGTH]
    if age_seconds is not None:
        response.headers["Age"] = str(age_seconds)


@router.post("/v1/retrieval/tavily/cache/lookup")
async def lookup_tavily_retrieval(
    body: _Description,
    request: Request,
    response: Response,
    _current: CurrentAccount,
) -> dict:
    """Answer whether this exact retrieval is already stored."""
    store = request.app.state.tavily_retrieval_cache_store
    key_hash = _key_hash(body)
    try:
        hit = await store.get(key_hash)
    except CacheUnavailable:
        # INVARIANT: a store failure is a BYPASS, never a miss — reporting a miss would
        # invite a write to a store that just failed to read.
        _publish(response, "bypass", reason=CACHE_UNAVAILABLE_REASON)
        return {"status": "bypass", "reason": CACHE_UNAVAILABLE_REASON, "result": None}

    if hit is None:
        _publish(response, "miss", key_hash=key_hash)
        return {"status": "miss", "reason": None, "result": None}

    _publish(response, "hit", key_hash=key_hash, age_seconds=hit.age_seconds)
    return {"status": "hit", "reason": None, "result": hit.result}


@router.post("/v1/retrieval/tavily/cache/entries")
async def fill_tavily_retrieval(
    body: _FillRequest,
    request: Request,
    _current: CurrentAccount,
) -> dict:
    """Store a result the caller has just paid for. Insert-only; first fill wins.

    WHY ``200`` with an outcome rather than ``201 Location``: the caller already holds the
    value, nothing dereferences a location, and a failed fill must never look like a
    failed request — the Runner logs it and carries on.
    """
    store = request.app.state.tavily_retrieval_cache_store
    if len(body.result.encode("utf-8")) > MAX_RESULT_BYTES:
        raise _refusal("result_too_large", f"result exceeds {MAX_RESULT_BYTES} bytes")

    key_hash = _key_hash(body)
    outcome = await store.set_if_absent(
        TavilyRetrievalCacheWrite(key_hash=key_hash, tool=body.tool, result=body.result)
    )
    return {"outcome": outcome}
