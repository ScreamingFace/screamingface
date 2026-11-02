"""Phase 4 (OME-479): Anthropic seeds its currently-proven caller parameter.

``reasoning_effort`` is the one optional parameter a client sends bare to
Anthropic today (``should_apply_profile_default("reasoning_effort") is False``,
so it is caller-only), and existing ``test_chat_x_profile`` cases prove it
reaches the Anthropic dispatch body. The fail-closed flip therefore MUST enable
it — this ties the seeded rule to the profile-independent summary so summary,
detail, and dispatch share one source.
"""

from __future__ import annotations

import litellm
import pytest
from litellm.llms.anthropic.chat.transformation import AnthropicConfig

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import inline_supported_parameters
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin


def test_reasoning_effort_is_enabled_across_anthropic_auth_modes() -> None:
    plugin = AnthropicProviderPlugin()
    rules = plugin.chat_parameter_rules(model="anthropic/claude-haiku-4-5", auth_type=None)
    # enabled for BOTH auth modes, so the conservative intersection keeps it.
    summary = inline_supported_parameters(rules, available_auth_modes=("api_key", "oauth"))
    assert "reasoning_effort" in summary


def test_reasoning_effort_schema_accepts_none_and_high() -> None:
    # "none" must pass classification (prepare_chat_body pops it afterwards) and
    # "high" is the ordinary enable value — both proven by test_chat_x_profile.
    plugin = AnthropicProviderPlugin()
    (rule,) = [
        r
        for r in plugin.chat_parameter_rules(model="anthropic/claude-haiku-4-5", auth_type="oauth")
        if r.request_path == "reasoning_effort"
    ]
    assert rule.parameter_schema is not None
    rule.parameter_schema.validate_value("none")
    rule.parameter_schema.validate_value("high")


def test_temperature_is_enabled_for_anthropic() -> None:
    # BOUNDARY PROOF: test_chat_request_cache.py::test_unsupported_field_bypasses
    # sends bare `temperature` to Anthropic and expects DISPATCH (cache-bypass),
    # not rejection — so the fail-closed flip MUST enable temperature too. It is a
    # sampling param, auth-independent, hence enabled under both modes.
    plugin = AnthropicProviderPlugin()
    rules = plugin.chat_parameter_rules(model="anthropic/claude-haiku-4-5", auth_type=None)
    summary = inline_supported_parameters(rules, available_auth_modes=("api_key", "oauth"))
    assert "temperature" in summary
    (rule,) = [r for r in rules if r.request_path == "temperature"]
    assert rule.parameter_schema is not None
    rule.parameter_schema.validate_value(0.7)  # the value the cache test sends


# --- Phase 8 (OME-479 §6.3/§9): widen the proven rule set + installed-transform proof ---
#
# FEATURE: Anthropic P1 observation overlay — the DISPATCH side. Standard sampling
# fields the INSTALLED litellm AnthropicConfig accepts are enabled under both auth
# modes; the Anthropic-NATIVE top_k is enabled for api_key ONLY (§6.3: a field may
# be enabled for API key yet omitted from the OAuth intersection — the OAuth Claude
# Code subscription path's native-param forwarding is uncaptured in v1).
# INVARIANT (§9): a rule is enabled ONLY with proof the field reaches the installed
# final transform — pinned here by running the request pipeline AND the installed
# AnthropicConfig transform, not merely asserting a kwarg reached acompletion.

_MODEL = "anthropic/claude-haiku-4-5"
_UPSTREAM = "claude-haiku-4-5"  # what litellm sees after the anthropic/ prefix strip
_MESSAGES = [{"role": "user", "content": "hi"}]


def _dispatch_body(caller_body: dict, *, auth_mode: AuthType) -> dict:
    # The route pipeline (routes/chat.py), minus profile defaults: strip provider
    # controls → fail-closed classify/project → prepare_chat_body.
    plugin = AnthropicProviderPlugin()
    projected = classify_and_project_chat_parameters(
        plugin.strip_provider_dispatch_controls(caller_body),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        auth_mode=auth_mode,
    )
    return plugin.prepare_chat_body(projected)


def _rules(auth_mode: AuthType | None):
    return AnthropicProviderPlugin().chat_parameter_rules(model=_MODEL, auth_type=auth_mode)


