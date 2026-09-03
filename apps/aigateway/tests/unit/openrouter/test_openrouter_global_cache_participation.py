"""OME-305/OME-884 — OpenRouter's operator gate governs PARTICIPATION, never key material.

FEATURE: a globally shared exact-request cache (OME-305) whose provider port asks two
separate questions — may this provider take part, and what would its key be.

STORY: as an operator I turn OpenRouter off and its rows stop being read or filled, while
the rows already stored keep describing exactly the requests that produced them.

INVARIANT under test: ``settings.enabled`` is the WHOLE answer for this provider. The
projection is contractually blind to it, the widened OME-884 port that now carries the raw
requested model changes nothing here, and a hazard scoped to another provider — direct
OpenAI's ``litellm.modify_params`` gate — must leave OpenRouter's answer untouched in both
its ON and OFF positions. A fix scoped to one provider silently changing another's caching
is precisely what that unit was forbidden from doing.
"""

from __future__ import annotations

import pytest

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.core.request_cache.global_controls import GlobalCacheControls
from aigateway.core.request_cache.global_plan import build_global_cache_plan
from aigateway.plugins.openrouter_provider.plugin import (
    GLOBAL_CACHE_ADAPTER_REVISION,
    OFFICIAL_API_BASE,
    OpenRouterProviderPlugin,
)
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

# The shared arrangement; see ``projection_harness``. Bound to the original private
# names so every relocated test body below reads unchanged.
from .projection_harness import MODEL as _MODEL
from .projection_harness import STRICT as _STRICT
from .projection_harness import UPSTREAM as _UPSTREAM
from .projection_harness import body as _body
from .projection_harness import projected as _projected

# --- the operator gate decides PARTICIPATION, not KEY MATERIAL (review MEDIUM-1) --


def _disabled_plugin() -> OpenRouterProviderPlugin:
    return OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=False))


def _enabled_plugin() -> OpenRouterProviderPlugin:
    # WHY spelled out here and NOT folded into `_plugin()`: `enabled` ships FALSE, so
    # the two arrangements differ — but only for PARTICIPATION. Every projection
    # assertion above deliberately keeps using the default-constructed plugin, because
    # the projection is contractually blind to this setting and those tests are the
    # place that stays true whichever way the switch is thrown.
    return OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True))


def test_a_disabled_provider_declines_to_participate_in_the_shared_cache() -> None:
    # INVARIANT: a provider kill switch must reach the CACHE path, not only the
    # dispatch path. `register_models` returns nothing and `api_key_strategy_for`
    # returns None when disabled — but a STORED ROW needs neither a model entry nor a
    # credential to be replayed, and the cache stage runs ahead of both checks.
    assert _disabled_plugin().participates_in_global_cache() is False
    assert _enabled_plugin().participates_in_global_cache() is True


def test_the_gate_changes_participation_without_touching_key_material() -> None:
    # WHY both halves in one test: they are the two directions of the same ruling —
    # settings may gate participation, never shape the key. If the gate also changed
    # the key, flipping the switch would abandon every stored row: a silent cache
    # flush dressed up as a bug fix.
    #
    # The projection is therefore asserted to be BLIND to the setting. That is also
    # its port contract (it reads the body alone), enforced globally by
    # `tests/unit/test_global_cache_projection_purity.py`; this is the
    # OpenRouter-specific statement of the same property, at the value level.
    expected = {
        "resolved_model": _UPSTREAM,
        "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
        "prepared": {"api_base": OFFICIAL_API_BASE, "provider": dict(_STRICT)},
    }
    assert _projected() == expected
    assert _disabled_plugin().global_cache_projection(_body()) == expected


def test_a_disabled_provider_yields_a_plan_that_does_not_participate() -> None:
    # The layer that actually enforces the gate: participation is refused in the PLAN,
    # which is where a settings read is legitimate. Asserted here rather than only at
    # the route so the property is pinned without a database, a profile or a
    # credential — and so a future refactor that drops the plan's call to the hook
    # fails a unit test rather than only an end-to-end one.
    def _plan(plugin: OpenRouterProviderPlugin):
        return build_global_cache_plan(
            body=_body(),
            plugin=plugin,
            controls=GlobalCacheControls(participate=True, bypass_reason=""),
            cache_enabled=True,
        )

    refused = _plan(_disabled_plugin())
    assert isinstance(refused, CacheBypass)
    assert refused.reason == PROJECTION_BYPASS_REASON
    # Non-vacuous: the SAME request under an enabled provider does participate, so the
    # refusal is owed to the gate and not to the request being unkeyable.
    assert not isinstance(_plan(_enabled_plugin()), CacheBypass)


# --- OME-884: the same verdict through the WIDENED participation port ----------


def test_the_operator_switch_is_the_whole_answer_whatever_model_is_passed() -> None:
    """OME-884 widened the port to carry the raw requested model. OpenRouter ignores it.

    ``test_a_disabled_provider_declines_to_participate_in_the_shared_cache`` above still
    pins the DEFAULTED call, which is the form the base class documents and the form a
    direct caller uses. This companion pins the form ``build_global_cache_plan`` actually
    uses — the raw model, exactly as the caller sent it — and proves the widening changed
    nothing here.

    WHY OpenRouter needs no per-model branch, unlike direct OpenAI: its one per-model
    refusal (`:online`) is KEY MATERIAL, not a participation question, and the projection
    already bypasses it. So the operator switch remains the entire verdict, and the extra
    argument must not be able to flip it in either direction — including for a model that
    is not a string, since this gate runs before the request's shape is adjudicated.
    """
    disabled = _disabled_plugin()
    enabled = _enabled_plugin()

    for model in (_MODEL, f"{_MODEL}:online", "openai/gpt-4o", "", None, 7, ["a"], {"b": 1}):
        assert disabled.participates_in_global_cache(model) is False, model
        assert enabled.participates_in_global_cache(model) is True, model

    # And the defaulted call agrees with the explicit one, so no caller sees a different
    # answer depending on which form of the port it reaches for.
    assert disabled.participates_in_global_cache() is disabled.participates_in_global_cache(_MODEL)
    assert enabled.participates_in_global_cache() is enabled.participates_in_global_cache(_MODEL)


def test_the_ambient_litellm_modifier_is_not_this_providers_concern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OME-884 cycle 2 blast-radius pin: the modifier gate is direct OpenAI's alone.

    ``litellm.modify_params`` disqualifies DIRECT OpenAI from the global cache because
    ``max_tokens`` is that provider's one keyed parameter, so a rewritten ceiling would
    poison a row the key cannot describe. OpenRouter reaches this decision from a
    different place entirely, and its participation must stay governed by the operator
    switch alone — otherwise a fix scoped to one provider silently changed another's
    caching, which is exactly what the unit was forbidden from doing.
    """
    import litellm

    for modifier in (True, False):
        monkeypatch.setattr(litellm, "modify_params", modifier)
        # Both the operator's ON and OFF answers must be exactly what they were: the
        # switch is still the whole story for this provider.
        assert _enabled_plugin().participates_in_global_cache("openrouter/openai/gpt-5") is True
        assert _enabled_plugin().participates_in_global_cache() is True
        assert _disabled_plugin().participates_in_global_cache("openrouter/openai/gpt-5") is False
        assert _disabled_plugin().participates_in_global_cache() is False
