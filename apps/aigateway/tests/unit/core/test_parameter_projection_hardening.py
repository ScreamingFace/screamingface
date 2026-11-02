"""Phase 4 (OME-479): fail-closed chat-parameter classification + projection.

FEATURE: the effective parameter contract, dispatch side. The SAME provider
rule set that drives the ``/v1/models`` summary and the ``/v1/model-parameters``
detail decides here which caller-supplied optional parameters are dispatchable,
and projects each accepted value to its provider-body target.

RED-first for the PURE core primitive
``classify_and_project_chat_parameters(body, *, rules, auth_mode)``. No route,
no network, no provider names — fabricated rule sets exercise the algebra so the
mechanism is provider-agnostic (SOLID: a new parameter is one provider-local
rule, never an edit here).

INVARIANT under test: fail closed. Only an enabled rule matching the REAL auth
mode authorizes an optional parameter; unknown / wrong-auth / malformed /
duplicate-channel / non-object-wrapper values reject with HTTP-safe request
paths and never reach the projected dispatch body.
"""

from __future__ import annotations

import pytest

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ParameterSchema,
    inline_supported_parameters,
)
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    _project,
    _TargetCollision,
    classify_and_project_chat_parameters,
    wrapper_path_conflicts,
)

_INT = ParameterSchema(type="integer", minimum=1)
_NUM = ParameterSchema(type="number", minimum=0, maximum=2)


def _direct(
    path: str,
    *,
    auth: tuple[AuthType, ...] = ("api_key",),
    schema: ParameterSchema | None = None,
    target: str | None = None,
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=path,
        applicable_auth_modes=auth,
        projection_kind="direct",
        provider_target=target,
        cache_behavior="bypass",
        projection_revision="r1",
        schema=schema,
    )


def _native(
    path: str,
    target: str,
    *,
    auth: tuple[AuthType, ...] = ("api_key",),
    schema: ParameterSchema | None = None,
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=path,
        applicable_auth_modes=auth,
        projection_kind="provider_native",
        provider_target=target,
        cache_behavior="bypass",
        projection_revision="r1",
        schema=schema,
    )


def _classify(body, rules=(), auth_mode: AuthType = "api_key"):
    return classify_and_project_chat_parameters(body, rules=rules, auth_mode=auth_mode)


# --- required-protocol / gateway-owned / transport (tier a: no rule needed) ---


def test_gateway_owned_and_protocol_fields_pass_without_any_rule() -> None:
    # STORY: as a client I send the ordinary OpenAI envelope with no optional
    # params; it must dispatch even for a provider that declares no rules.
    body = {
        "model": "p/m",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "extra_headers": {"x-trace": "1"},
        "metadata": {"k": "v"},
        "timeout": 30,
    }
    out = _classify(body, rules=())
    assert out == body
    assert out is not body  # a fresh normalized body, never the caller's dict


def test_input_body_is_never_mutated() -> None:
    body = {"model": "p/m", "messages": [], "temperature": 0.5}
    _classify(body, rules=(_direct("temperature", schema=_NUM),))
    assert body == {"model": "p/m", "messages": [], "temperature": 0.5}


# --- enabled rules: direct + provider_native projection ----------------------


def test_enabled_direct_rule_validates_and_keeps_field_top_level() -> None:
    out = _classify(
        {"model": "p/m", "messages": [], "temperature": 0.25},
        rules=(_direct("temperature", schema=_NUM),),
    )
    assert out["temperature"] == 0.25


def test_provider_native_rule_projects_into_dotted_target_and_consumes_wrapper() -> None:
    # INVARIANT: provider_params is consumed key-by-key into the rule target and
    # NEVER splatted — a raw provider_params object can never reach a provider.
    out = _classify(
        {"model": "p/m", "messages": [], "provider_params": {"top_k": 40}},
        rules=(_native("provider_params.top_k", "extra_body.top_k", schema=_INT),),
    )
    assert out["extra_body"] == {"top_k": 40}
    assert "provider_params" not in out
    assert "top_k" not in out  # only under the projected target


def test_direct_rule_may_project_to_a_provider_target() -> None:
    out = _classify(
        {"model": "p/m", "messages": [], "route": "fallback"},
        rules=(_direct("route", target="extra_body.route"),),
    )
    assert out["extra_body"] == {"route": "fallback"}


def test_rule_without_schema_forwards_complex_value_unchanged() -> None:
    # OpenRouter-native routing objects have no scalar schema; a rule with no
    # schema authorizes the path and forwards the value verbatim.
    prefs = {"order": ["anthropic"], "allow_fallbacks": False}
    out = _classify(
        {"model": "p/m", "messages": [], "provider": prefs},
        rules=(_direct("provider"),),
    )
    assert out["provider"] == prefs


# --- fail-closed rejections (HTTP-safe paths, no raw values) ------------------


def test_unknown_top_level_optional_param_rejects() -> None:
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify({"model": "p/m", "messages": [], "banana": 1}, rules=())
    assert exc.value.rejected == {"banana": "unknown"}


