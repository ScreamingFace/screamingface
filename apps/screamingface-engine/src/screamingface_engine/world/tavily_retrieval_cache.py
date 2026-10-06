"""The engine's client for the aigateway Tavily retrieval cache.

FEATURE: OME-1045 — before a Tavily call the engine asks whether this exact retrieval is already
stored, and after a paid, successful call it posts the answer back. Tavily execution and the
Tavily credential stay in the engine; the gateway only keys and stores an opaque string
(route contract: OME-1043).

INVARIANT: a cache failure is a bypass, never an error into the tool loop. The cache may not
become an availability dependency of a run. `asyncio.CancelledError` is not a cache failure and
propagates.

INVARIANT: the Tavily API key is never sent here. A description holds only the arguments that
shape the Tavily request; the gateway derives the key hash from it server-side.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

# The gateway's tool names (`TOOL_WEB_SEARCH` / `TOOL_WEB_FETCH`) and provider; the engine does not
# import aigateway, so the strings are repeated and the route contract keeps them equal.
_PROVIDER = "tavily"
_TOOL_WEB_SEARCH = "web_search"
_TOOL_WEB_FETCH = "web_fetch"

_LOOKUP_PATH = "/v1/retrieval/tavily/cache/lookup"
_FILL_PATH = "/v1/retrieval/tavily/cache/entries"

# WHY its own timeout: the cache is a side lane. A slow gateway must cost seconds, not the 30 s a
# Tavily call may take.
_CACHE_TIMEOUT = httpx.Timeout(5.0)

_LOOKUP_STATUSES = frozenset({"hit", "miss", "bypass"})
_FILL_OUTCOMES = frozenset({"stored", "race_lost", "not_stored"})


@dataclass(frozen=True)
class TavilyLookup:
    """What one cache lookup answered. `headers` are the gateway's response fields, for the
    caller that reads the cache outcome from them."""

    status: Literal["hit", "miss", "bypass"]
    result: str | None
    headers: Mapping[str, str]


def search_description(
    query: str,
    search_depth: str,
    max_results: int,
    excluded_domains: Sequence[str],
) -> dict[str, object]:
    """The `web_search` request as the gateway's description model names it."""
    return {
        "provider": _PROVIDER,
        "tool": _TOOL_WEB_SEARCH,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "excluded_domains": list(excluded_domains),
    }


def fetch_description(url: str, excluded_domains: Sequence[str]) -> dict[str, object]:
    """The `web_fetch` request as the gateway's description model names it."""
    return {
        "provider": _PROVIDER,
        "tool": _TOOL_WEB_FETCH,
        "url": url,
        "excluded_domains": list(excluded_domains),
    }


class TavilyRetrievalCache:
    """Lookup and fill against the aigateway the connector already talks to.

    Holds the connector's aigateway client and the same outgoing headers as the chat calls, so
    there is no new pool, base URL or setting.
    """

    __slots__ = ("_client", "_headers")

    def __init__(self, client: httpx.AsyncClient, headers: Mapping[str, str]) -> None:
        self._client = client
        self._headers = dict(headers)

    async def lookup(self, description: Mapping[str, object]) -> TavilyLookup:
        """Ask for a stored result. Any failure is a `bypass` and the caller calls Tavily."""
        try:
            response = await self._client.post(
                _LOOKUP_PATH,
                headers=self._headers,
                json=description,
                timeout=_CACHE_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or body.get("status") not in _LOOKUP_STATUSES:
                raise ValueError("malformed lookup body")
            if body["status"] != "hit":
                return TavilyLookup(body["status"], None, response.headers)
            result = body.get("result")
            if not isinstance(result, str):
                raise ValueError("a hit carries no result")
            return TavilyLookup("hit", result, response.headers)
        except (httpx.HTTPError, ValueError) as exc:
            # Names the error type only — never the query or a result (OME-990).
            logger.warning("tavily cache lookup failed error=%s", type(exc).__name__)
            return TavilyLookup("bypass", None, {})

    async def fill(self, description: Mapping[str, object], result: str) -> str | None:
        """Store a result just paid for. Returns the gateway outcome, or `None` on any failure."""
        try:
            response = await self._client.post(
                _FILL_PATH,
                headers=self._headers,
                json={**description, "result": result},
                timeout=_CACHE_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
            outcome = body.get("outcome") if isinstance(body, dict) else None
            if outcome not in _FILL_OUTCOMES:
                raise ValueError("malformed fill body")
            return outcome
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("tavily cache fill failed error=%s", type(exc).__name__)
            return None
