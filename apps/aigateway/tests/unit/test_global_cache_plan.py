"""OME-305 U5 — the pure pre-credential global cache plan.

FEATURE: one global exact-request cache. A hit needs no profile, no auth mode and
no credential, so the decision to LOOK has to be taken before any of them are
resolved. This module is that decision as a pure function, and these tests are
what let the ticket's central properties — identity invariance and projection
purity — be proven without a connection, a credential blob or a database.

STORY: as a benchmark operator I re-run a suite from a second account; the plan is
byte-for-byte the same plan the first account produced, so the stored response is
reachable without the second account's key.

INVARIANT under test: TOTAL. An operator gate that is off, a caller opt-out, a
malformed control, an unkeyable request and a provider hook that raises all
produce a plan that does not participate — with a bounded reason. Nothing raises.

INVARIANT under test: exactly one of (key, reason) is populated, so a plan can
never be read as "cacheable and also bypassed".

AIDEV-NOTE: fabricated plugins only, no provider names and no route. The real
registry sweep lives in test_global_cache_registry_conformance.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ParameterSchema,
)
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.core.profile_models import AuthMode
from aigateway.core.request_cache.global_controls import parse_global_cache_controls
from aigateway.core.request_cache.global_eligibility import BYPASS_UNPROJECTED_NATIVE
from aigateway.core.request_cache.global_keys import GlobalCacheKeyResult
from aigateway.core.request_cache.global_plan import (
    BYPASS_DISABLED,
    GlobalCacheDecision,
    build_global_cache_plan,
)
from aigateway.core.standard_parameters import provider_native_rule

_AUTH: tuple[AuthMode, ...] = ("api_key",)
_MODEL = "planned/m"
_ADAPTER_REVISION = "pa-1"

_TEMPERATURE = ParameterProjectionRule(
    request_path="temperature",
    applicable_auth_modes=_AUTH,
    projection_kind="direct",
    cache_behavior="keyed",
    projection_revision="rule-r1",
    schema=ParameterSchema(type="number", minimum=0, maximum=2),
)


class _Plugin(ProviderPluginBase):
    """A provider that describes itself: cacheable by deliberate implementation."""

    custom_llm_provider = "planned"

    def register_models(self) -> list[ModelEntry]:
        return [ModelEntry(model_name="m", litellm_params={"model": _MODEL})]

    def available_auth_modes(self) -> tuple[AuthMode, ...]:
        # Must AGREE with every keyed rule's ``applicable_auth_modes`` below. A
        # provider offering a mode one of its keyed rules does not apply in is
        # exactly what the mode-restriction guard refuses — see
        # ``_ModeRestricted``, which is that inconsistency on purpose.
        return _AUTH

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        return (_TEMPERATURE,)

    def global_cache_projection(self, body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        return {
            "resolved_model": "m",
            "provider_adapter_revision": _ADAPTER_REVISION,
            "prepared": {"api_base": "https://example.invalid/v1"},
        }


class _Undescribed(_Plugin):
    """A provider that has not implemented the port — the fail-safe default."""

    custom_llm_provider = "undescribed"

    global_cache_projection = ProviderPluginBase.global_cache_projection


class _BrokenRules(_Plugin):
    """A provider whose rule table raises. Third-party-shaped code on a hot path."""

    custom_llm_provider = "broken"

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        raise RuntimeError("boom")


class _ModeRestricted(_Plugin):
    """Offers two auth modes, but its keyed rule applies in only one of them.

    No shipped provider may publish this shape after owner ruling 59. It remains a
    core fail-safe fixture so a third-party or future rule-table bug bypasses rather
    than under-keying a request before auth resolution.
    """

    custom_llm_provider = "restricted"

    def available_auth_modes(self) -> tuple[AuthMode, ...]:
        return ("api_key", "oauth")


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}
    body.update(overrides)
    return body


def _plan(
    body: dict[str, Any] | None = None,
    *,
    plugin: ProviderPluginBase | None = None,
    controls: Any = None,
    cache_enabled: bool = True,
) -> GlobalCacheDecision:
    return build_global_cache_plan(
        body=_body() if body is None else body,
        plugin=_Plugin() if plugin is None else plugin,
        controls=parse_global_cache_controls({}) if controls is None else controls,
        cache_enabled=cache_enabled,
    )


def _key(decision: GlobalCacheDecision) -> GlobalCacheKeyResult:
    assert isinstance(decision, GlobalCacheKeyResult)
    return decision


def _bypass(decision: GlobalCacheDecision) -> CacheBypass:
    assert isinstance(decision, CacheBypass)
    return decision


# --- the plan cannot see identity ---------------------------------------------


def test_the_planner_accepts_no_identity_profile_or_credential_input() -> None:
    # Plan §10, proven structurally: a later parameter named ``account_id`` fails
    # here even if no test ever passes one.
    assert set(inspect.signature(build_global_cache_plan).parameters) == {
        "body",
        "plugin",
        "controls",
        "cache_enabled",
    }


def test_the_planner_performs_no_io_and_needs_no_await() -> None:
    # A coroutine would be the first symptom of a store read or a credential fetch
    # creeping into the half that must stay pure.
    assert not inspect.iscoroutinefunction(build_global_cache_plan)


def test_the_same_request_plans_to_the_same_key_every_time() -> None:
    first = _key(_plan())
    second = _key(_plan())
    assert first.key_hash == second.key_hash


def test_a_participating_plan_carries_a_key_and_no_reason() -> None:
    key = _key(_plan(_body(temperature=0.7)))
    assert len(key.key_hash) == 64
    assert key.provider == "planned"
    assert key.model == _MODEL
    assert not hasattr(key, "reason")


def test_a_keyed_parameter_still_reaches_the_planned_key() -> None:
    bare = _key(_plan())
    warmer = _key(_plan(_body(temperature=0.7)))
    assert bare.key_hash != warmer.key_hash


# --- the operator gate --------------------------------------------------------


def test_a_disabled_cache_does_not_participate() -> None:
    bypass = _bypass(_plan(cache_enabled=False))
    assert bypass.reason == BYPASS_DISABLED
    assert not hasattr(bypass, "key_hash")


@pytest.mark.parametrize(
    "controls",
    [
        {"cache": {"use-cache": False}},
        {"cache": {"use-cache": "yes"}},
        {"cache": {"ttl": 60}},
    ],
)
def test_the_operator_gate_outranks_every_caller_control(controls: dict[str, Any]) -> None:
    # WHY the gate is reported rather than the caller's control: when the cache is
    # off, no property of the request was ever consulted, and naming one would
    # describe a decision that was not reached.
    bypass = _bypass(
        _plan(controls=parse_global_cache_controls(dict(controls)), cache_enabled=False)
    )
    assert bypass.reason == BYPASS_DISABLED


def test_a_disabled_cache_still_yields_a_plan_for_an_unkeyable_request() -> None:
    # Total: the gate is checked before eligibility, so a body that could not be
    # keyed anyway is still answered with a plan and not an exception.
    assert _bypass(_plan({"model": 7}, cache_enabled=False)).reason == BYPASS_DISABLED


# --- caller controls ----------------------------------------------------------


@pytest.mark.parametrize(
    ("control", "reason"),
    [
        ({"use-cache": False}, "opted_out"),
        ({"use-cache": "yes"}, "malformed_controls"),
        ({"ttl": 60}, "unsupported_control"),
        ({"no-store": True}, "unsupported_control"),
        ({"variant": "sample-0"}, "unsupported_control"),
    ],
)
def test_a_caller_control_that_refuses_the_cache_is_reported_verbatim(
    control: dict[str, Any], reason: str
) -> None:
    bypass = _bypass(_plan(controls=parse_global_cache_controls({"cache": control})))
    assert bypass.reason == reason


@pytest.mark.parametrize("control", [None, {}, {"use-cache": True}])
def test_participation_is_the_default_and_is_explicitly_requestable(control: Any) -> None:
    # v2 grammar: absent, empty and an explicit opt-IN all read+write.
    controls = parse_global_cache_controls({} if control is None else {"cache": control})
    _key(_plan(controls=controls))


# --- provider failures cost a bypass, never the request -----------------------


def test_a_provider_that_has_not_implemented_the_port_does_not_participate() -> None:
    bypass = _bypass(_plan(plugin=_Undescribed()))
    assert bypass.reason == PROJECTION_BYPASS_REASON


def test_a_provider_rule_table_that_raises_does_not_participate() -> None:
    bypass = _bypass(_plan(plugin=_BrokenRules()))
    assert bypass.reason == "provider_rule_set"


def test_an_unknown_caller_parameter_does_not_participate() -> None:
    assert _bypass(_plan(_body(nonesuch=1))).reason == "unknown_parameter"


# --- a native value the projection does not describe (BYPASS_UNPROJECTED_NATIVE) --


class _UnprojectedNative(_Plugin):
    """Keys a ``provider_params`` field into a root its projection never describes.

    The rule targets ``routing.mode``, so the projected root is ``routing`` — and
    ``_Plugin.global_cache_projection`` returns a ``prepared`` containing only
    ``api_base``. That is a provider whose two halves disagree: it accepts and keys a
    native value, then fails to report where the value went.
    """

    custom_llm_provider = "unprojected"

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        return (
            provider_native_rule(
                "provider_params.mode",
                provider_target="routing.mode",
                auth_modes=_AUTH,
                projection_revision="rule-native-1",
                schema=ParameterSchema(type="string", enum=("fast",)),
                cache_behavior="keyed",
            ),
        )


def test_a_keyed_native_value_whose_root_the_projection_omits_makes_the_request_unkeyable() -> None:
    """``BYPASS_UNPROJECTED_NATIVE`` — the fail-safe for a self-inconsistent provider.

    INVARIANT: an accepted provider-native value participates in the key ONLY through
    the projection. A native rule contributes NO entry of its own (``_accept`` returns
    ``entry={}`` for native rules) — it contributes a projected ROOT that the
    projection is then expected to describe. If the root is missing, the value the
    caller sent is invisible to the key while still changing what is dispatched, which
    is the wrong-hit shape: two callers sending different ``mode`` values would share
    one entry.

    WHY a bypass rather than a raise or an assertion: this is third-party-shaped code
    on the request path. Refusing to cache costs an entry; failing the request would
    cost the answer, and keying anyway would cost correctness.
    """
    bypass = _bypass(_plan(_body(provider_params={"mode": "fast"}), plugin=_UnprojectedNative()))
    assert bypass.reason == BYPASS_UNPROJECTED_NATIVE


def test_that_same_provider_still_caches_a_request_that_omits_the_native_value() -> None:
    # Anti-vacuity, and the same per-path granularity the mode-restriction guard has:
    # the root is only claimed when a rule actually ACCEPTS a value, so a provider with
    # an undescribed root still caches every request that does not use it. Without this
    # the test above would also pass if the guard disabled the provider wholesale.
    _key(_plan(plugin=_UnprojectedNative()))


def test_the_unprojected_guard_is_what_refuses_and_not_the_absence_of_a_schema() -> None:
    # The same body against the same rule table is KEYABLE once the projection
    # describes the root — so the refusal above is attributable to the missing root
    # alone, not to the wrapper, the schema or the native projection kind.
    class _Describes(_UnprojectedNative):
        custom_llm_provider = "describes"

        def global_cache_projection(self, body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
            return {
                "resolved_model": "m",
                "provider_adapter_revision": _ADAPTER_REVISION,
                "prepared": {"api_base": "https://example.invalid/v1", "routing": {"mode": "fast"}},
            }

    _key(_plan(_body(provider_params={"mode": "fast"}), plugin=_Describes()))


# --- a parameter that is not offered in every auth mode (ruling 33) -----------


def test_a_parameter_the_provider_offers_in_only_some_modes_does_not_participate() -> None:
    # INVARIANT: the key cannot see which auth mode the caller will resolve to, so a
    # path that only EXISTS in one mode may never be keyed. Keyed, an api-key caller
    # could fill an entry using a parameter an OAuth caller is not offered, and that
    # OAuth caller would be served a 200 hit for a request the miss path refuses.
    #
    # WHY this is not the approved validation-skip trade-off: that one is about an
    # invalid VALUE. This is availability — the parameter is not on offer at all.
    bypass = _bypass(_plan(_body(temperature=0.7), plugin=_ModeRestricted()))
    assert bypass.reason == "mode_restricted_parameter"


def test_the_same_provider_still_caches_requests_that_omit_that_parameter() -> None:
    # Granularity is PER PATH, not per provider: one mode-restricted parameter costs
    # this request its entry, not every request to the provider. Without this the
    # guard would silently disable caching for any provider having one such rule.
    _key(_plan(plugin=_ModeRestricted()))


def test_the_provider_mode_set_is_not_derived_from_the_rules_themselves() -> None:
    """The guard must consult provider METADATA, never a summary of the rule set.

    AIDEV-NOTE: this is the anti-vacuity test for ruling 33. Deriving the mode set
    as the union of ``applicable_auth_modes`` across the rules is self-satisfying —
    with every rule api-key-only the union is ``{"api_key"}``, so "applicable in all
    modes" is vacuously TRUE for all of them and the guard silently does nothing.
    ``_ModeRestricted`` has exactly that rule set, so a union-derived guard would let
    it participate; a metadata-driven one refuses it.
    """
    restricted = _ModeRestricted()
    rule_union = {mode for rule in (_TEMPERATURE,) for mode in rule.applicable_auth_modes}
    assert rule_union == {"api_key"}
    # The provider genuinely offers more than its rules cover — the gap IS the hazard.
    assert set(restricted.available_auth_modes()) > rule_union
    _bypass(_plan(_body(temperature=0.7), plugin=restricted))


@pytest.mark.parametrize(
    "body",
    [
        {"messages": [{"role": "user", "content": "hi"}]},
        {"model": "", "messages": []},
        {"model": 7, "messages": []},
        {"model": None, "messages": []},
    ],
)
def test_a_body_without_a_usable_model_does_not_participate(body: dict[str, Any]) -> None:
    # The route rejects these before the stage runs; the planner must still be
    # total, because a bypass is the only answer it is allowed to give.
    assert _bypass(_plan(body)).reason == "unsupported_shape"


def test_streaming_requests_do_not_participate() -> None:
    assert _bypass(_plan(_body(stream=True))).reason == "stream"


def test_a_tool_bearing_request_without_a_declared_rule_does_not_participate() -> None:
    # OME-782 (owner decision D1): tools/tool_choice presence no longer bypasses the
    # cache unconditionally — ``_Plugin`` here declares no ``tools``/``tool_choice``
    # rule at all, so this still does not participate, but now for the same reason
    # as any other undeclared parameter, not a tool-specific one. See
    # test_global_cache_tool_requests.py for the keyed case on a provider that DOES
    # declare function-calling rules.
    tools = _plan(_body(tools=[{"type": "function", "function": {"name": "f"}}]))
    assert _bypass(tools).reason == "unknown_parameter"


# --- the plan is unambiguous ---------------------------------------------------


@pytest.mark.parametrize(
    "decision",
    [
        _plan(),
        _plan(cache_enabled=False),
        _plan(controls=parse_global_cache_controls({"cache": {"use-cache": False}})),
        _plan(plugin=_Undescribed()),
        _plan(_body(nonesuch=1)),
    ],
)
def test_exactly_one_of_key_and_reason_is_populated(decision: GlobalCacheDecision) -> None:
    if isinstance(decision, CacheBypass):
        assert decision.reason
        assert not hasattr(decision, "key_hash")
    else:
        assert isinstance(decision, GlobalCacheKeyResult)
        assert decision.key_hash
        assert not hasattr(decision, "reason")


# --- the provider participation gate (OME-305 review, MEDIUM-1) ----------------


class _SwitchedOff(_Plugin):
    """A provider an operator has turned off. Everything else about it is unchanged."""

    custom_llm_provider = "switched-off"

    def participates_in_global_cache(self, model: object = None) -> bool:
        # OME-884: mechanical signature adaptation. The port now receives the raw
        # requested model; this double still ignores it and still declines.
        del model
        return False


class _BrokenGate(_Plugin):
    """A provider whose participation hook raises — same hazard class as _BrokenRules."""

    custom_llm_provider = "broken-gate"

    def participates_in_global_cache(self, model: object = None) -> bool:
        # OME-884: mechanical signature adaptation; the hazard under test is unchanged.
        del model
        raise RuntimeError("boom")


def test_a_provider_that_declines_to_participate_yields_no_key() -> None:
    # WHY the plan is where this is enforced: the cache stage runs before model
    # resolution and before credentials, so a provider's dispatch-side guards cannot
    # stop a STORED row from being replayed. A row needs neither to be served.
    _bypass(_plan(plugin=_SwitchedOff()))
    # Non-vacuous: the identical request DOES participate for a provider that has not
    # declined, so the refusal is owed to the gate and not to an unkeyable request.
    _key(_plan())


def test_declining_to_participate_is_reported_as_a_provider_reason() -> None:
    # NOT ``disabled``: that value is re-interpreted by
    # ``chat_cache_stage._closed_gate_reason``, which maps it to ``cache_unavailable``
    # whenever the cache's own switch is on — blaming a healthy store for a provider
    # an operator turned off. Measured, not assumed; see the route-level test.
    bypass = _bypass(_plan(plugin=_SwitchedOff()))
    assert bypass.reason == PROJECTION_BYPASS_REASON
    assert bypass.reason != BYPASS_DISABLED


def test_a_participation_hook_that_raises_fails_to_bypass() -> None:
    # INVARIANT (this module's TOTAL claim): a provider hook is third-party-shaped code
    # on a path that must never fail a request. It costs a bypass, never a 500 — and it
    # fails CLOSED, because a hook that cannot answer has not granted participation.
    bypass = _bypass(_plan(plugin=_BrokenGate()))
    assert bypass.reason == PROJECTION_BYPASS_REASON


def test_a_provider_participates_by_default() -> None:
    # BOUNDARY on the port default. It must be True: the gate is opt-OUT, so a
    # provider that never heard of it keeps caching. Flipping this default to False
    # would silently un-cache every provider that has implemented a projection.
    assert ProviderPluginBase.participates_in_global_cache(_Plugin()) is True
    assert _Plugin().participates_in_global_cache() is True


def test_the_plan_result_is_exactly_a_key_or_a_bypass() -> None:
    assert isinstance(_plan(), GlobalCacheKeyResult)
    assert isinstance(_plan(cache_enabled=False), CacheBypass)


# --- the model-aware participation port (OME-884) -----------------------------


class _ModelRecordingGate(_Plugin):
    """Records exactly what the participation port was handed."""

    custom_llm_provider = "model-recording"

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[object] = []

    def participates_in_global_cache(self, model: object = None) -> bool:
        self.seen.append(model)
        return True


def test_the_participation_hook_receives_the_raw_requested_model() -> None:
    """OME-884: the ONE fact the gate may see beyond deployment-local state.

    WHY the port needs it at all: an ambient ``litellm.model_alias_map`` entry silently
    REDIRECTS one model to another, so a stored row for the requested id would be
    replayed while a miss would dispatch something else entirely. That is a per-MODEL
    hazard, and a model-free gate could only answer it by disabling the whole provider.

    INVARIANT: the RAW value, exactly as the caller sent it — not a resolved, prefixed,
    stripped or validated form. Nothing else about the request crosses this port: no
    body, no account, no auth mode, no credential, no settings.
    """
    plugin = _ModelRecordingGate()
    _key(_plan(plugin=plugin))

    assert plugin.seen == [_MODEL]


def test_the_participation_hook_is_consulted_before_the_model_shape_is_adjudicated() -> None:
    # The gates are deliberately NOT reordered by OME-884. Participation still runs
    # ahead of the ``is_text`` shape check, so a body whose model is not a string still
    # reaches the gate — with that raw value — and the hook must be total over it.
    plugin = _ModelRecordingGate()
    body = _body()
    body["model"] = 7

    _bypass(_plan(body, plugin=plugin))

    assert plugin.seen == [7]


def test_a_provider_that_ignores_the_model_is_unaffected() -> None:
    # The default implementation and every provider that does not care must keep
    # participating: OME-884 widened the port, it did not add a duty.
    assert ProviderPluginBase.participates_in_global_cache(_Plugin(), _MODEL) is True
    assert _Plugin().participates_in_global_cache(_MODEL) is True