def test_unknown_nested_provider_params_key_rejects_with_dotted_path() -> None:
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "provider_params": {"mystery": 1}},
            rules=(_native("provider_params.top_k", "extra_body.top_k", schema=_INT),),
        )
    assert exc.value.rejected == {"provider_params.mystery": "unknown"}


def test_rule_for_a_different_auth_mode_is_wrong_auth_not_unknown() -> None:
    # A path the provider DOES own but only under another auth mode must be
    # distinguishable from a truly unknown path (fail closed either way).
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "temperature": 0.5},
            rules=(_direct("temperature", auth=("oauth",), schema=_NUM),),
            auth_mode="api_key",
        )
    assert exc.value.rejected == {"temperature": "wrong_auth_mode"}


def test_malformed_value_rejects_against_gateway_schema() -> None:
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "temperature": 9},
            rules=(_direct("temperature", schema=_NUM),),
        )
    assert exc.value.rejected == {"temperature": "malformed"}


def test_boolean_never_satisfies_a_numeric_schema() -> None:
    # WHY: bool is a subclass of int; temperature=true must reject, not slip
    # through as 1 (guarded in ParameterSchema.validate_value).
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "temperature": True},
            rules=(_direct("temperature", schema=_NUM),),
        )
    assert exc.value.rejected == {"temperature": "malformed"}


def test_provider_params_must_be_an_object() -> None:
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "provider_params": [1, 2, 3]},
            rules=(_native("provider_params.top_k", "extra_body.top_k", schema=_INT),),
        )
    assert exc.value.rejected == {"provider_params": "not_an_object"}


def test_duplicate_channel_to_the_same_target_rejects() -> None:
    # Two accepted channels resolving to ONE provider-body location must reject
    # rather than silently drop one, in BOTH collision shapes: an occupied leaf,
    # and an intermediate segment blocked by a non-dict.
    #
    # WHY (OME-597): two DISTINCT rules sharing one target can no longer occur —
    # normalize_rules rejects both an exact duplicate target and a PREFIX overlap
    # (`extra_body` vs `extra_body.top_k`) at CONSTRUCTION, proven by the
    # duplicate-provider-target tests in test_chat_parameter_contract.py. A rule
    # also cannot target a gateway-owned field (_check_consistency).
    #
    # AIDEV-NOTE (OME-704): the LAST route that reached this guard through
    # classify_and_project_chat_parameters was one rule addressed twice — via the
    # flat dot-key top-level key AND the wrapper. That key is no longer a caller
    # addressing form at all (see the dotted-alias tests below), so with a valid
    # rule set the guard is now defence in depth and is exercised at its own layer.
    # It is deliberately KEPT: it is the primitive that makes "one target, one
    # writer" true no matter what a future addressing form does.
    occupied_leaf: dict[str, object] = {}
    _project(occupied_leaf, "extra_body.top_k", 40)
    assert occupied_leaf == {"extra_body": {"top_k": 40}}
    with pytest.raises(_TargetCollision):
        _project(occupied_leaf, "extra_body.top_k", 50)

    blocked_container: dict[str, object] = {"extra_body": "not-a-dict"}
    with pytest.raises(_TargetCollision):
        _project(blocked_container, "extra_body.top_k", 40)
    # The blocking value is never overwritten: the guard refuses the write rather
    # than replacing whatever already occupies the path.
    assert blocked_container == {"extra_body": "not-a-dict"}


# --- the wrapper is the ONLY addressing form (OME-704) ------------------------


def test_a_dotted_top_level_key_is_not_a_wrapper_alias() -> None:
    # A provider_native rule's request_path IS the string "provider_params.top_k",
    # so a TOP-LEVEL key spelled that way used to match the rule directly and
    # dispatch — an undocumented second addressing form for every wrapped native
    # field, on every provider, outside the documented contract.
    # INVARIANT: the provider_params OBJECT is the only caller addressing form.
    rules = (_native("provider_params.top_k", "extra_body.top_k", schema=_INT),)
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "provider_params.top_k": 40},
            rules=rules,
        )
    assert exc.value.rejected == {"provider_params.top_k": "unknown"}


def test_a_dotted_top_level_key_rejects_even_when_the_wrapper_is_also_present() -> None:
    # The dotted key is refused on its own terms, so it cannot smuggle a second
    # value in beside a legitimate wrapper entry.
    rules = (_native("provider_params.top_k", "extra_body.top_k", schema=_INT),)
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {
                "model": "p/m",
                "messages": [],
                "provider_params.top_k": 40,
                "provider_params": {"top_k": 50},
            },
            rules=rules,
        )
    assert exc.value.rejected == {"provider_params.top_k": "unknown"}


def test_an_unruled_dotted_top_level_key_also_rejects() -> None:
    # The guard is structural, not rule-dependent: it fires before rule resolution,
    # so a dotted key naming a path NO rule owns rejects the same way. One reason
    # code for one structural mistake.
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "provider_params.mystery": 1},
            rules=(_native("provider_params.top_k", "extra_body.top_k", schema=_INT),),
        )
    assert exc.value.rejected == {"provider_params.mystery": "unknown"}