def test_max_tokens_and_top_p_are_enabled_under_both_auth_modes() -> None:
    for auth_mode in ("api_key", "oauth"):
        paths = {r.request_path for r in _rules(auth_mode) if auth_mode in r.applicable_auth_modes}
        assert {"max_tokens", "top_p"} <= paths, (auth_mode, paths)


def test_native_top_k_rule_is_api_key_only() -> None:
    # the genuine proof-level asymmetry: enabled for api_key, unproven for OAuth.
    (rule,) = [r for r in _rules(None) if r.request_path == "provider_params.top_k"]
    assert rule.applicable_auth_modes == ("api_key",)
    assert rule.projection_kind == "provider_native"
    assert rule.target == "top_k"  # provider-native target: top-level for Anthropic


def test_enabled_standard_params_reach_installed_transform() -> None:
    prepared = _dispatch_body(
        {
            "model": _MODEL,
            "messages": _MESSAGES,
            "temperature": 0.5,
            "max_tokens": 128,
            "top_p": 0.9,
        },
        auth_mode="api_key",
    )
    assert prepared["temperature"] == 0.5
    assert prepared["max_tokens"] == 128
    assert prepared["top_p"] == 0.9
    # Installed final transform (litellm AnthropicConfig): all three reach the
    # outbound provider body — pinned against the installed library, not assumed.
    cfg = AnthropicConfig()
    mapped = cfg.map_openai_params(
        non_default_params={"temperature": 0.5, "max_tokens": 128, "top_p": 0.9},
        optional_params={},
        model=_UPSTREAM,
        drop_params=False,
    )
    body = cfg.transform_request(
        model=_UPSTREAM,
        messages=prepared["messages"],
        optional_params=mapped,
        litellm_params={},
        headers={},
    )
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 128
    assert body["top_p"] == 0.9


def test_native_top_k_reaches_transform_via_api_key_path() -> None:
    prepared = _dispatch_body(
        {"model": _MODEL, "messages": _MESSAGES, "provider_params": {"top_k": 40}},
        auth_mode="api_key",
    )
    # provider_params consumed; native top_k projected to the top level.
    assert prepared["top_k"] == 40
    assert "provider_params" not in prepared
    # Full acompletion delivery: get_optional_params forwards native top_k, and the
    # installed transform emits it on the outbound body (§9 last-boundary proof).
    optional = litellm.utils.get_optional_params(
        model=_UPSTREAM, custom_llm_provider="anthropic", top_k=prepared["top_k"]
    )
    assert optional["top_k"] == 40
    body = AnthropicConfig().transform_request(
        model=_UPSTREAM,
        messages=prepared["messages"],
        optional_params=optional,
        litellm_params={},
        headers={},
    )
    assert body["top_k"] == 40


def test_stop_reaches_installed_transform_as_stop_sequences() -> None:
    # OME-582 (§9): the enabled stop rule projects the caller field onto the dispatch
    # body, and the installed AnthropicConfig transform renames it to stop_sequences —
    # pinned against the installed library, not assumed.
    prepared = _dispatch_body(
        {"model": _MODEL, "messages": _MESSAGES, "stop": ["\n\n", "END"]},
        auth_mode="api_key",
    )
    assert prepared["stop"] == ["\n\n", "END"]
    cfg = AnthropicConfig()
    mapped = cfg.map_openai_params(
        non_default_params={"stop": ["\n\n", "END"]},
        optional_params={},
        model=_UPSTREAM,
        drop_params=False,
    )
    body = cfg.transform_request(
        model=_UPSTREAM,
        messages=prepared["messages"],
        optional_params=mapped,
        litellm_params={},
        headers={},
    )
    assert body["stop_sequences"] == ["\n\n", "END"]


def test_native_top_k_is_wrong_auth_mode_under_oauth() -> None:
    # the api-key-only rule is KNOWN to the provider but not applicable under OAuth,
    # so it fails closed as wrong_auth_mode (not "unknown") — proving the contract is
    # auth-mode-aware end to end.
    plugin = AnthropicProviderPlugin()
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {"model": _MODEL, "messages": _MESSAGES, "provider_params": {"top_k": 40}},
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="oauth"),
            auth_mode="oauth",
        )
    assert exc.value.rejected == {"provider_params.top_k": "wrong_auth_mode"}


