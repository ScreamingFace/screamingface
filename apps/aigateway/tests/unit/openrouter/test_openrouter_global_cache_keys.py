"""OME-305 U3 — OpenRouter's projected equivalences, proven at the HASH.

FEATURE: a globally shared exact-request cache OpenRouter requests can enter. Its sibling
``test_openrouter_global_cache_projection.py`` proves the projection canonicalizes
correctly; a projection can be perfect while the value never reaches the key at all —
which is exactly what a ``bypass`` rule does.

STORY: as a benchmark operator I write ``1``, ``1.0`` and ``1.000`` for the same price
ceiling across three runs and get one row, while a genuinely different ceiling gets its
own.

INVARIANT under test (plan §10 stop condition: "a provider parameter becomes keyed without
a key-difference test"): every reviewed routing control and every keyed parameter path has
an explicit key-difference proof, the canonical equivalences collapse to ONE key, and the
caller's raw spelling never appears in the key material.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.cache_ports import CacheBypass
from aigateway.core.parameter_projection import (
    WRAPPER_KEY,
)
from aigateway.core.request_cache.global_keys import (
    build_global_cache_key_dto,
    canonical_key_material,
)
from aigateway.plugins.openrouter_provider.routing_policy import (
    ROUTING_CONTROLS,
)

# The shared arrangement; see ``projection_harness``. Bound to the original private
# names so every relocated test body below reads unchanged.
from .projection_harness import MODEL as _MODEL
from .projection_harness import STRICT as _STRICT
from .projection_harness import body as _body
from .projection_harness import key as _key
from .projection_harness import plugin as _plugin

# --- the promotion to `keyed`: the same pins, at the HASH ----------------------
#
# Plan §10 stop condition: "a provider parameter becomes keyed without a
# key-difference test". Everything above proves the PROJECTION canonicalizes
# correctly; a projection can be perfect while the value never reaches the key at
# all — which is exactly what a `bypass` rule does, and exactly what these catch.


def test_a_routing_controlled_request_is_keyed_rather_than_bypassed() -> None:
    # The half the promotion delivers: a request CARRYING a control gets a key at all.
    # While the rules declared `bypass` this returned a CacheBypass, so `_key`'s own
    # assertion is the test.
    assert len(_key(provider_params={"sort": "price"})) == 64


def test_the_same_routing_controlled_request_repeats_to_the_same_key() -> None:
    # A keyed HIT on repeat — the hit rate this promotion exists to create.
    controls = {"max_price_prompt": "1", "data_collection": "deny"}
    assert _key(provider_params=dict(controls)) == _key(provider_params=dict(controls))


def test_a_routing_control_changes_the_key_at_all() -> None:
    # Guards against the control being accepted and then silently excluded — the
    # under-keying failure that would share one entry across two policies.
    assert _key(provider_params={"sort": "price"}) != _key()


@pytest.mark.parametrize(
    ("leaf", "first", "second"),
    [
        ("max_price_prompt", "1", "2"),
        ("max_price_completion", "0.5", "0.75"),
        ("data_collection", "deny", "allow"),
        ("zdr", True, False),
    ],
)
def test_two_requests_differing_only_in_one_control_never_cross_hit(
    leaf: str, first: Any, second: Any
) -> None:
    # THE privacy/correctness test for this promotion. A different price ceiling or a
    # different data policy is a different request, and serving one from the other's
    # entry is a correctness bug for price and a privacy bug for data policy.
    #
    # AIDEV-NOTE: `sort` is absent from this table because its reviewed enum admits
    # exactly one value (`("price",)`), so two distinct VALID values cannot be
    # constructed for it. Its key difference is presence-vs-absence and is covered by
    # test_a_routing_control_changes_the_key_at_all. Widen the enum and add a row here.
    assert _key(provider_params={leaf: first}) != _key(provider_params={leaf: second})


def test_every_reviewed_control_is_covered_by_a_key_difference_test() -> None:
    """Guards the table above against a control being promoted and never pinned.

    AIDEV-NOTE: plan §10 forbids a parameter becoming keyed without a key-difference
    test, and a hand-written parametrize table cannot notice a SIXTH control being
    added to ``ROUTING_CONTROLS``. This asserts the reviewed surface is exactly what
    the tests above exercise, so adding a control without pinning it fails here.
    """
    covered = {"max_price_prompt", "max_price_completion", "data_collection", "zdr"}
    # `sort` is pinned by presence-vs-absence rather than by two values — see above.
    assert {control.leaf for control in ROUTING_CONTROLS} == covered | {"sort"}


@pytest.mark.parametrize(
    ("path", "first", "second"),
    [
        ("seed", 1, 2),
        ("response_format", {"type": "text"}, {"type": "json_object"}),
        ("n", 1, 2),
        ("logprobs", False, True),
        ("top_logprobs", 1, 2),
        ("stop", ["alpha"], ["beta"]),
        ("max_tokens", 32, 64),
        ("temperature", 0.2, 0.8),
        ("frequency_penalty", 0.1, 0.2),
        ("presence_penalty", 0.1, 0.2),
        (
            "tools",
            [{"type": "function", "function": {"name": "a"}}],
            [{"type": "function", "function": {"name": "b"}}],
        ),
        (
            "tool_choice",
            "auto",
            {"type": "function", "function": {"name": "f"}},
        ),
        # OME-781: the deployment blocklist that forced these to `bypass` is deleted,
        # so both search fields are keyed exactly like every other direct path.
        ("web_search", True, False),
        ("web_search_excluded_domains", ["a.test"], ["b.test"]),
        # OME-993: the DRACO judge's reasoning throttle is output-affecting and keyed.
        ("reasoning_effort", "low", "high"),
    ],
)
def test_two_openrouter_requests_differing_only_in_one_keyed_value_never_share_a_key(
    path: str, first: Any, second: Any
) -> None:
    assert _key(**{path: first}) != _key(**{path: second})


def test_every_openrouter_keyed_path_has_an_explicit_key_difference_proof() -> None:
    """Ruling 7: the tables in this module account for every keyed path."""
    plugin = _plugin()
    keyed = {
        rule.request_path
        for rule in plugin.chat_parameter_rules(model=_MODEL, auth_type=None)
        if rule.cache_behavior == "keyed"
    }
    covered_by_two_values = {
        "seed",
        "response_format",
        "n",
        "logprobs",
        "top_logprobs",
        "stop",
        "max_tokens",
        "temperature",
        "frequency_penalty",
        "presence_penalty",
        "top_p",
        "provider_params.max_price_prompt",
        "provider_params.max_price_completion",
        "provider_params.data_collection",
        "provider_params.zdr",
        "provider_params.top_k",
        # OME-787: OpenRouter is the first provider opted into keyed tools/tool_choice
        # (it has a real ``global_cache_projection`` to back them) — pinned by the two
        # rows above, same as every other direct-keyed path.
        "tools",
        "tool_choice",
        # OME-781: the deployment blocklist that forced these to `bypass` is deleted.
        "web_search",
        "web_search_excluded_domains",
        # OME-993: keyed with the two-value row above.
        "reasoning_effort",
    }
    # `sort` has one valid value and is pinned by presence versus absence above.
    assert keyed == covered_by_two_values | {"provider_params.sort"}


def test_the_two_price_ceilings_are_keyed_independently() -> None:
    # A ceiling on the prompt is not a ceiling on the completion; collapsing them
    # would serve a completion-capped answer to a prompt-capped request.
    assert _key(provider_params={"max_price_prompt": "1"}) != _key(
        provider_params={"max_price_completion": "1"}
    )


@pytest.mark.parametrize("spelling", ["1", "1.0", "1.000"])
def test_every_spelling_of_one_price_ceiling_shares_one_key(spelling: str) -> None:
    # Plan §2.6 at the hash: "1" == "1.0" == "1.000". These are ONE upstream ceiling,
    # so they must be one entry — three would be a silent 3x loss of hit rate.
    #
    # WHY this can only work through the reconstructed policy: `normalize_price`
    # collapses the spellings on the way to the wire, so hashing the caller's raw leaf
    # could never make them agree.
    assert _key(provider_params={"max_price_prompt": spelling}) == _key(
        provider_params={"max_price_prompt": "1"}
    )


def test_a_false_zdr_flag_keys_exactly_like_omitting_it() -> None:
    # Plan §2.6: `zdr` omitted == `zdr: false`. The gateway sends NOTHING for a false
    # flag, so the two requests are byte-identical upstream and must be one entry.
    assert _key(provider_params={"zdr": False}) == _key()


def test_a_true_zdr_flag_is_a_distinct_key() -> None:
    # The inverse, and the one that matters for privacy: a zero-data-retention
    # request must never be answered from an entry filled without that restriction.
    true_key = _key(provider_params={"zdr": True})
    assert true_key != _key()
    assert true_key != _key(provider_params={"zdr": False})


def test_the_strict_routing_policy_participates_in_every_key() -> None:
    # OME-651's `require_parameters` is forced onto every dispatch, so every stored
    # response was produced under strict routing. It reaches the key through
    # `prepared_request`, which is what makes that a property of the ENTRY and not
    # merely of the dispatch.
    plugin = _plugin()
    dto = build_global_cache_key_dto(
        provider="openrouter",
        body=_body(),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=None),
        projection=plugin.global_cache_projection,
        provider_auth_modes=plugin.available_auth_modes(),
    )
    assert not isinstance(dto, CacheBypass), dto
    assert dto.prepared_request["provider"] == dict(_STRICT)
    assert WRAPPER_KEY not in canonical_key_material(dto)


def test_the_callers_raw_spelling_never_appears_in_the_key_material() -> None:
    # The design this promotion rests on: what participates is the RECONSTRUCTED
    # policy, not the caller's wrapper. A caller leaf name leaking into the hashed
    # material would mean the spelling was being keyed after all, and the §2.6
    # equivalences above would be accidental rather than structural.
    plugin = _plugin()
    dto = build_global_cache_key_dto(
        provider="openrouter",
        body=_body(provider_params={"max_price_prompt": "1.000"}),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=None),
        projection=plugin.global_cache_projection,
        provider_auth_modes=plugin.available_auth_modes(),
    )
    assert not isinstance(dto, CacheBypass), dto
    material = canonical_key_material(dto)
    assert "max_price_prompt" not in material
    assert "1.000" not in material
    # ...while the canonical upstream form IS there.
    assert dto.prepared_request["provider"]["max_price"] == {"prompt": "1"}
