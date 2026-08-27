"""OME-972 U1 — parsing, publishability, and merge halves of live model discovery.

FEATURE: live OpenRouter model discovery — ``/v1/models`` lists what OpenRouter
actually serves now instead of compiled seeds frozen at deploy time.

INVARIANT (fail-closed): a catalog that is malformed, empty, over the publish
cap, or paginated off-policy NEVER yields a partial listing — every such case
raises a sanitized ``DiscoveryError`` so the cache keeps the last good snapshot.
"""

from __future__ import annotations

import pytest

from aigateway.core.parameter_discovery import DiscoveryError
from aigateway.plugins.openrouter_provider.live_models import (
    LIVE_MODELS_DISCOVERY_SOURCE,
    explicit_operator_entries,
    live_listing_entries,
    parse_catalog_page,
    publishable_upstream_ids,
    validate_next_url,
)
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

# ---------------------------------------------------------------- source policy


def test_discovery_source_pins_identity_and_cache_policy() -> None:
    # INVARIANT: the source identity/policy is declared BEFORE any fetch and is
    # what the process-local cache scopes TTLs to — changing it invalidates
    # every stored snapshot, so the exact values are pinned here.
    assert LIVE_MODELS_DISCOVERY_SOURCE.key == "openrouter:models:list"
    assert LIVE_MODELS_DISCOVERY_SOURCE.revision == "openrouter:models:list-v1"
    assert LIVE_MODELS_DISCOVERY_SOURCE.ttl_s == 300.0
    assert LIVE_MODELS_DISCOVERY_SOURCE.stale_ttl_s == 3600.0
    assert LIVE_MODELS_DISCOVERY_SOURCE.failure_ttl_s == 30.0


# ---------------------------------------------------------------- parse_catalog_page


def test_parse_catalog_page_extracts_ids_next_and_total() -> None:
    payload = {
        "data": [
            {"id": "openai/gpt-5", "name": "GPT-5"},
            {"id": "qwen/qwen3-coder"},
        ],
        "links": {"next": "/api/v1/models?output_modalities=text&limit=250&offset=250"},
        "total_count": 412,
    }
    ids, next_url, total = parse_catalog_page(payload)
    assert ids == ("openai/gpt-5", "qwen/qwen3-coder")
    assert next_url == "/api/v1/models?output_modalities=text&limit=250&offset=250"
    assert total == 412


def test_parse_catalog_page_last_page_carries_an_explicit_null_next() -> None:
    # The live envelope always carries both completeness fields; the FINAL page
    # says so with ``links.next = null``, never by omitting the key.
    ids, next_url, total = parse_catalog_page(
        {"data": [{"id": "a/b"}], "links": {"next": None}, "total_count": 1}
    )
    assert ids == ("a/b",)
    assert next_url is None
    assert total == 1


def test_parse_catalog_page_empty_data_is_a_well_formed_page() -> None:
    # WHY not a failure here: an empty PAGE is structurally valid; an empty
    # CATALOG is refused later by ``publishable_upstream_ids``, which is the one
    # place that can distinguish the two.
    ids, next_url, total = parse_catalog_page(
        {"data": [], "links": {"next": None}, "total_count": 0}
    )
    assert ids == ()
    assert next_url is None
    assert total == 0


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "a", "dict"],
        {"data": "not-a-list", "links": {"next": None}, "total_count": 0},
        {"data": {"id": "a/b"}, "links": {"next": None}, "total_count": 1},
        {},
        {"links": {"next": None}, "total_count": 0},
        {"data": [{"id": "a/b"}], "links": {"next": 42}, "total_count": 1},
        # Completeness metadata is REQUIRED, not advisory: without it a page
        # cannot be told apart from a silently truncated one.
        {"data": [{"id": "a/b"}], "total_count": 1},
        {"data": [{"id": "a/b"}], "links": {}, "total_count": 1},
        {"data": [{"id": "a/b"}], "links": "next", "total_count": 1},
        {"data": [{"id": "a/b"}], "links": {"next": None}},
        {"data": [{"id": "a/b"}], "links": {"next": None}, "total_count": "1"},
        {"data": [{"id": "a/b"}], "links": {"next": None}, "total_count": True},
        {"data": [{"id": "a/b"}], "links": {"next": None}, "total_count": 1.0},
        {"data": [{"id": "a/b"}], "links": {"next": None}, "total_count": -1},
        # A malformed ROW is malformed DATA: the page is no longer a trustworthy
        # census of what upstream serves, so the whole refresh fails.
        {"data": [{"id": "a/b"}, {"name": "no-id"}], "links": {"next": None}, "total_count": 2},
        {"data": [{"id": "a/b"}, "bare-string"], "links": {"next": None}, "total_count": 2},
        {"data": [{"id": "a/b"}, {"id": 7}], "links": {"next": None}, "total_count": 2},
        {"data": [{"id": "a/b"}, {"id": None}], "links": {"next": None}, "total_count": 2},
    ],
    ids=[
        "list-envelope",
        "data-string",
        "data-dict",
        "empty-envelope",
        "no-data",
        "non-string-next",
        "no-links",
        "links-without-next",
        "links-not-a-dict",
        "no-total-count",
        "total-count-string",
        "total-count-bool",
        "total-count-float",
        "total-count-negative",
        "row-without-id",
        "row-not-an-object",
        "row-id-not-a-string",
        "row-id-null",
    ],
)
def test_parse_catalog_page_malformed_envelope_or_row_fails_closed(payload: object) -> None:
    # INVARIANT (owner correction, 2026-08-25): NOTHING is skipped and salvaged.
    # A page that cannot be fully parsed can never be cached as a fresh, complete
    # catalog — the last good snapshot must survive instead.
    with pytest.raises(DiscoveryError) as exc:
        parse_catalog_page(payload)
    assert exc.value.reason == "malformed_json"


