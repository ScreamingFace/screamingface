"""Phase 10 (OME-479 §Phase 10): provider-AGNOSTIC contract conformance.

FEATURE: the effective-parameter contract's cross-provider guarantees. Instead of
per-provider assertions, this suite DISCOVERS the real registry (`load_plugins`) and
iterates EVERY registered model, so the algebra's invariants are locked for every
current AND future provider — a new plugin that violates them fails here, not in prod.

STORY: as a gateway maintainer adding a provider, I get an automatic guarantee that my
plugin's models route to me, that my summary never overclaims an auth-specific field,
that a locked/transport field cannot be turned on by an ordinary rule, and that every
param I enable is fully evidenced — without editing any central inventory.

INVARIANT (SOLID/hexagonal — plan §12): this file contains NO provider-name literal and
NO hardcoded model/provider inventory. The registry is the single source of truth; the
core composes, the plugins select. (The ONE legitimately-named regression guard — "Codex
GPT-family ids never surface under an `openai` namespace" — lives in the codex-owned test
file, where naming codex is domain-correct, not inventory.)
INVARIANT (§4.4): a RULE is the only thing that enables a parameter; an observation only
adds visibility. Every enabled entry here is proven rule-backed AND fully evidenced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import aigateway.plugins as plugin_packages
from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import normalize_rules
from aigateway.core.loader import load_plugins
from aigateway.core.model_capabilities import canonical_model_id, model_row
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.core.parameter_projection import GATEWAY_OWNED_FIELDS, wrapper_path_conflicts
from aigateway.core.plugin_base import PluginSettings
from aigateway.core.registry import ProviderRegistry
from aigateway.core.request_cache.global_keys import STRUCTURALLY_EXCLUDED_FIELDS


def _operator_gate_overrides(settings_cls: type[PluginSettings]) -> dict[str, bool]:
    """The plugin's operator on/off gates, mapped to ON.

    A gate is recognised by SHAPE, never by name: a boolean setting that defaults to
    False is an operator switch an installation must opt into. Keying off the shape
    keeps this file free of provider names (see the module INVARIANT) and sweeps a
    future provider's gate automatically, without editing anything here.
    """
    return {
        name: True
        for name, field in settings_cls.model_fields.items()
        if field.annotation is bool and field.default is False
    }


def _load_registry() -> ProviderRegistry:
    """The registry the CONTRACT is defined by: every operator gate forced ON.

    WHY (OME-646): a provider that ships disabled contributes no models, so every
    invariant below held vacuously for it while the suite still reported success — the
    gate could not fail for that provider. Conformance describes the declared contract,
    which does not change when an operator flips a switch, so the sweep opts every
    provider in.

    AIDEV-NOTE: this reaches only gates expressible as settings. A plugin that builds
    its catalogue by querying a live external process at call time still contributes
    nothing here when that process is absent, and its rules stay unswept — a real
    residual hole, but one no settings choice can close.
    """
    discovered = ProviderRegistry()
    load_plugins(discovered)
    registry = ProviderRegistry()
    for plugin in discovered.all():
        overrides = _operator_gate_overrides(plugin.settings_cls)
        registry.register(type(plugin)(plugin.settings_cls(**overrides)) if overrides else plugin)
    return registry


# Built once from the SAME discovery the app uses at startup; no names baked in.
_REGISTRY = _load_registry()

# The locked v1 /v1/models row shape (plan §4.1) — asserted structurally, not by value.
_LOCKED_ROW_KEYS = frozenset(
    {
        "id",
        "object",
        "owned_by",
        "supported_parameters",
        "supported_tools",
        "unsupported_parameter_behavior",
        "parameter_contract_url",
    }
)


def _iter_models():
    for plugin in _REGISTRY.all():
        for entry in plugin.register_models():
            canonical = canonical_model_id(
                custom_llm_provider=plugin.custom_llm_provider, model_name=entry.model_name
            )
            yield plugin, entry, canonical


def _document(plugin: Any, canonical: str, auth_mode: AuthMode) -> dict[str, Any]:
    # Mirrors routes/model_parameters.py: the plugin's own hooks + the core composer.
    return build_model_parameter_document(
        canonical_id=canonical,
        gateway_provider=plugin.custom_llm_provider,
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:conformance|prof:1",
        rules=plugin.chat_parameter_rules(model=canonical, auth_type=auth_mode),
        observations=plugin.chat_parameter_observations(model=canonical, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=canonical, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=canonical, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )


def _assert_non_vacuous_contract_views() -> None:
    swept_providers: set[str] = set()
    for plugin, _entry, canonical in _iter_models():
        swept_providers.add(plugin.custom_llm_provider)
        for mode in plugin.available_auth_modes():
            applicable = [
                rule
                for rule in plugin.chat_parameter_rules(model=canonical, auth_type=mode)
                if mode in rule.applicable_auth_modes
            ]
            assert applicable, (plugin.custom_llm_provider, canonical, mode)
    assert swept_providers


@pytest.fixture(autouse=True)
def _non_vacuous_contract_population() -> None:
    _assert_non_vacuous_contract_views()


_SWEPT_PROVIDER_NAMES = tuple(
    sorted({plugin.custom_llm_provider for plugin, _entry, _canonical in _iter_models()})
)


@pytest.mark.parametrize("provider_name", _SWEPT_PROVIDER_NAMES)
def test_population_guard_rejects_a_provider_with_an_empty_rule_set(
    monkeypatch: pytest.MonkeyPatch, provider_name: str
) -> None:
    plugin = next(
        plugin
        for plugin, _entry, _canonical in _iter_models()
        if plugin.custom_llm_provider == provider_name
    )
    monkeypatch.setattr(plugin, "chat_parameter_rules", lambda **_kwargs: ())

    with pytest.raises(AssertionError):
        _assert_non_vacuous_contract_views()


def test_registry_discovery_is_non_vacuous() -> None:
    # Filesystem discovery is independent of the registry under test: a package that
    # silently stops loading cannot disappear from both sides of this assertion.
    package_root = Path(plugin_packages.__file__).parent
    assert len(_REGISTRY.all()) == len(tuple(package_root.glob("*_provider/plugin.py")))


def test_an_operator_gate_cannot_hide_a_provider_from_conformance() -> None:
    # NON-VACUITY, per-provider (OME-646). The guard above sums models across the WHOLE
    # registry, so a provider contributing ZERO still passes it — and every invariant in
    # this file then holds vacuously for that provider while the suite reports success.
    # That is exactly how a schema-less enabled rule survived a green gate: the provider
    # sat behind an operator on/off gate that is off by default, so the sweep examined
    # none of its rows.
    #
    # INVARIANT: conformance is a property of the DECLARED contract, not of one
    # deployment's configuration. A provider whose catalog appears once its operator
    # gates are forced on MUST be in the sweep. Stated this way the check is not
    # self-referential: it compares default-settings plugins against the swept registry,
    # so it fails the moment _load_registry stops forcing the gates.
    #
    # A provider that declares no models even with every gate forced on is discovering
    # its catalog from a live external process at call time; no settings choice can make
    # it declarable here, so it is out of this guard's reach (see the AIDEV-NOTE on
    # _load_registry for that residual).
    swept = {plugin.custom_llm_provider for plugin, _entry, _canonical in _iter_models()}
    as_configured = ProviderRegistry()
    load_plugins(as_configured)
    for plugin in as_configured.all():
        overrides = _operator_gate_overrides(plugin.settings_cls)
        if not overrides or plugin.register_models():
            continue
        ungated = type(plugin)(plugin.settings_cls(**overrides))
        if ungated.register_models():
            assert plugin.custom_llm_provider in swept, plugin.custom_llm_provider


def test_every_model_id_routes_to_its_owning_plugin() -> None:
    # Routing invariant (plan §4.1): a canonical id's first path segment is the owning
    # plugin's unique registry key, so /v1/chat/completions + /v1/model-parameters both
    # resolve the SAME plugin. This subsumes "Codex never resolves to OpenAI": a codex id
    # whose prefix routed to an `openai` plugin would fail here — no provider names needed.
    for plugin, _entry, canonical in _iter_models():
        prefix = canonical.split("/", 1)[0]
        assert _REGISTRY.get(prefix) is plugin, canonical


def test_every_model_row_has_the_locked_summary_shape() -> None:
    for plugin, entry, canonical in _iter_models():
        row = model_row(plugin, entry)
        assert _LOCKED_ROW_KEYS <= set(row), canonical
        assert row["id"] == canonical
        assert row["object"] == "model"
        assert row["owned_by"] == plugin.custom_llm_provider
        # fail-closed literal: unknown/disabled params never silently pass.
        assert row["unsupported_parameter_behavior"] == "reject", canonical
        assert isinstance(row["supported_parameters"], list)
        assert isinstance(row["supported_tools"], list)
        assert row["parameter_contract_url"].startswith("/v1/model-parameters?model="), canonical


def test_no_rule_enables_a_gateway_owned_or_transport_field() -> None:
    # A locked field (model/messages/stream/extra_headers/metadata/timeout) is authorized
    # STRUCTURALLY, never by a rule; and a transport control (surfaced via
    # chat_transport_capabilities) is never an ordinary parameter rule. Check across the
    # summary view (None) AND every real auth mode — neither request_path nor target,
    # nor any transport name, may collide with a rule path.
    for plugin, _entry, canonical in _iter_models():
        for mode in (None, *plugin.available_auth_modes()):
            rules = plugin.chat_parameter_rules(model=canonical, auth_type=mode)
            rule_paths = {rule.request_path for rule in rules}
            for rule in rules:
                assert rule.request_path not in GATEWAY_OWNED_FIELDS, (canonical, rule.request_path)
                assert rule.target not in GATEWAY_OWNED_FIELDS, (canonical, rule.target)
            transport = plugin.chat_transport_capabilities(model=canonical, auth_type=mode)
            transport_names = {cap.name for cap in transport}
            assert transport_names & rule_paths == set(), canonical


def test_summary_is_the_independent_cross_auth_mode_intersection() -> None:
    # The conservative summary must equal the intersection of per-auth-mode enabled paths,
    # recomputed HERE from per-mode rule filtering (NOT by calling
    # inline_supported_parameters — that would test the impl against itself). A field that
    # only one auth mode can prove must be absent, so /v1/models never overclaims.
    for plugin, entry, canonical in _iter_models():
        rules_none = normalize_rules(plugin.chat_parameter_rules(model=canonical, auth_type=None))
        all_paths = {rule.request_path for rule in rules_none}
        modes = plugin.available_auth_modes()
        if modes:
            expected = set(all_paths)
            for mode in modes:
                mode_rules = plugin.chat_parameter_rules(model=canonical, auth_type=mode)
                enabled = {r.request_path for r in mode_rules if mode in r.applicable_auth_modes}
                expected &= enabled
        else:
            # No auth mode can prove any field → the conservative summary is EMPTY
            # (OME-580). "∅ ⊆ anything" is vacuously true, so advertising every ruled
            # path here would be the exact opposite of conservative.
            expected = set()
        assert set(model_row(plugin, entry)["supported_parameters"]) == expected, canonical


def test_every_enabled_param_is_fully_evidenced() -> None:
    # "Enabling is earned" (§6.2): under each REAL auth mode, an enabled parameter must be
    # backed by a rule applicable to that mode AND carry the full evidence a client relies
    # on — a validation schema, a projection kind, a cache behavior, and a corroborating
    # provider observation (support == supported, with a real source). No enabled-but-blank.
    for plugin, _entry, canonical in _iter_models():
        for mode in plugin.available_auth_modes():
            rule_by_path = {
                rule.request_path: rule
                for rule in plugin.chat_parameter_rules(model=canonical, auth_type=mode)
                if mode in rule.applicable_auth_modes
            }
            parameters = _document(plugin, canonical, mode)["parameters"]
            enabled_paths: set[str] = set()
            for path, entry_dict in parameters.items():
                if entry_dict["gateway"]["status"] != "enabled":
                    continue
                enabled_paths.add(path)
                where = (canonical, mode, path)
                # auth evidence: enabled-ness is rule-driven for THIS mode.
                assert path in rule_by_path, where
                # schema + projection + cache evidence.
                assert entry_dict["schema"] is not None, where
                assert entry_dict["gateway"].get("projection"), where
                assert entry_dict["gateway"].get("cache_behavior"), where
                # final-boundary evidence: a real observation corroborates support.
                assert entry_dict["provider"]["support"] == "supported", where
                assert entry_dict["provider"]["source"] != "none", where
            assert enabled_paths == set(rule_by_path), (canonical, mode)


def test_registered_providers_agree_on_which_natives_ride_the_wrapper() -> None:
    # INVARIANT (OME-599): a provider states "this native rides the provider_params.*
    # wrapper" in TWO hand-synced places — its discovery literal and its provider_native
    # rule — and neither imports the other. If they drift, the same field is described at
    # two request paths at once (the rule wrapped, the observation bare), and the contract
    # lists it twice.
    #
    # WHY this guard is needed despite test_every_enabled_param_is_fully_evidenced: that
    # test only inspects ENABLED entries, so it catches drift solely in an auth mode where
    # the rule applies. In a mode where the rule is DISABLED the field silently moves to the
    # bare path and nothing complains. Checking the None (summary) view AND every real mode
    # closes that gap, and naming the field reports the actual cause instead of a downstream
    # "enabled but unevidenced" symptom.
    for plugin, _entry, canonical in _iter_models():
        for mode in (None, *plugin.available_auth_modes()):
            paths = [
                rule.request_path
                for rule in plugin.chat_parameter_rules(model=canonical, auth_type=mode)
            ]
            paths += [
                obs.request_path
                for obs in plugin.chat_parameter_observations(model=canonical, auth_type=mode)
            ]
            assert wrapper_path_conflicts(paths) == (), (canonical, mode)


def test_registered_provider_rule_sets_have_unique_targets() -> None:
    # INVARIANT (OME-597): within one provider rule set, no two rules write the same provider
    # wire target. normalize_rules enforces it at construction; this locks it for every
    # registered provider (and any future one) under every auth-mode view — a misconfig that
    # points two request paths at one target fails in CI here, never as a caller-facing
    # duplicate_channel 400 in prod. Green today; a future colliding rule turns it red.
    for plugin, _entry, canonical in _iter_models():
        for mode in (None, *plugin.available_auth_modes()):
            rules = plugin.chat_parameter_rules(model=canonical, auth_type=mode)
            # normalize_rules raises DuplicateParameterRuleError on a target collision; the
            # explicit set-size assertion documents intent and gives a legible failure tuple.
            normalized = normalize_rules(rules)
            targets = [rule.target for rule in normalized]
            assert len(set(targets)) == len(targets), (canonical, mode, targets)


def test_every_provider_publishes_a_stream_capability_matching_its_dispatch_gate() -> None:
    # INVARIANT (OME-601): the contract and the ENFORCED behaviour cannot drift.
    # /v1/chat/completions rejects stream=true whenever supports_chat_streaming()
    # is false, so the published transport status must equal that same flag —
    # otherwise a client reads "enabled" and is answered with a 400 (or reads
    # "disabled" and never uses a capability that works).
    #
    # ``stream`` is gateway-owned, so it can never be a parameter rule; the
    # transport section is the ONLY surface that can carry it.
    for plugin, _entry, canonical in _iter_models():
        streams = plugin.supports_chat_streaming()
        for mode in (None, *plugin.available_auth_modes()):
            transport = plugin.chat_transport_capabilities(model=canonical, auth_type=mode)
            by_name = {cap.name: cap for cap in transport}
            assert "stream" in by_name, (canonical, mode)
            cap = by_name["stream"]
            assert (cap.gateway_status == "enabled") is streams, (canonical, mode)
            # a disabled control always explains itself; an enabled one has nothing to explain.
            assert (cap.reason is None) is streams, (canonical, mode)


def test_every_enabled_rule_declares_a_cache_behavior_the_pipeline_can_honor() -> None:
    # INVARIANT (OME-479 §4.6, closure Unit 1): the published `cache_behavior` is a
    # PROMISE about the real pipeline, and the pipeline has exactly two outcomes for a
    # request path — it participates in the cache key, or its presence bypasses. A rule
    # declaring `keyed` or `transport_only` for a path the key builder does not read
    # would publish a promise the runtime breaks (the request would bypass while the
    # contract says otherwise).
    #
    # REPOINTED (OME-305): the deliverable set was v1's three `PROMPT_KEY_FIELDS`,
    # which made `keyed` unreachable for every provider — `model`/`messages` are
    # gateway-owned so no rule may name them, and no provider rules `system`. The v2
    # builder keys every request path EXCEPT a published exclusion set, so the promise
    # the pipeline can keep is now a DENYLIST. Same property, and the source of truth
    # is the builder that actually decides it rather than a hand-maintained list — an
    # allowlist would need editing on every promotion, which is how the v1 version
    # rotted into a guard forbidding the promotions it was meant to police.
    #
    # WHY here rather than in a provider suite: this is the cross-provider half of the
    # composition guard. The route-level test proves the CURRENT pipeline honours a
    # declared bypass even across `prepare_chat_body`; this proves no provider — present
    # or future — can declare a cache behaviour that pipeline is unable to deliver.
    for plugin, _entry, canonical in _iter_models():
        for mode in plugin.available_auth_modes():
            for rule in plugin.chat_parameter_rules(model=canonical, auth_type=mode):
                if mode not in rule.applicable_auth_modes:
                    continue
                if rule.cache_behavior == "bypass":
                    continue
                assert rule.request_path.split(".", 1)[0] not in STRUCTURALLY_EXCLUDED_FIELDS, (
                    canonical,
                    mode,
                    rule.request_path,
                    rule.cache_behavior,
                )


def test_the_composed_transport_section_is_populated_for_every_provider() -> None:
    # The section reaches the SERVED document, not just the plugin hook — the
    # previously vacuous transport conformance now has content to check.
    for plugin, _entry, canonical in _iter_models():
        for mode in plugin.available_auth_modes():
            doc = _document(plugin, canonical, mode)
            assert doc["transport"], (canonical, mode)
            assert set(doc["transport"]["stream"]) >= {"provider_support", "gateway_status"}
