"""OME-305 U2 — provider-AGNOSTIC conformance for the global cache projection.

FEATURE: one global exact-request cache. A provider makes a parameter cacheable by
declaring ``cache_behavior="keyed"`` on its own rule, and describes its own
output-affecting preparation through ``global_cache_projection``. Nothing central
lists which parameters or which providers those are — so the guarantees have to be
swept over the REAL registry instead of an inventory.

STORY: as a gateway maintainer promoting a parameter to ``keyed``, I get an
automatic guarantee that the key builder can actually see and hash that path, and
that my provider has a pure projection to back the promise — without editing any
central table.

INVARIANT (SOLID/hexagonal, plan §12): no provider name and no model inventory in
this file. The registry is the source of truth.

INVARIANT under test — an honest ``cache_behavior``. A rule that says ``keyed``
publishes a promise in the detailed contract; these tests prove the pipeline can
keep it. The v1 guard expressed this as "a non-bypass path must be one of
``model``/``messages``/``system``", which was true only while the key was
prompt-only. The generalized form is: a non-bypass path must be a path the v2 key
builder can SEE and does not structurally exclude.

AIDEV-NOTE on what is deliberately NOT swept here: per-value key sensitivity.
Two distinct caller values SHOULD usually produce two keys, but not always — a
provider may normalize ``"1"``, ``"1.0"`` and ``"1.000"`` to one canonical price
on purpose, and that equivalence is exactly what its own named tests must pin.
Generic value generation would also need a value satisfying an arbitrary
pattern-constrained schema, which is not decidable here. Sensitivity is guaranteed
structurally instead: the DTO carries each accepted value verbatim under its
request path, so two different values cannot collide unless the PROVIDER collapsed
them.
"""

from __future__ import annotations

import copy
import inspect
from typing import Any

import pytest

from aigateway.core.cache_ports import CacheBypass
from aigateway.core.chat_parameters import normalize_rules
from aigateway.core.plugin_base import ProviderPluginBase
from aigateway.core.request_cache.global_keys import (
    EXCLUDED_TRANSPORT_FIELDS,
    PRESENCE_BYPASS_REASONS,
    PROMPT_FIELDS,
    TRUTHY_BYPASS_REASONS,
    build_global_cache_key,
)

from ._global_cache_registry_sweep import (
    MINIMUM_PROVIDERS,
    MODEL_LESS_PROVIDERS,
    MODELS,
    PROVIDERS,
    unswept_providers,
)
from ._global_cache_registry_sweep import body as _body
from ._global_cache_registry_sweep import probe_body as _probe_body
from ._global_cache_registry_sweep import rules as _rules

_WRAPPER_PREFIX = "provider_params."

# AIDEV-NOTE: the registry-loading scaffolding MOVED to
# ``_global_cache_registry_sweep`` when the projection-purity sweeps became their own
# module (OME-305). The note that used to sit here argued for duplicating it rather
# than hoisting it into a conftest; that reasoning still stands, and is why the shared
# home is a private sibling module imported by name rather than a conftest. A third
# copy is what made duplication the worse trade.


# The non-bypass rule instances the two honesty sweeps below actually examine, MEASURED
# rather than estimated. Stated so a DROP reads as a regression rather than as a pass —
# the failure mode is a sweep that keeps passing while examining nothing.
#
# 72 of 186 swept instances (39%), contributed by the two providers that implement
# ``global_cache_projection``: 21 anthropic, 51 openrouter. The other five contribute
# zero BY RULING (owner decision 51 ships two providers; the rest keep the bypassing
# base default), so a low provider count here is intended and a low INSTANCE count is
# not. Owner decision 59 deliberately removed the three model instances of Anthropic's
# api-key-only ``top_k`` because a pre-auth key cannot honor a mode-restricted promise.
_OBSERVED_NON_BYPASS_INSTANCES = 72


def _non_bypass_instances() -> list[tuple[Any, str, Any]]:
    """Every (plugin, model, rule) triple a non-bypass sweep is entitled to examine."""
    return [
        (plugin, model, rule)
        for plugin, model in MODELS
        for rule in _rules(plugin, model)
        if rule.cache_behavior != "bypass"
    ]