# ---------------------------------------------------------------- validate_next_url


def test_validate_next_url_accepts_exact_on_policy_relative_next() -> None:
    absolute = validate_next_url(
        "/api/v1/models?output_modalities=text&limit=250&offset=250", expected_offset=250
    )
    assert (
        absolute
        == "https://openrouter.ai/api/v1/models?output_modalities=text&limit=250&offset=250"
    )


def test_validate_next_url_accepts_exact_on_policy_absolute_next() -> None:
    url = "https://openrouter.ai/api/v1/models?output_modalities=text&limit=250&offset=500"
    assert validate_next_url(url, expected_offset=500) == url


@pytest.mark.parametrize(
    ("next_url", "expected_offset"),
    [
        # INVARIANT: a next link is validated BEFORE it is dialed — any deviation
        # from the pinned origin/path/query fails the WHOLE refresh, so a partial
        # or policy-violating chain can never be cached as fresh.
        ("https://evil.example/api/v1/models?output_modalities=text&limit=250&offset=250", 250),
        ("http://openrouter.ai/api/v1/models?output_modalities=text&limit=250&offset=250", 250),
        ("https://openrouter.ai/api/v2/models?output_modalities=text&limit=250&offset=250", 250),
        ("/api/v1/models?output_modalities=text&limit=250&offset=500", 250),
        ("/api/v1/models?limit=250&offset=250", 250),
        ("/api/v1/models?output_modalities=text&limit=500&offset=250", 250),
        ("/api/v1/models?output_modalities=text&limit=250&offset=250&extra=1", 250),
        ("/api/v1/models?output_modalities=text&limit=250&offset=250&offset=250", 250),
        ("/api/v1/models?output_modalities=text&limit=250&offset=250#frag", 250),
        ("/api/v1/models?output_modalities=image&limit=250&offset=250", 250),
    ],
    ids=[
        "foreign-origin",
        "insecure-scheme",
        "wrong-path",
        "wrong-offset",
        "missing-modality",
        "wrong-limit",
        "extra-param",
        "duplicate-offset",
        "fragment",
        "wrong-modality",
    ],
)
def test_validate_next_url_refuses_any_off_policy_next(next_url: str, expected_offset: int) -> None:
    with pytest.raises(DiscoveryError) as exc:
        validate_next_url(next_url, expected_offset=expected_offset)
    assert exc.value.reason == "model_catalog_truncated"


# ---------------------------------------------------------------- publishable_upstream_ids


def test_publishable_keeps_plain_ids_and_drops_variants_and_junk() -> None:
    # INVARIANT: auto-publish admits ONLY plain upstream ids — the same shape
    # predicate the admission route enforces. Colon variants and tilde aliases
    # stay reachable via explicit operator config or direct dispatch, never
    # via automatic listing.
    ids = publishable_upstream_ids(
        [
            "qwen/qwen3-coder",
            "openai/gpt-5",
            "openai/gpt-5",  # duplicate collapses
            "deepseek/deepseek-chat:free",  # colon variant — dropped
            "meta/llama~4",  # tilde alias — dropped
            "not-a-slug",  # no vendor/model shape — dropped
            "vendor/" + "a" * 300,  # over-length — dropped
        ]
    )
    assert ids == ("openai/gpt-5", "qwen/qwen3-coder")


@pytest.mark.parametrize(
    "raw_ids",
    [[], ["deepseek/deepseek-chat:free", "meta/llama~4", "not-a-slug"]],
    ids=["no-rows", "all-filtered"],
)
def test_publishable_empty_result_fails_closed(raw_ids: list[str]) -> None:
    # WHY: an empty catalog is indistinguishable from a broken upstream read —
    # caching it as fresh would evict the entire last-good listing.
    with pytest.raises(DiscoveryError) as exc:
        publishable_upstream_ids(raw_ids)
    assert exc.value.reason == "model_catalog_empty"


