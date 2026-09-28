"""OME-1044 — the Tavily retrieval cache endpoints.

FEATURE: the Runner asks whether this exact retrieval was already answered, and posts
the answer back after paying for it. aigateway holds no Tavily credential and makes no
Tavily call — it only keys and stores.

INVARIANT under test: a miss is a `200` ANSWER, never a `404`. That follows the house
precedent set by `POST /v1/models/admit`: the caller's next move needs the body either
way, so a refusal carries a diagnostic code rather than an HTTP error.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

LOOKUP = "/v1/retrieval/tavily/cache/lookup"
ENTRIES = "/v1/retrieval/tavily/cache/entries"

_SEARCH = {
    "provider": "tavily",
    "tool": "web_search",
    "query": "who runs openmined",
    "search_depth": "advanced",
    "max_results": 5,
    "excluded_domains": [],
}
_RESULT = "Title: OpenMined\nURL: https://openmined.org\nContent: a privacy community"


def _login(client: TestClient) -> TestClient:
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


@pytest.fixture
def cache_client(client: TestClient) -> TestClient:
    """The STOCK app. The lane is unconditional, so no env var turns it on."""
    return _login(client)


# --- the round trip -----------------------------------------------------------


def test_a_cold_key_is_a_miss_then_a_fill_then_a_hit(cache_client: TestClient) -> None:
    miss = cache_client.post(LOOKUP, json=_SEARCH)
    assert miss.status_code == 200, miss.text
    assert miss.json() == {"status": "miss", "reason": None, "result": None}
    assert miss.headers["X-AIGW-Cache"] == "miss"

    fill = cache_client.post(ENTRIES, json={**_SEARCH, "result": _RESULT})
    assert fill.status_code == 200, fill.text
    assert fill.json() == {"outcome": "stored"}

    hit = cache_client.post(LOOKUP, json=_SEARCH)
    assert hit.status_code == 200, hit.text
    assert hit.json() == {"status": "hit", "reason": None, "result": _RESULT}
    assert hit.headers["X-AIGW-Cache"] == "hit"
    # The published key is a PREFIX of the hash — never the whole digest, never content.
    assert len(hit.headers["X-AIGW-Cache-Key"]) == 12
    assert int(hit.headers["Age"]) >= 0


def test_a_second_fill_loses_the_race_and_does_not_overwrite(cache_client: TestClient) -> None:
    cache_client.post(ENTRIES, json={**_SEARCH, "result": "first"})
    second = cache_client.post(ENTRIES, json={**_SEARCH, "result": "second"})
    assert second.status_code == 200
    assert second.json() == {"outcome": "race_lost"}
    hit = cache_client.post(LOOKUP, json=_SEARCH)
    assert hit.json()["result"] == "first"


def test_a_web_fetch_round_trips_on_its_url(cache_client: TestClient) -> None:
    body = {"provider": "tavily", "tool": "web_fetch", "url": "https://example.com/paper"}
    assert cache_client.post(LOOKUP, json=body).json()["status"] == "miss"
    cache_client.post(ENTRIES, json={**body, "result": "# Paper"})
    hit = cache_client.post(LOOKUP, json=body)
    assert hit.json() == {"status": "hit", "reason": None, "result": "# Paper"}


def test_a_url_differing_only_in_host_case_hits_the_same_row(cache_client: TestClient) -> None:
    body = {"provider": "tavily", "tool": "web_fetch", "url": "https://example.com/paper"}
    cache_client.post(ENTRIES, json={**body, "result": "# Paper"})
    equivalent = {**body, "url": "HTTPS://Example.COM/paper#section"}
    assert cache_client.post(LOOKUP, json=equivalent).json()["result"] == "# Paper"


# --- the leakage guard, end to end -------------------------------------------


def test_a_different_exclusion_set_never_reads_the_other_row(cache_client: TestClient) -> None:
    # INVARIANT: a cached hit is an already-formatted string that can no longer be
    # re-filtered, so the key is the ONLY place a benchmark's exclusions can be honoured.
    unrestricted = {**_SEARCH, "excluded_domains": []}
    restricted = {**_SEARCH, "excluded_domains": ["arxiv.org"]}
    cache_client.post(ENTRIES, json={**unrestricted, "result": "leaky"})
    assert cache_client.post(LOOKUP, json=restricted).json()["status"] == "miss"


def test_the_native_tavily_spelling_of_excluded_domains_is_refused(
    cache_client: TestClient,
) -> None:
    # INVARIANT (OME-1044 review F1): the contract field is `excluded_domains`, but
    # Tavily's native spelling is `exclude_domains`. A silently ignored field would key
    # the request WITHOUT the exclusion the caller actually sent — the wrong-hit path
    # that defeats the leakage guard. Extra fields are FORBIDDEN, so the native
    # spelling is a 422 on both endpoints, never a keyed request.
    for endpoint, body in (
        (LOOKUP, {**_SEARCH, "exclude_domains": ["arxiv.org"]}),
        (ENTRIES, {**_SEARCH, "result": _RESULT, "exclude_domains": ["arxiv.org"]}),
    ):
        response = cache_client.post(endpoint, json=body)
        assert response.status_code == 422, response.text
        types = {err["type"] for err in response.json()["detail"]}
        assert "extra_forbidden" in types


def test_an_unknown_field_is_refused(cache_client: TestClient) -> None:
    # INVARIANT (OME-1044 review F1): this is a cache-key endpoint — every
    # output-affecting field must be in the key or rejected. A field this route does
    # not know cannot be keyed, so it must not be silently dropped.
    for endpoint, body in (
        (LOOKUP, {**_SEARCH, "bogus": 1}),
        (ENTRIES, {**_SEARCH, "result": _RESULT, "bogus": 1}),
    ):
        response = cache_client.post(endpoint, json=body)
        assert response.status_code == 422, response.text
        types = {err["type"] for err in response.json()["detail"]}
        assert "extra_forbidden" in types


def test_a_store_failure_is_a_bypass_with_the_rfc_9211_header(
    cache_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: a store failure is a BYPASS, never a miss — reporting a miss would
    # invite a write to a store that just failed to read. The RFC 9211 member carries
    # the published reason as `detail`, which is what the Runner's parser surfaces.
    from aigateway.core.request_cache.store import CacheUnavailable
    from aigateway.core.request_cache.tavily_store import TavilyRetrievalCacheStore

    async def _broken_get(self, key_hash: str) -> None:
        raise CacheUnavailable("test store failure")

    # Patch the CLASS method: the store instance was created in the app lifespan, and
    # a bound lookup at call time picks up the patched method.
    monkeypatch.setattr(TavilyRetrievalCacheStore, "get", _broken_get)
    response = cache_client.post(LOOKUP, json=_SEARCH)
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "bypass", "reason": "cache_unavailable", "result": None}
    assert response.headers["Cache-Status"] == "aigateway; fwd=bypass; detail=cache_unavailable"


# --- the RFC 9211 Cache-Status header (spec §Interface) ----------------------


def test_a_miss_publishes_the_rfc_9211_cache_status_header(cache_client: TestClient) -> None:
    # INVARIANT (spec §Interface): the endpoints emit `Cache-Status` (RFC 9211) PLUS
    # the `X-AIGW-Cache*` fallback triple, so the Runner's parser reads the standard
    # field first. A miss is `fwd=miss` — the cache was consulted and had nothing.
    miss = cache_client.post(LOOKUP, json=_SEARCH)
    assert miss.status_code == 200, miss.text
    assert miss.headers["Cache-Status"] == "aigateway; fwd=miss"
    assert miss.headers["X-AIGW-Cache"] == "miss"


def test_a_hit_publishes_the_rfc_9211_cache_status_header(cache_client: TestClient) -> None:
    # INVARIANT (spec §Interface): a hit is `hit; key="<prefix>"`, and the prefix is the
    # SAME 12-character prefix the legacy header carries — enough to correlate two
    # requests, never the whole digest.
    #
    # INVARIANT: the key is QUOTED. RFC 9211 §2.7 types `key` as a String, and an RFC 8941
    # String is delimited — so the quotes are the parameter's TYPE, not an escaping detail
    # the hex prefix happens not to need. A bare prefix serializes as a Token instead, which
    # a strict consumer reads as a type mismatch rather than as a key (PR #782 review).
    cache_client.post(ENTRIES, json={**_SEARCH, "result": _RESULT})
    hit = cache_client.post(LOOKUP, json=_SEARCH)
    assert hit.status_code == 200, hit.text
    prefix = hit.headers["X-AIGW-Cache-Key"]
    assert hit.headers["Cache-Status"] == f'aigateway; hit; key="{prefix}"'
    assert len(prefix) == 12


def test_the_exclusion_order_does_not_split_one_logical_set(cache_client: TestClient) -> None:
    first = {**_SEARCH, "excluded_domains": ["arxiv.org", "semanticscholar.org"]}
    reordered = {**_SEARCH, "excluded_domains": ["SemanticScholar.org", "arxiv.org"]}
    cache_client.post(ENTRIES, json={**first, "result": _RESULT})
    assert cache_client.post(LOOKUP, json=reordered).json()["result"] == _RESULT


# --- the lane is unconditional ------------------------------------------------


def test_the_lane_serves_with_no_configuration_at_all(cache_client: TestClient) -> None:
    # INVARIANT: UNCONDITIONAL (owner decision). `cache_client` sets no env var and the
    # chart carries no value, so a stock deployment caches retrieval. If a configuration
    # layer ever creeps back in, this stops being a miss and becomes a bypass.
    lookup = cache_client.post(LOOKUP, json=_SEARCH)
    assert lookup.status_code == 200, lookup.text
    assert lookup.json()["status"] == "miss"
    assert "X-AIGW-Cache-Reason" not in lookup.headers

    assert cache_client.post(ENTRIES, json={**_SEARCH, "result": _RESULT}).json() == {
        "outcome": "stored"
    }


# --- authentication -----------------------------------------------------------


def test_the_endpoints_require_an_authenticated_caller(client: TestClient) -> None:
    # Identity gates WHO MAY ASK; it never enters the key.
    assert client.post(LOOKUP, json=_SEARCH).status_code == 401
    assert client.post(ENTRIES, json={**_SEARCH, "result": _RESULT}).status_code == 401


# --- validation refusals ------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({**_SEARCH, "provider": "exa"}, "unknown_provider"),
        ({**_SEARCH, "tool": "web_crawl"}, "unknown_tool"),
        ({**_SEARCH, "query": "   "}, "invalid_target"),
        ({"provider": "tavily", "tool": "web_search", "url": "https://x.test/"}, "invalid_target"),
        ({"provider": "tavily", "tool": "web_fetch", "query": "no url"}, "invalid_target"),
        ({"provider": "tavily", "tool": "web_fetch", "url": "not-a-url"}, "invalid_target"),
        ({**_SEARCH, "max_results": 0}, "invalid_max_results"),
        ({**_SEARCH, "max_results": 101}, "invalid_max_results"),
        ({**_SEARCH, "excluded_domains": ["  "]}, "invalid_excluded_domains"),
    ],
)
def test_a_malformed_description_is_refused_with_a_machine_readable_code(
    cache_client: TestClient, body: dict, code: str
) -> None:
    response = cache_client.post(LOOKUP, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code


def test_an_oversized_result_is_refused(cache_client: TestClient) -> None:
    # WHY a cap: the row is plaintext in a shared table, and an unbounded fill would let
    # one caller grow every deployment's cache without limit.
    response = cache_client.post(ENTRIES, json={**_SEARCH, "result": "x" * (256 * 1024 + 1)})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "result_too_large"


def test_a_fill_without_a_result_is_refused(cache_client: TestClient) -> None:
    response = cache_client.post(ENTRIES, json=_SEARCH)
    assert response.status_code == 422, response.text
