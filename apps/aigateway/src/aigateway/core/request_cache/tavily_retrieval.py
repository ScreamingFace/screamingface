"""OME-1043/OME-1044 — the Tavily retrieval cache key.

FEATURE: a repeated Tavily `web_search` / `web_fetch` is answered from one shared row
instead of being paid for again. The second-order win is larger than the Tavily credit:
the tool result is appended to `messages` and the chat cache hashes those verbatim, so a
stable retrieval result is what makes the tool-loop continuation cacheable at all.

STORY: as a benchmark operator I re-run a suite and its web-augmented candidates neither
re-pay Tavily nor re-pay the model, because both halves of the turn now key identically.

INVARIANT: aigateway never calls Tavily and never holds a Tavily credential. The Runner
keeps both. This module only describes and keys a retrieval request.

INVARIANT: identity is structurally absent — no account, profile, auth mode or
credential reaches any signature here. That is what makes one row safe to share.

INVARIANT: `excluded_domains` participates in the key. This is security-critical, not
cosmetic: a cached hit returns an already-formatted result string that can no longer be
re-filtered, so the key is the ONLY place a benchmark's retrieval policy (DRACO excludes
arxiv/semanticscholar) can be honoured. Dropping it would let a row filled by an
unrestricted caller be served to a restricted one.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from .canonical import canonical_digest

__all__ = [
    "MAX_RESULTS_CEILING",
    "MAX_RESULTS_FLOOR",
    "OPERATION",
    "TAVILY_PROVIDER",
    "TAVILY_RETRIEVAL_CONTRACT_REVISION",
    "TAVILY_TOOLS",
    "TOOL_WEB_FETCH",
    "TOOL_WEB_SEARCH",
    "TavilyDescriptionError",
    "TavilyRetrievalCacheKey",
    "build_tavily_retrieval_key",
    "normalize_excluded_domains",
    "normalize_fetch_url",
    "normalize_search_query",
    "tavily_retrieval_key",
]

TAVILY_PROVIDER: Final = "tavily"
TOOL_WEB_SEARCH: Final = "web_search"
TOOL_WEB_FETCH: Final = "web_fetch"
TAVILY_TOOLS: Final = frozenset({TOOL_WEB_SEARCH, TOOL_WEB_FETCH})

# INVARIANT: `operation` is INSIDE the hashed material, so a retrieval key and a chat key
# can never collide even in principle — the two lanes share one table.
OPERATION: Final = "retrieval.tavily"

# INVARIANT: the revision is inside the hashed material too. Bump it whenever the member
# set or any normalization rule below changes, which abandons every row keyed under the
# old rules rather than re-serving them under new semantics.
TAVILY_RETRIEVAL_CONTRACT_REVISION: Final = "aigw-tavily-retrieval-2026-08a"

MAX_RESULTS_FLOOR: Final = 1
MAX_RESULTS_CEILING: Final = 100

_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}


class TavilyDescriptionError(ValueError):
    """A retrieval description cannot be keyed.

    ``code`` is the published refusal code the route returns, so the caller can branch
    on it. It is a ValueError so the individual normalizers stay usable on their own.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TavilyRetrievalCacheKey:
    """The closed set of facts a Tavily retrieval key is computed from.

    AIDEV-NOTE: closed on purpose. Adding a member changes every stored key, so it must
    come with a `TAVILY_RETRIEVAL_CONTRACT_REVISION` bump —
    `test_the_hashed_member_set_is_closed_and_exact` is the tripwire.
    """

    provider: str
    tool: str
    target: str
    search_depth: str | None
    max_results: int | None
    excluded_domains: tuple[str, ...]


def normalize_search_query(raw: str) -> str:
    """A search query, NFC-composed and trimmed, with case preserved.

    WHY case is preserved: prompt-shaped material is hashed as sent, mirroring the chat
    lane's `PROMPT_FIELDS`. Whether a search engine treats case as significant is
    Tavily's business, and folding it here would merge requests the caller wrote
    differently.
    """
    query = unicodedata.normalize("NFC", raw).strip()
    if not query:
        raise TavilyDescriptionError("invalid_target", "a web_search query must not be empty")
    return query