def test_publishable_over_publish_cap_fails_never_truncates() -> None:
    too_many = [f"vendor/model-{i}" for i in range(5_001)]
    with pytest.raises(DiscoveryError) as exc:
        publishable_upstream_ids(too_many)
    assert exc.value.reason == "model_catalog_too_large"


def test_publishable_exactly_at_cap_is_allowed() -> None:
    at_cap = [f"vendor/model-{i}" for i in range(5_000)]
    assert len(publishable_upstream_ids(at_cap)) == 5_000


# ---------------------------------------------------------------- operator explicitness


def test_default_constructed_settings_yield_no_operator_entries() -> None:
    # INVARIANT (snapshot-or-fallback): compiled default seeds are the FALLBACK,
    # not operator intent — a healthy snapshot replaces them entirely, so a
    # default-constructed settings object contributes no operator entries.
    assert explicit_operator_entries(OpenRouterPluginSettings(enabled=True)) == ()


def test_constructor_configured_models_are_operator_entries_in_order() -> None:
    settings = OpenRouterPluginSettings(
        enabled=True,
        default_models=[
            "openrouter/deepseek/deepseek-chat-v3.1:free",  # colon variant survives explicitly
            "openrouter/qwen/qwen3-coder",
        ],
    )
    entries = explicit_operator_entries(settings)
    assert [e.model_name for e in entries] == [
        "openrouter/deepseek/deepseek-chat-v3.1:free",
        "openrouter/qwen/qwen3-coder",
    ]
    assert all(e.litellm_params == {"model": e.model_name} for e in entries)


def test_env_configured_models_count_as_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: operators configure via AIGW_OPENROUTER_DEFAULT_MODELS in deployment —
    # env-sourced values land in ``model_fields_set`` exactly like constructor
    # arguments, which is the mechanism that makes explicit config survive a
    # healthy snapshot.
    monkeypatch.setenv("AIGW_OPENROUTER_DEFAULT_MODELS", '["openrouter/qwen/qwen3-coder"]')
    settings = OpenRouterPluginSettings(enabled=True)
    entries = explicit_operator_entries(settings)
    assert [e.model_name for e in entries] == ["openrouter/qwen/qwen3-coder"]


# ---------------------------------------------------------------- live_listing_entries


def test_listing_is_operator_first_then_discovered_without_duplicates() -> None:
    settings = OpenRouterPluginSettings(
        enabled=True,
        default_models=[
            "openrouter/deepseek/deepseek-chat-v3.1:free",
            "openrouter/qwen/qwen3-coder",  # also discovered — listed once, operator-first
        ],
    )
    entries = live_listing_entries(settings, ("openai/gpt-5", "qwen/qwen3-coder"))
    assert [e.model_name for e in entries] == [
        "openrouter/deepseek/deepseek-chat-v3.1:free",
        "openrouter/qwen/qwen3-coder",
        "openrouter/openai/gpt-5",
    ]


def test_listing_without_explicit_config_is_discovered_only() -> None:
    entries = live_listing_entries(
        OpenRouterPluginSettings(enabled=True), ("openai/gpt-5", "qwen/qwen3-coder")
    )
    assert [e.model_name for e in entries] == [
        "openrouter/openai/gpt-5",
        "openrouter/qwen/qwen3-coder",
    ]
    assert all(e.litellm_params == {"model": e.model_name} for e in entries)


def test_the_real_envelope_shape_parses_with_all_its_extra_keys() -> None:
    """STRICT must not mean BRITTLE: unknown keys are upstream's business.

    WHY pinned: a live page (probed 2026-08-25) carries ~14 keys per row —
    ``architecture``, ``pricing``, ``context_length``, ``canonical_slug`` and
    more — and the envelope may grow siblings of ``total_count``. Requiring an
    exact key set would turn any upstream addition into a total listing outage,
    so the parser reads only what it needs and ignores the rest.
    """
    ids, next_url, total = parse_catalog_page(
        {
            "data": [
                {
                    "id": "openai/gpt-5",
                    "canonical_slug": "openai/gpt-5",
                    "name": "GPT-5",
                    "context_length": 400_000,
                    "architecture": {"modality": "text+image->text"},
                    "pricing": {"prompt": "0.00000125"},
                },
            ],
            "links": {"next": None, "prev": None},
            "total_count": 1,
            "some_future_field": {"unread": True},
        }
    )
    assert (ids, next_url, total) == (("openai/gpt-5",), None, 1)
