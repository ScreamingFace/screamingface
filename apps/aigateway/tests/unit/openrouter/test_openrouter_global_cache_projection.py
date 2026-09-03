"""OME-305 U3 — OpenRouter's own projection for the global exact-request cache.

FEATURE: a globally shared exact-request cache that OpenRouter requests can actually
enter. Under v1 they could not: ``prepare_chat_body`` pins an API base and rebuilds the
``provider`` object, and a key builder that INSPECTS the prepared body cannot tell a
reviewed rewrite from an unreviewed one, so every OpenRouter call bypassed. The provider
now PROJECTS its preparation instead — a pure function of the request body — and the
fingerprint is computed from what will be sent.

STORY: as a benchmark operator I run the same OpenRouter suite from a second account and
the identical calls are answered from the first run's stored responses, without a second
dispatch and without touching the second account's key.

INVARIANT under test: the projection is PURE and TOTAL. No I/O, no credential, no
identity, no clock; it never mutates the caller's body; and a request this plugin would
refuse to dispatch yields a bounded ``CacheBypass`` rather than the exception
``prepare_chat_body`` raises — the cache may never fail a request.

INVARIANT under test (the reason the projection calls the real reconstruction): one
upstream routing policy is ONE cache entry. Three spellings of a price ceiling, and a
``zdr`` flag whose ``false`` is sent as nothing at all, canonicalize to the same policy —
so they must canonicalize to the same projection. Splitting them would silently cost the
hit rate this ticket exists to create, while the inverse — two genuinely different
policies sharing an entry — would serve a response produced under a ceiling or data
policy the caller did not ask for.

Scope of THIS file: the projected SHAPE, and the leaves the projection refuses to
describe. Siblings:
  ``test_openrouter_global_cache_keys.py``          — the same equivalences at the HASH,
    which is the only place they protect a caller (plan §10: a provider parameter may not
    become keyed without a key-difference test).
  ``test_openrouter_global_cache_participation.py`` — the operator gate, which decides
    participation and never key material.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi import HTTPException

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.core.parameter_projection import (
    classify_and_project_chat_parameters,
)
from aigateway.core.request_cache.global_keys import (
    build_global_cache_key,
)
from aigateway.plugins.openrouter_provider.plugin import (
    GLOBAL_CACHE_ADAPTER_REVISION,
    OFFICIAL_API_BASE,
)
from aigateway.plugins.openrouter_provider.routing_policy import (
    STRICT_ROUTING_KEY,
)

# The shared arrangement; see ``projection_harness``. Bound to the original private
# names so every relocated test body below reads unchanged.
from .projection_harness import MODEL as _MODEL
from .projection_harness import STRICT as _STRICT
from .projection_harness import UPSTREAM as _UPSTREAM
from .projection_harness import body as _body
from .projection_harness import plugin as _plugin
from .projection_harness import policy as _policy
from .projection_harness import projected as _projected
from .projection_harness import reason as _reason

# --- the projected shape ------------------------------------------------------


def test_a_bare_request_projects_the_pinned_base_and_the_strict_policy() -> None:
    # The two output-affecting things this boundary adds on its own. Attribution
    # headers and the injected key are transport and deliberately absent.
    assert _projected() == {
        "resolved_model": _UPSTREAM,
        "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
        "prepared": {"api_base": OFFICIAL_API_BASE, "provider": dict(_STRICT)},
    }


def test_the_projected_model_is_the_upstream_remainder() -> None:
    # D8: the gateway prefix IS LiteLLM's provider prefix and is stripped exactly
    # once at the wire, so the upstream id is what OpenRouter resolves.
    assert _projected()["resolved_model"] == _UPSTREAM
    assert not _projected()["resolved_model"].startswith("openrouter/")


def test_the_projection_is_deterministic_and_leaves_the_body_untouched() -> None:
    body = _body(provider_params={"sort": "price"})
    snapshot = copy.deepcopy(body)
    plugin = _plugin()
    assert plugin.global_cache_projection(body) == plugin.global_cache_projection(body)
    assert body == snapshot


def test_a_fresh_policy_object_is_returned_each_call() -> None:
    # A shared object would let one request's mutation become the next one's key.
    first = _policy(provider_params={"sort": "price"})
    first["sort"] = "tampered"
    assert _policy(provider_params={"sort": "price"})["sort"] == "price"


# --- strictness is unconditional ----------------------------------------------


def test_require_parameters_is_in_every_projected_policy() -> None:
    # OME-651: there is no caller-dependent path that omits it, so it is part of
    # every fingerprint — a stored response was produced under strict routing.
    for overrides in (
        {},
        {"provider_params": {"sort": "price"}},
        {"provider_params": {"zdr": True}},
        {"provider_params": {"max_price_prompt": "1", "data_collection": "deny"}},
    ):
        assert _policy(**overrides)[STRICT_ROUTING_KEY] is True, overrides


# --- one upstream policy is one entry (plan §2.6) -----------------------------


@pytest.mark.parametrize("spelling", ["1", "1.0", "1.000"])
def test_every_spelling_of_one_price_ceiling_projects_to_one_policy(spelling: str) -> None:
    # The gateway canonicalizes a validated decimal string before it goes upstream,
    # so these are one ceiling — and must be one cache entry, not three.
    assert _policy(provider_params={"max_price_prompt": spelling}) == {
        "max_price": {"prompt": "1"},
        **_STRICT,
    }


def test_a_different_ceiling_is_a_different_policy() -> None:
    assert _policy(provider_params={"max_price_prompt": "1"}) != _policy(
        provider_params={"max_price_prompt": "2"}
    )


def test_the_two_price_ceilings_are_addressed_independently() -> None:
    assert _policy(provider_params={"max_price_prompt": "1"}) != _policy(
        provider_params={"max_price_completion": "1"}
    )


def test_a_false_zdr_flag_projects_exactly_like_omitting_it() -> None:
    # ``false`` and absence mean the same thing upstream, so the honest encoding of
    # "I have no constraint" is to send nothing — and the two requests are the same
    # request.
    assert _policy(provider_params={"zdr": False}) == _policy()


def test_a_true_zdr_flag_is_a_distinct_policy() -> None:
    assert _policy(provider_params={"zdr": True}) == {"zdr": True, **_STRICT}
    assert _policy(provider_params={"zdr": True}) != _policy()


def test_each_reviewed_control_reaches_its_documented_location() -> None:
    assert _policy(provider_params={"sort": "price"}) == {"sort": "price", **_STRICT}
    assert _policy(provider_params={"data_collection": "deny"}) == {
        "data_collection": "deny",
        **_STRICT,
    }
    assert _policy(provider_params={"max_price_completion": "0.5"}) == {
        "max_price": {"completion": "0.5"},
        **_STRICT,
    }


# --- what the projection refuses to describe ----------------------------------


def test_a_wrapper_leaf_that_is_not_a_routing_control_is_not_projected() -> None:
    # ``provider_params.top_k`` targets ``extra_body``, not the routing policy. The
    # projection describes only what it owns; the key builder is what decides
    # whether an undescribed keyed path may participate.
    assert _policy(provider_params={"top_k": 3}) == dict(_STRICT)


@pytest.mark.parametrize(
    "wrapper",
    [
        {"allow_fallbacks": True},  # the excluded control plane
        {"order": ["openai"]},  # provider selection the gateway owns
        {"max_price": {"prompt": "1"}},  # the upstream spelling is not a caller path
        {"nonesuch": 1},
    ],
)
def test_an_unruled_wrapper_leaf_makes_the_whole_request_uncacheable(wrapper: Any) -> None:
    """The refusal these need lives in the KEY BUILDER, not in the projection.

    A leaf with no rule is a 400 on dispatch, so it may never be silently dropped
    from a fingerprint — but the projection is not where that is decided: it
    describes only the surface it owns, and describing an unruled leaf is exactly
    what it must not do. The two halves together are what closes the door.
    """
    plugin = _plugin()
    built = build_global_cache_key(
        provider="openrouter",
        body=_body(provider_params=wrapper),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=None),
        projection=plugin.global_cache_projection,
        provider_auth_modes=plugin.available_auth_modes(),
    )
    assert isinstance(built, CacheBypass), built
    assert built.reason == "unknown_parameter"


def test_a_bare_openrouter_request_is_cacheable_end_to_end() -> None:
    # The property v1 could never have: a request to a provider that rewrites the
    # body gets a global key, because the rewrite is PROJECTED rather than inspected.
    plugin = _plugin()
    built = build_global_cache_key(
        provider="openrouter",
        body=_body(),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=None),
        projection=plugin.global_cache_projection,
        provider_auth_modes=plugin.available_auth_modes(),
    )
    assert not isinstance(built, CacheBypass), built
    assert len(built.key_hash) == 64


@pytest.mark.parametrize(
    "wrapper",
    [
        {"sort": "throughput"},  # the excluded ordering (OME-703 owns provider selection)
        {"max_price_prompt": "abc"},  # not a decimal
        {"max_price_prompt": "-1"},  # a ceiling that is not a ceiling
        {"max_price_prompt": " 1"},  # invisible in a diff and in a log
        {"zdr": "true"},  # a string is not a boolean
        {"data_collection": "maybe"},  # outside the reviewed enum
    ],
)
def test_a_value_the_gateway_would_refuse_to_reconstruct_bypasses(wrapper: Any) -> None:
    # INVARIANT (ledger decision 12): a request whose policy cannot be rebuilt 503s
    # on dispatch. Moving the cache read ahead of preparation must never turn one
    # into a 200 hit, so the projection bypasses instead of describing it.
    assert _reason(provider_params=wrapper) == PROJECTION_BYPASS_REASON


def test_a_malformed_wrapper_bypasses() -> None:
    assert _reason(provider_params="nope") == PROJECTION_BYPASS_REASON
    assert _reason(provider_params=["sort"]) == PROJECTION_BYPASS_REASON


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-fable-5",  # no gateway prefix
        "openrouter/claude-fable-5",  # no author segment
        "openrouter/",  # nothing upstream
        "openai/gpt-5",  # another provider's prefix
        "",
        None,
        7,
    ],
)
def test_a_model_this_plugin_would_not_dispatch_bypasses_instead_of_raising(model: Any) -> None:
    # ``prepare_chat_body`` raises a 400 for exactly these. A projection may not
    # fail a request, so the same judgement is reported as a bypass.
    plugin = _plugin()
    body = _body(model=model)
    assert isinstance(plugin.global_cache_projection(body), CacheBypass)
    with pytest.raises(HTTPException) as raised:
        plugin.prepare_chat_body(dict(body))
    assert raised.value.status_code == 400


def test_a_caller_supplied_provider_object_is_never_projected() -> None:
    # INVARIANT: raw ``provider`` is not a caller request path. The classifier
    # refuses it, and the projection reads only the wrapper — so a caller cannot
    # reach the routing control plane through the fingerprint either.
    assert _policy(provider={"order": ["openai"], "allow_fallbacks": True}) == dict(_STRICT)


# --- the declared `top_k` leaf is really projected (OME-305 review, MEDIUM-2) ---


def test_a_top_k_request_projects_the_exact_leaf_its_own_rule_targets() -> None:
    # The rule publishes `provider_params.top_k -> extra_body.top_k` as `keyed`, and
    # a native value participates in the key ONLY through `prepared`. So the leaf
    # itself must be here: satisfying the key builder's ROOT check with an empty
    # `extra_body` would pass that check while silently dropping the value from the
    # hash, which is the one failure a globally shared cache may never have.
    assert _projected(provider_params={"top_k": 3})["prepared"]["extra_body"] == {"top_k": 3}


def test_a_request_without_top_k_projects_no_extra_body_root_at_all() -> None:
    # BOUNDARY, and the reason the emission is conditional. The key builder's guard
    # is root-only: once `extra_body` is present, every rule targeting that root is
    # keyed on trust, and a leaf missing from it reads as a DELIBERATE omission
    # rather than an error. Emitting the root unconditionally would therefore turn a
    # future `extra_body.*` rule into a silent collision instead of a safe bypass.
    assert "extra_body" not in _projected()["prepared"]
    assert "extra_body" not in _projected(provider_params={"sort": "price"})["prepared"]


def test_two_top_k_values_never_share_a_key() -> None:
    plugin = _plugin()

    def _key(**overrides: Any) -> Any:
        return build_global_cache_key(
            provider="openrouter",
            body=_body(**overrides),
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=None),
            projection=plugin.global_cache_projection,
            provider_auth_modes=plugin.available_auth_modes(),
        )

    three, seven = _key(provider_params={"top_k": 3}), _key(provider_params={"top_k": 7})
    # It must be keyed at all — the defect was a permanent `unprojected_parameter`.
    assert not isinstance(three, CacheBypass), three
    assert not isinstance(seven, CacheBypass), seven
    assert three.key_hash != seven.key_hash
    # ...and neither may collide with the bare request that asked for no top_k.
    bare = _key()
    assert not isinstance(bare, CacheBypass), bare
    assert three.key_hash != bare.key_hash


def test_the_projected_top_k_is_the_value_dispatch_will_actually_send() -> None:
    # The agreement that makes keying it sound. If the projection and the dispatch
    # path disagreed about the effective value, the key would describe a request the
    # provider never receives.
    plugin = _plugin()
    dispatched = classify_and_project_chat_parameters(
        _body(provider_params={"top_k": 3}),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
        auth_mode="api_key",
    )
    projected = _projected(provider_params={"top_k": 3})["prepared"]
    assert dispatched["extra_body"]["top_k"] == projected["extra_body"]["top_k"]