# --- OME-579: Anthropic temperature enforces its real [0, 1] range -----------
#
# FEATURE: honest parameter contract. Anthropic's Messages API accepts temperature
# in [0, 1] and the installed litellm AnthropicConfig forwards the value with NO
# clamp, so the shared OpenAI-compatible [0, 2] schema over-advertises and lets a
# provider-bound-violating value through. Anthropic MUST advertise + enforce [0, 1],
# rejecting an out-of-range value at classification BEFORE any credential access.


def test_anthropic_temperature_advertises_upper_bound_of_one() -> None:
    (rule,) = [r for r in _rules("api_key") if r.request_path == "temperature"]
    assert rule.parameter_schema is not None
    # provider-local bound, NOT the shared OpenAI-compatible maximum of 2.
    assert rule.parameter_schema.maximum == 1
    rule.parameter_schema.validate_value(1.0)  # inclusive upper bound is valid


def test_anthropic_temperature_above_one_is_rejected_before_dispatch() -> None:
    plugin = AnthropicProviderPlugin()
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {"model": _MODEL, "messages": _MESSAGES, "temperature": 1.5},
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
            auth_mode="api_key",
        )
    # malformed (above maximum) — the fail-closed classifier stops it before the
    # route ever returns to credential access.
    assert exc.value.rejected == {"temperature": "malformed"}


def test_anthropic_temperature_at_one_reaches_the_installed_transform() -> None:
    # boundary: the maximum valid value still projects onto the dispatch body.
    prepared = _dispatch_body(
        {"model": _MODEL, "messages": _MESSAGES, "temperature": 1.0},
        auth_mode="api_key",
    )
    assert prepared["temperature"] == 1.0


def test_api_key_only_native_top_k_is_dropped_from_the_cross_auth_summary() -> None:
    # OME-580 asymmetry lock: the api-key-only native top_k is applicable under the
    # api-key view but MUST be dropped from the cross-auth (api_key ∩ oauth) inline
    # summary. The summary is a conservative SUBSET of any single mode's enabled
    # detail — never an exact-equality that would overclaim an auth-specific field.
    plugin = AnthropicProviderPlugin()
    rules = plugin.chat_parameter_rules(model=_MODEL, auth_type=None)
    cross = inline_supported_parameters(rules, available_auth_modes=("api_key", "oauth"))
    api_key_view = inline_supported_parameters(rules, available_auth_modes=("api_key",))
    assert "provider_params.top_k" not in cross  # intersection drops the api-key-only field
    assert "provider_params.top_k" in api_key_view  # the single-mode view keeps it


@pytest.mark.parametrize("model", ["claude-opus-4-8", "claude-opus-4-7"])
def test_models_without_sampling_support_neither_advertise_nor_rule_it(model: str) -> None:
    # INVARIANT: Anthropic returns 400 for every non-default sampling value on
    # these models, so evidence and authorization must agree that the paths are off.
    plugin = AnthropicProviderPlugin()
    canonical = f"anthropic/{model}"
    ruled = {
        rule.request_path
        for rule in plugin.chat_parameter_rules(model=canonical, auth_type="api_key")
    }
    observed = {
        observation.request_path: observation.support
        for observation in plugin.chat_parameter_observations(model=canonical, auth_type="api_key")
    }

    assert {"temperature", "top_p", "provider_params.top_k"}.isdisjoint(ruled)
    assert observed["temperature"] == "unsupported"
    assert observed["top_p"] == "unsupported"
    assert observed["provider_params.top_k"] == "unsupported"
    assert {"max_tokens", "reasoning_effort", "stop", "tools", "tool_choice"} <= ruled


def test_an_unreviewed_model_does_not_inherit_sampling_rules_or_evidence() -> None:
    plugin = AnthropicProviderPlugin()
    model = "anthropic/claude-future-unreviewed"
    sampling = {"temperature", "top_p", "provider_params.top_k"}

    ruled = {
        rule.request_path for rule in plugin.chat_parameter_rules(model=model, auth_type="api_key")
    }
    observed = {
        observation.request_path
        for observation in plugin.chat_parameter_observations(model=model, auth_type="api_key")
    }

    assert sampling.isdisjoint(ruled)
    assert sampling.isdisjoint(observed)