def test_the_registry_sweep_is_not_vacuous() -> None:
    """Guards the guards: every sweep in this file is a loop that can examine nothing.

    AIDEV-NOTE: this asserted only ``MODELS`` non-empty, which is a claim about MODELS
    and proves nothing about rules or providers reaching an assertion. Three distinct
    ways coverage silently shrank, each now pinned:
      * a provider registered but contributing no models (it happened — see
        ``MODEL_LESS_PROVIDERS``), so a per-model sweep skipped it entirely;
      * the non-bypass population collapsing, which would leave the two honesty sweeps
        passing having examined nothing;
      * a plugin-level invariant swept per MODEL rather than per PLUGIN, which makes
        both problems invisible.
    """
    assert MODELS
    assert len(PROVIDERS) >= MINIMUM_PROVIDERS, [p.custom_llm_provider for p in PROVIDERS]
    # A registered provider that reaches no per-model sweep must be a KNOWN, recorded
    # case — never a new one that quietly appeared.
    assert unswept_providers() <= MODEL_LESS_PROVIDERS, unswept_providers()
    assert len(_non_bypass_instances()) >= _OBSERVED_NON_BYPASS_INSTANCES, (
        "the non-bypass population shrank; the honesty sweeps below now examine less "
        f"than the {_OBSERVED_NON_BYPASS_INSTANCES} instances observed when they were written"
    )


def test_no_non_bypass_rule_names_a_field_the_key_builder_structurally_excludes() -> None:
    """The generalized replacement for v1's ``PROMPT_KEY_FIELDS`` guard.

    A rule claiming ``keyed`` or ``transport_only`` for a path the builder skips
    structurally — prompt material, an excluded transport field, or a field whose
    presence bypasses outright — publishes a promise the pipeline silently drops.

    AIDEV-NOTE: compares the path's FIRST SEGMENT, not the whole path. Every excluded
    entry is a BARE top-level field name, so ``request_path not in excluded`` could
    never fail for a dotted path — a rule keyed on ``tools.function`` passed while being
    exactly as unreachable as one keyed on ``tools``. Widening the population without
    this fix would have swept many more instances through an assertion that still could
    not fail on the interesting shape, which is why the two changes landed together.
    ``provider_params.*`` is unaffected and must stay so: its first segment is the
    wrapper, and the wrapper object is its own namespace — a provider-native ``stream``
    inside it is NOT the top-level ``stream`` the presence bypass reads.
    """
    excluded = (
        PROMPT_FIELDS
        | EXCLUDED_TRANSPORT_FIELDS
        | frozenset(PRESENCE_BYPASS_REASONS)
        | frozenset(TRUTHY_BYPASS_REASONS)
    )
    examined = 0
    for plugin, model, rule in _non_bypass_instances():
        examined += 1
        root = rule.request_path.split(".", 1)[0]
        assert root not in excluded, (
            plugin.custom_llm_provider,
            model,
            rule.request_path,
            rule.cache_behavior,
        )
    assert examined, "examined no non-bypass rule; this sweep proved nothing"


def test_every_non_bypass_rule_uses_an_addressing_form_the_key_builder_can_see() -> None:
    # Direct dotted paths are addressable top-level; only provider-native paths require the
    # wrapper object. A direct `provider_params.*` rule would claim the wrapper-only namespace
    # while bypassing its reconstruction contract, so it is the one unreachable combination.
    examined = 0
    for plugin, model, rule in _non_bypass_instances():
        examined += 1
        reachable = not rule.request_path.startswith(_WRAPPER_PREFIX) or (
            rule.projection_kind == "provider_native"
        )
        assert reachable, (plugin.custom_llm_provider, model, rule.request_path)
    assert examined, "examined no non-bypass rule; this sweep proved nothing"


def test_every_non_bypass_rule_applies_in_every_mode_its_provider_offers() -> None:
    """Owner ruling 59: the pre-auth cache cannot key a mode-restricted rule."""
    examined = 0
    for plugin, model, rule in _non_bypass_instances():
        examined += 1
        provider_modes = set(plugin.available_auth_modes())
        assert provider_modes <= set(rule.applicable_auth_modes), (
            plugin.custom_llm_provider,
            model,
            rule.request_path,
            rule.cache_behavior,
            provider_modes,
            rule.applicable_auth_modes,
        )
    assert examined, "examined no non-bypass rule; this sweep proved nothing"


def test_the_projection_port_cannot_receive_identity_in_any_plugin() -> None:
    # Plan §10: no account, profile, user, auth mode or credential may reach a
    # globally shared key. Proven structurally for every override, not just the
    # base default — an added parameter fails here regardless of what it is named.
    #
    # Swept over PROVIDERS, not MODELS: this is a property of the CLASS, and a
    # per-model sweep skipped every plugin that declares no models (finding L2).
    for plugin in PROVIDERS:
        signature = inspect.signature(type(plugin).global_cache_projection)
        assert list(signature.parameters) == ["self", "body"], plugin.custom_llm_provider