def normalize_fetch_url(raw: str) -> str:
    """A fetch URL reduced to the parts that can change the page served.

    The reviewed rules: lowercase the scheme and host (both case-insensitive per
    RFC 3986), drop a default port and the fragment, and keep the path case and the
    query string.

    WHY `utm_*` is NOT stripped: a query parameter can change the response, and there is
    no way to know from here which ones are inert. Over-normalizing would serve one
    page's content for another's URL, which is far worse than an extra row.
    """
    parsed = urlsplit(raw.strip())
    scheme = parsed.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise TavilyDescriptionError("invalid_target", "a web_fetch url must be http or https")
    if "@" in parsed.netloc:
        # WHY fail closed rather than strip: a URL carrying credentials must not be
        # cached at all, and canonicalizing the userinfo would corrupt it.
        raise TavilyDescriptionError("invalid_target", "a web_fetch url must not carry credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise TavilyDescriptionError(
            "invalid_target", "a web_fetch url has an invalid port"
        ) from exc
    host = (parsed.hostname or "").lower()
    if not host:
        raise TavilyDescriptionError("invalid_target", "a web_fetch url must name a host")
    if ":" in host:
        # An IPv6 literal — `hostname` strips the brackets that make the netloc valid.
        host = f"[{host}]"
    netloc = host if port is None or port == _DEFAULT_PORTS[scheme] else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))


def normalize_excluded_domains(values: Sequence[str]) -> tuple[str, ...]:
    """The exclusion set, lowercased, de-duplicated and sorted.

    INVARIANT: sorted and de-duplicated HERE, so the order a caller happened to send
    cannot split one logical exclusion set across two rows.
    """
    normalized: set[str] = set()
    for value in values:
        domain = value.strip().lower()
        if not domain:
            raise TavilyDescriptionError(
                "invalid_excluded_domains", "an excluded domain must not be blank"
            )
        normalized.add(domain)
    return tuple(sorted(normalized))


def build_tavily_retrieval_key(
    *,
    tool: str,
    target: str,
    search_depth: str | None = None,
    max_results: int | None = None,
    excluded_domains: Sequence[str] = (),
) -> TavilyRetrievalCacheKey:
    """Normalize a caller's description into the closed key DTO.

    INVARIANT: no identity parameter exists on this signature.
    """
    if tool not in TAVILY_TOOLS:
        raise TavilyDescriptionError("unknown_tool", f"unknown tavily tool: {tool!r}")

    if tool == TOOL_WEB_SEARCH:
        normalized_target = normalize_search_query(target)
        if max_results is not None and not (
            MAX_RESULTS_FLOOR <= max_results <= MAX_RESULTS_CEILING
        ):
            raise TavilyDescriptionError(
                "invalid_max_results",
                f"max_results must be between {MAX_RESULTS_FLOOR} and {MAX_RESULTS_CEILING}",
            )
        depth, results = search_depth, max_results
    else:
        normalized_target = normalize_fetch_url(target)
        # INVARIANT: the search-only knobs must not enter a fetch key. They cannot change
        # what a fetch returns, so keying them would abandon every cached fetch the next
        # time someone retunes search.
        depth, results = None, None

    return TavilyRetrievalCacheKey(
        provider=TAVILY_PROVIDER,
        tool=tool,
        target=normalized_target,
        search_depth=depth,
        max_results=results,
        excluded_domains=normalize_excluded_domains(excluded_domains),
    )


def tavily_retrieval_key(key: TavilyRetrievalCacheKey) -> str:
    """The cache-key hash for one Tavily retrieval request."""
    return canonical_digest(
        {
            "schema": TAVILY_RETRIEVAL_CONTRACT_REVISION,
            "operation": OPERATION,
            "provider": key.provider,
            "tool": key.tool,
            "target": key.target,
            "search_depth": key.search_depth,
            "max_results": key.max_results,
            "excluded_domains": list(key.excluded_domains),
        }
    )