def test_the_wrapper_form_still_dispatches_after_the_dotted_guard() -> None:
    # The guard must not cost the documented form anything.
    out = _classify(
        {"model": "p/m", "messages": [], "provider_params": {"top_k": 40}},
        rules=(_native("provider_params.top_k", "extra_body.top_k", schema=_INT),),
    )
    assert out["extra_body"] == {"top_k": 40}
    assert "provider_params" not in out


def test_all_rejections_are_reported_together_and_sorted() -> None:
    with pytest.raises(UnsupportedParametersError) as exc:
        _classify(
            {"model": "p/m", "messages": [], "zeta": 1, "alpha": 2, "temperature": 99},
            rules=(_direct("temperature", schema=_NUM),),
        )
    # deterministic, path-sorted; every offending path surfaces at once.
    assert exc.value.rejected == {
        "alpha": "unknown",
        "temperature": "malformed",
        "zeta": "unknown",
    }


# --- single-source consistency: summary path ⇒ dispatchable ------------------


def test_every_summary_path_is_accepted_by_dispatch_for_that_auth_mode() -> None:
    # The cross-projection invariant at the dispatch layer: a path the
    # profile-independent summary advertises is accepted by the classifier for
    # that auth mode, because BOTH read the one rule source.
    rules = (
        _direct("temperature", auth=("api_key", "oauth"), schema=_NUM),
        _direct("max_tokens", auth=("api_key", "oauth"), schema=_INT),
    )
    summary = inline_supported_parameters(rules, available_auth_modes=("api_key", "oauth"))
    assert set(summary) == {"temperature", "max_tokens"}
    body = {"model": "p/m", "messages": [], "temperature": 1.0, "max_tokens": 8}
    out = _classify(body, rules=rules, auth_mode="api_key")
    assert out["temperature"] == 1.0
    assert out["max_tokens"] == 8


# --- wrapper-path agreement (OME-599) ----------------------------------------
#
# INVARIANT: within one provider view a native name is addressed at EXACTLY ONE
# path — never at both its bare name and its provider_params.* path. A provider
# states "this field rides the wrapper" in two hand-synced places (its discovery
# literal and its provider_native rule), and nothing imports one from the other;
# if they drift, the SAME field is described at two paths at once.
#
# WHY a dedicated predicate rather than relying on evidence checks: drift is only
# caught transitively where the rule is ENABLED (there the wrapped entry goes
# unevidenced). In an auth mode where the rule is disabled the field just moves to
# the bare path and nothing complains. This predicate is auth-mode independent.
#
# NOTE this is a DIFFERENT invariant from OME-597's one-rule-per-target: that one
# stops two rules racing to one wire field; this one stops the rule set and the
# evidence set from disagreeing about where a field lives.


def test_bare_and_wrapped_form_of_one_native_is_a_conflict() -> None:
    assert wrapper_path_conflicts({"top_k", "provider_params.top_k"}) == ("top_k",)


def test_wrapped_only_is_coherent() -> None:
    assert wrapper_path_conflicts({"temperature", "provider_params.top_k"}) == ()


def test_bare_only_is_coherent() -> None:
    assert wrapper_path_conflicts({"temperature", "top_k", "max_tokens"}) == ()


def test_no_paths_is_coherent() -> None:
    assert wrapper_path_conflicts(()) == ()


def test_every_conflict_is_reported_sorted_and_deterministic() -> None:
    conflicts = wrapper_path_conflicts(
        [
            "zeta",
            "provider_params.zeta",
            "alpha",
            "provider_params.alpha",
            "provider_params.only_wrapped",
        ]
    )
    assert conflicts == ("alpha", "zeta")


def test_nested_native_under_the_wrapper_does_not_false_positive_on_its_prefix() -> None:
    # WHY: the native name is the WHOLE remainder after the wrapper prefix.
    # "provider_params.a.b" addresses field "a.b", which is NOT the field "a", so a
    # bare "a" alongside it is coherent — a naive first-segment split would flag it.
    assert wrapper_path_conflicts({"a", "provider_params.a.b"}) == ()
    assert wrapper_path_conflicts({"a.b", "provider_params.a.b"}) == ("a.b",)


def test_the_bare_wrapper_key_itself_is_not_treated_as_a_native() -> None:
    # "provider_params" with no dotted suffix addresses the wrapper object, not a
    # native field; it must never be read as a conflict with anything.
    assert wrapper_path_conflicts({"provider_params", "top_k"}) == ()


def test_accepts_any_iterable_and_tolerates_duplicates() -> None:
    # Callers pass the UNION of rule paths and observation paths, which is a plain
    # iterable that may repeat a path; the result must not depend on multiplicity.
    assert wrapper_path_conflicts(["top_k", "top_k", "provider_params.top_k"]) == ("top_k",)
