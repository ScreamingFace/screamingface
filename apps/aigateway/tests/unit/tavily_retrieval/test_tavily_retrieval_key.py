"""OME-1044 — the Tavily retrieval cache key.

FEATURE: a repeated Tavily `web_search` / `web_fetch` is served from one shared row
instead of being paid for again, which also makes the tool-loop continuation chat call
byte-identical and therefore cacheable in its own right.

INVARIANT under test: the key is a pure function of the request DESCRIPTION, it is
identity-free, and `excluded_domains` participates in it. That last one is
security-critical, not cosmetic — a cached hit returns an already-formatted string that
can no longer be re-filtered, so the key is the only place a benchmark's domain
exclusions can be honoured.
"""

from __future__ import annotations

import hashlib
import inspect
import json

import pytest

from aigateway.core.request_cache.tavily_retrieval import (
    OPERATION,
    TAVILY_PROVIDER,
    TAVILY_RETRIEVAL_CONTRACT_REVISION,
    TOOL_WEB_FETCH,
    TOOL_WEB_SEARCH,
    TavilyRetrievalCacheKey,
    build_tavily_retrieval_key,
    normalize_excluded_domains,
    normalize_fetch_url,
    normalize_search_query,
    tavily_retrieval_key,
)


def _house_form(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _search(
    *,
    tool: str = TOOL_WEB_SEARCH,
    target: str = "who runs openmined",
    search_depth: str | None = "advanced",
    max_results: int | None = 5,
    excluded_domains: tuple[str, ...] = (),
) -> TavilyRetrievalCacheKey:
    """A baseline search key whose members individual tests vary one at a time."""
    return TavilyRetrievalCacheKey(
        provider=TAVILY_PROVIDER,
        tool=tool,
        target=target,
        search_depth=search_depth,
        max_results=max_results,
        excluded_domains=excluded_domains,
    )


# --- the hashed member set ----------------------------------------------------


def test_the_hashed_member_set_is_closed_and_exact() -> None:
    # INVARIANT: this pins the EXACT hashed mapping. Adding, removing or renaming a
    # member changes every stored key, so it must be a deliberate act that also bumps
    # TAVILY_RETRIEVAL_CONTRACT_REVISION — this test is the tripwire.
    key = _search(excluded_domains=("arxiv.org",))
    expected = _house_form(
        {
            "schema": TAVILY_RETRIEVAL_CONTRACT_REVISION,
            "operation": OPERATION,
            "provider": "tavily",
            "tool": "web_search",
            "target": "who runs openmined",
            "search_depth": "advanced",
            "max_results": 5,
            "excluded_domains": ["arxiv.org"],
        }
    )
    assert tavily_retrieval_key(key) == hashlib.sha256(expected.encode("utf-8")).hexdigest()


def test_the_operation_namespaces_this_lane_away_from_the_chat_lane() -> None:
    # INVARIANT: `operation` is inside the hashed material, so a retrieval key and a
    # chat key can never collide even in principle.
    assert OPERATION == "retrieval.tavily"
    assert OPERATION != "chat.completions"


def test_the_key_builder_accepts_no_identity_profile_or_credential_input() -> None:
    # INVARIANT: identity is structurally absent — that is what makes one row safe to
    # share across accounts.
    names = set(inspect.signature(build_tavily_retrieval_key).parameters)
    forbidden = {"account", "account_id", "profile", "auth_mode", "credential", "api_key", "user"}
    assert names & forbidden == set()


# --- discrimination: what must NOT share a row --------------------------------


def test_two_different_exclusion_sets_never_share_a_row() -> None:
    # THE leakage guard. Without `excluded_domains` in the key, a row filled by an
    # unrestricted caller would be served to a DRACO run whose policy excludes arxiv,
    # and the cache would silently defeat that control.
    unrestricted = tavily_retrieval_key(_search(excluded_domains=()))
    restricted = tavily_retrieval_key(_search(excluded_domains=("arxiv.org",)))
    wider = tavily_retrieval_key(_search(excluded_domains=("arxiv.org", "semanticscholar.org")))
    assert len({unrestricted, restricted, wider}) == 3


def test_max_results_and_search_depth_each_discriminate() -> None:
    baseline = tavily_retrieval_key(_search())
    assert tavily_retrieval_key(_search(max_results=10)) != baseline
    assert tavily_retrieval_key(_search(search_depth="basic")) != baseline


def test_the_tool_discriminates_for_one_target() -> None:
    target = "https://example.com/paper"
    searched = tavily_retrieval_key(_search(tool=TOOL_WEB_SEARCH, target=target))
    fetched = tavily_retrieval_key(
        TavilyRetrievalCacheKey(
            provider=TAVILY_PROVIDER,
            tool=TOOL_WEB_FETCH,
            target=target,
            search_depth=None,
            max_results=None,
            excluded_domains=(),
        )
    )
    assert searched != fetched


def test_query_case_is_preserved_so_it_discriminates() -> None:
    # WHY verbatim: prompt-shaped material is hashed as sent, mirroring the chat lane.
    # Whether a search engine is case-insensitive is Tavily's business, not ours.
    assert tavily_retrieval_key(_search(target="OpenMined")) != tavily_retrieval_key(
        _search(target="openmined")
    )


# --- normalization: the reviewed rules ----------------------------------------


def test_a_search_query_is_stripped_and_nfc_normalized() -> None:
    assert normalize_search_query("  hello  ") == "hello"
    # NFC folds a combining sequence onto its composed form, so the same text typed two
    # ways is one row rather than two.
    assert normalize_search_query("cafe\u0301") == normalize_search_query("caf\u00e9")


def test_an_empty_search_query_is_refused() -> None:
    with pytest.raises(ValueError):
        normalize_search_query("   ")


def test_a_fetch_url_lowercases_scheme_and_host_but_keeps_path_case() -> None:
    assert normalize_fetch_url("HTTPS://Example.COM/Path/To") == "https://example.com/Path/To"


def test_a_fetch_url_drops_a_default_port_and_keeps_a_custom_one() -> None:
    assert normalize_fetch_url("https://example.com:443/x") == "https://example.com/x"
    assert normalize_fetch_url("http://example.com:80/x") == "http://example.com/x"
    assert normalize_fetch_url("https://example.com:8443/x") == "https://example.com:8443/x"


def test_a_fetch_url_drops_the_fragment_and_keeps_the_query() -> None:
    # WHY: a fragment is never sent to the server, so it cannot change the page. The
    # query string can, so it stays — including `utm_*`, which v1 deliberately does NOT
    # strip: over-normalizing risks serving a DIFFERENT page's content.
    assert normalize_fetch_url("https://example.com/x#section") == "https://example.com/x"
    assert (
        normalize_fetch_url("https://example.com/x?utm_source=a&b=c")
        == "https://example.com/x?utm_source=a&b=c"
    )


def test_a_fetch_url_without_a_scheme_or_host_is_refused() -> None:
    with pytest.raises(ValueError):
        normalize_fetch_url("example.com/x")
    with pytest.raises(ValueError):
        normalize_fetch_url("https:///x")


def test_a_fetch_url_carrying_credentials_is_refused() -> None:
    # WHY fail closed rather than strip: a URL with embedded credentials must not be
    # cached at all, and lowercasing the userinfo to canonicalize it would corrupt it.
    with pytest.raises(ValueError):
        normalize_fetch_url("https://user:secret@example.com/x")


def test_excluded_domains_are_lowercased_deduped_and_sorted() -> None:
    # INVARIANT: sorted + deduped HERE, so the caller's ordering cannot split one
    # logical exclusion set across two rows.
    assert normalize_excluded_domains(["B.com", "a.com", "b.com ", "A.COM"]) == (
        "a.com",
        "b.com",
    )
    assert normalize_excluded_domains([]) == ()


def test_a_blank_excluded_domain_is_refused() -> None:
    with pytest.raises(ValueError):
        normalize_excluded_domains(["a.com", "  "])


# --- the builder ties normalization to the DTO --------------------------------


def test_the_builder_normalizes_before_keying() -> None:
    messy = build_tavily_retrieval_key(
        tool=TOOL_WEB_SEARCH,
        target="  who runs openmined  ",
        search_depth="advanced",
        max_results=5,
        excluded_domains=["B.com", "a.com"],
    )
    tidy = build_tavily_retrieval_key(
        tool=TOOL_WEB_SEARCH,
        target="who runs openmined",
        search_depth="advanced",
        max_results=5,
        excluded_domains=["a.com", "b.com"],
    )
    assert tavily_retrieval_key(messy) == tavily_retrieval_key(tidy)


def test_the_builder_drops_search_only_fields_for_a_fetch() -> None:
    # INVARIANT: `search_depth` and `max_results` are meaningless for `web_fetch`, so
    # they must not enter its key — otherwise an unrelated search-tuning change would
    # abandon every cached fetch.
    key = build_tavily_retrieval_key(
        tool=TOOL_WEB_FETCH,
        target="https://example.com/x",
        search_depth="advanced",
        max_results=5,
        excluded_domains=[],
    )
    assert key.search_depth is None
    assert key.max_results is None