def test_no_projection_is_asynchronous() -> None:
    # INVARIANT: the projection is PURE and synchronous. A coroutine would be the
    # first symptom of a hook that wants to do I/O. Per PLUGIN — see above.
    for plugin in PROVIDERS:
        assert not inspect.iscoroutinefunction(type(plugin).global_cache_projection)


def test_every_projection_is_deterministic_and_leaves_the_body_untouched() -> None:
    # Per PLUGIN via ``probe_body``, so a model-less provider is covered too; where a
    # provider declares models, its own first model is what gets probed.
    for plugin in PROVIDERS:
        body = _probe_body(plugin)
        snapshot = copy.deepcopy(body)
        first = plugin.global_cache_projection(body)
        second = plugin.global_cache_projection(body)
        assert body == snapshot, plugin.custom_llm_provider
        assert first == second, plugin.custom_llm_provider


def test_no_projection_opens_a_network_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("global_cache_projection attempted network I/O")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    # Per PLUGIN: a provider whose model discovery needs a live daemon is exactly the
    # one most likely to dial something from inside a projection, and it was the one
    # this sweep skipped.
    for plugin in PROVIDERS:
        plugin.global_cache_projection(_probe_body(plugin))


def test_the_auth_mode_independent_rule_view_agrees_with_every_per_mode_view() -> None:
    """Ruling 7 / decision 1 — the pre-cache stage may only see the ``None`` view.

    The cache stage runs before any auth mode is resolved, so it keys a request using
    ``chat_parameter_rules(auth_type=None)``. Validation later runs under the RESOLVED
    mode. Two disagreements would be silent correctness bugs:

    - a path the ``None`` view does not carry but a per-mode view does would be keyed
      as an unknown parameter (a bypass) while that mode considers it accepted, so the
      request could never be cached under the mode that actually allows it;
    - a path both views carry but with a different ``cache_behavior``, target or
      schema would be keyed under one policy and dispatched under another — the exact
      shape of "two callers share a key but not a request".

    So: every per-mode path is a subset of the ``None`` view, and every shared path is
    IDENTICAL in the three fields that decide keying and projection.
    """
    for plugin, model in MODELS:
        base = {rule.request_path: rule for rule in _rules(plugin, model)}
        for mode in plugin.available_auth_modes():
            for rule in normalize_rules(plugin.chat_parameter_rules(model=model, auth_type=mode)):
                context = (plugin.custom_llm_provider, model, mode, rule.request_path)
                assert rule.request_path in base, context
                reference = base[rule.request_path]
                assert rule.cache_behavior == reference.cache_behavior, context
                assert rule.provider_target == reference.provider_target, context
                assert rule.parameter_schema == reference.parameter_schema, context


def test_a_provider_that_declares_a_keyed_rule_backs_it_with_a_real_projection() -> None:
    """The honesty check that makes ``keyed`` mean something.

    A ``keyed`` rule is worthless while the provider's projection bypasses — every
    request for that model would bypass anyway, so the contract would advertise a
    cacheable parameter that can never be cached.
    """
    for plugin, model in MODELS:
        if not any(rule.cache_behavior == "keyed" for rule in _rules(plugin, model)):
            continue
        produced = plugin.global_cache_projection(_body(model))
        assert not isinstance(produced, CacheBypass), (plugin.custom_llm_provider, model)


def test_a_bare_request_is_cacheable_exactly_when_the_provider_has_a_projection() -> None:
    """End-to-end over the registry: no keyed parameters, just the prompt.

    This is the property v1 never had for a provider that rewrites the body —
    ``prepare_chat_body`` adding an ``api_base`` made every such request
    structurally ineligible. Under v2 preparation is PROJECTED, not inspected, so
    a bare request is cacheable whenever the provider can describe itself.
    """
    for plugin, model in MODELS:
        body = _body(model)
        implemented = not isinstance(plugin.global_cache_projection(dict(body)), CacheBypass)
        built = build_global_cache_key(
            provider=plugin.custom_llm_provider,
            body=body,
            rules=_rules(plugin, model),
            projection=plugin.global_cache_projection,
            provider_auth_modes=plugin.available_auth_modes(),
        )
        assert isinstance(built, CacheBypass) is not implemented, (
            plugin.custom_llm_provider,
            model,
            built,
        )


def test_the_default_projection_bypasses() -> None:
    # Fail safe: a provider is cacheable only by deliberately implementing the
    # hook, never by inheriting a guess about what its preparation does.
    class _Bare(ProviderPluginBase):  # type: ignore[misc]
        pass

    assert isinstance(
        ProviderPluginBase.global_cache_projection(_Bare, {"model": "m"}),  # type: ignore[arg-type]
        CacheBypass,
    )
