"""Phase 6c (OME-479 §4.4/§6.1): OpenRouter detail-contract observation overlay.

FEATURE: OpenRouter P0 observation overlay — the detailed /v1/model-parameters
document. Proves the composition the route performs (build_model_parameter_
document over the plugin's OWN rules + observations) surfaces EVERY endpoint-
accepted field with an honest gateway status, from labelled-local evidence and
with NO network.

STORY: as an API consumer, every field OpenRouter accepts is visible here with an
honest gateway status — so I know exactly what I may send. A field the gateway does
not project is visible-but-DISABLED rather than hidden.

INVARIANT (§4.4): an observation NEVER enables a field; only a rule does. An
observed-but-unruled field stays visible-but-rejected (projection_not_implemented).
Since OME-479 closure Unit 2 promoted top_p — the last OpenRouter path that was
observed with no rule — that case is constructed by withholding a rule from the
composer, which isolates the rule as the sole authorizing input.
INVARIANT: no network — the detail endpoint composes from labelled-local evidence.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.auth_types import AuthType
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin

_MODEL = "openrouter/google/gemini-2.0-flash-001"


def _parameters(auth_mode: AuthType = "api_key", *, without: str | None = None) -> dict[str, Any]:
    # Mirrors routes/model_parameters.py verbatim: the SAME plugin hooks, the SAME
    # composer — only the profile resolution (auth_mode) is supplied directly.
    # ``without`` withholds ONE rule while leaving the observations untouched, so a
    # test can construct the observed-but-unruled case for a field that is ruled.
    plugin = OpenRouterProviderPlugin()
    rules = tuple(plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode))
    if without is not None:
        rules = tuple(rule for rule in rules if rule.request_path != without)
    document = build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="openrouter",
        auth_mode=auth_mode,
        scope="account_profile",
        context_identity="acct:test|prof:1",
        rules=rules,
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )
    return document["parameters"]


def test_observed_but_unruled_field_is_visible_but_disabled() -> None:
    # A field accepted by the endpoint (observed) but with NO gateway rule stays
    # visible and honestly disabled.
    #
    # AIDEV-NOTE: `top_p` used to supply this scenario for free — it was the one
    # OpenRouter path observed with no rule. It was promoted (OME-479 closure
    # Unit 2), so the scenario is now CONSTRUCTED by withholding only the RULE
    # while the real observation set stays untouched. Every assertion is the one
    # this test always made; what changed is that the observation is now proven
    # NOT to be what enables a field, instead of merely happening not to.
    top_p = _parameters(without="top_p")["top_p"]
    assert top_p["provider"]["support"] == "supported"
    assert top_p["provider"]["source"] == "openrouter:static"
    assert top_p["gateway"]["status"] == "disabled"
    assert top_p["gateway"]["reason"] == "projection_not_implemented"


def test_promoted_native_param_is_enabled_at_wrapper_path() -> None:
    params = _parameters()
    # the P0 promotion: provider_params.top_k is observed AND ruled → ENABLED, and
    # the bare native name never appears as a parameter.
    assert "top_k" not in params
    top_k = params["provider_params.top_k"]
    assert top_k["gateway"]["status"] == "enabled"
    assert top_k["provider"]["support"] == "supported"
    assert top_k["provider"]["source"] == "openrouter:static"


def test_ruled_and_observed_standard_field_is_enabled_with_evidence() -> None:
    temperature = _parameters()["temperature"]
    assert temperature["gateway"]["status"] == "enabled"
    # carries the observation's evidence, not "unknown/none".
    assert temperature["provider"]["support"] == "supported"
    assert temperature["provider"]["source"] == "openrouter:static"


def test_native_routing_controls_are_absent_from_the_contract() -> None:
    # OME-646: `provider`, `plugins`, `route` and `models` used to be ruled here without
    # a validation schema — the one OpenRouter case of "enabled but carrying no provider
    # evidence". Both halves were the defect: an enabled ordinary parameter must declare
    # a gateway-owned validation schema, and these are fallback/routing controls the task
    # excludes. Unruled AND unobserved, they are absent from the contract entirely, and a
    # caller who sends one gets a named 400 (test_openrouter_security).
    #
    # AIDEV-NOTE: the general property this test used to carry — a ruled-but-unobserved
    # field is enabled with honest unknown/none evidence — is provider-agnostic and lives
    # in core: test_chat_parameter_contract::
    # test_enabled_rule_without_observation_reports_unknown_provider_support.
    params = _parameters()
    for path in ("provider", "plugins", "route", "models"):
        assert path not in params, path


def test_every_endpoint_observed_sampling_field_is_visible_with_a_status() -> None:
    params = _parameters()
    # "expose ALL provider params": each accepted sampling field is visible with a
    # status — enabled when ruled, disabled-but-visible otherwise.
    for path in (
        "temperature",
        "top_p",
        "max_tokens",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "stop",
        "provider_params.top_k",
    ):
        assert path in params, path
    # OME-479 closure Unit 2: top_p is now ruled → enabled; its disabled guard is
    # retired because the installed transform carries it (§9 probe), exactly as the
    # three promotions below retired theirs. It was the LAST observed-but-unruled
    # OpenRouter path, so no "still-unruled" loop remains here — the deliberate
    # construction of that case now lives in
    # test_observed_but_unruled_field_is_visible_but_disabled.
    assert params["top_p"]["gateway"]["status"] == "enabled"
    # …and the disabled REASON is gone rather than left stale beside an enabled
    # status, which would tell a caller the field is unprojected while it dispatches.
    assert "reason" not in params["top_p"]["gateway"]
    # OME-582: stop is now ruled → enabled (still visible in the list above).
    assert params["stop"]["gateway"]["status"] == "enabled"
    # OME-585: seed is now ruled → enabled (still visible in the list above); its
    # disabled guard is retired because the installed transform carries it (§9 proof).
    assert params["seed"]["gateway"]["status"] == "enabled"
    # OME-586: frequency_penalty + presence_penalty are now ruled → enabled; their
    # disabled guards are retired because the installed transform carries them (§9 proof).
    assert params["frequency_penalty"]["gateway"]["status"] == "enabled"
    assert params["presence_penalty"]["gateway"]["status"] == "enabled"


def test_observations_are_labelled_local_not_fabricated_per_model() -> None:
    # every observation surfaced here is labelled-local endpoint evidence; none
    # claims to be live per-model catalog evidence (that arrives via discovery).
    params = _parameters()
    sources = {p["provider"]["source"] for p in params.values()}
    # only labelled-local ("openrouter:static") or rule-only ("none") provenance;
    # never the live "openrouter:models" catalog label without a network fetch.
    #
    # AIDEV-NOTE (OME-704): "openrouter:routing-policy" joined the allowlist. It is
    # a REVIEWED labelled-local label like openrouter:static — a different reviewed
    # SURFACE (routing behaviour vs the model's sampling inventory), deliberately
    # kept distinct so a stale review is attributable. The protection is unchanged:
    # this stays a CLOSED set, so a fabricated or live label still fails, and adding
    # a member is a reviewed act. The live labels are now also asserted directly, so
    # the test states its own invariant instead of only implying it.
    assert sources <= {"openrouter:static", "openrouter:routing-policy", "none"}
    assert sources.isdisjoint({"openrouter:models", "openrouter:openapi"})


# --- OME-583: function calling (tools + tool_choice) overlay -----------------
#
# FEATURE: first-class function calling. OpenRouter is OpenAI-compatible; the installed
# litellm openrouter path forwards both tools[] and tool_choice (§9), so both are ENABLED
# and evidenced from the same labelled-local endpoint source.


def _document(auth_mode: AuthType = "api_key") -> dict[str, Any]:
    plugin = OpenRouterProviderPlugin()
    return build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="openrouter",
        auth_mode=auth_mode,
        scope="account_profile",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )


def test_tools_and_tool_choice_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("tools", "tool_choice"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "openrouter:static", path


def test_tools_section_reports_function_enabled() -> None:
    assert _document()["tools"] == {
        "function": {"provider_support": "supported", "gateway_status": "enabled"}
    }


# --- OME-584: structured output (response_format) overlay --------------------
#
# FEATURE: structured output. OpenRouter is OpenAI-compatible; the installed litellm
# openrouter transform forwards response_format VERBATIM (§9 probe: both json_object and
# json_schema land on the wire unchanged), so it is ENABLED and evidenced from the same
# labelled-local endpoint source.


def test_response_format_is_enabled_with_evidence() -> None:
    entry = _parameters()["response_format"]
    assert entry["gateway"]["status"] == "enabled"
    # carries the observation's evidence, not "unknown/none".
    assert entry["provider"]["support"] == "supported"
    assert entry["provider"]["source"] == "openrouter:static"


# --- OME-585: seed + n sampling controls -------------------------------------
#
# FEATURE: seed (deterministic sampling) + n (number of choices). OpenRouter is
# OpenAI-compatible; the installed litellm openrouter transform forwards both VERBATIM
# (§9 probe), so both are ENABLED and evidenced from the labelled-local endpoint source
# (seed via the sampling observation constant already present; n via a direct observation).


def test_seed_and_n_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("seed", "n"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "openrouter:static", path


# --- OME-586: frequency_penalty + presence_penalty overlay -------------------
#
# FEATURE: repetition controls. OpenRouter is OpenAI-compatible; the installed litellm
# openrouter transform forwards both penalties VERBATIM (§9 probe), so both are ENABLED and
# evidenced from the labelled-local endpoint source (both already in the sampling constant).


def test_frequency_and_presence_penalty_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("frequency_penalty", "presence_penalty"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "openrouter:static", path


# --- OME-595: logprobs + top_logprobs overlay --------------------------------
#
# FEATURE: output introspection. OpenRouter is OpenAI-compatible; the installed litellm
# openrouter transform forwards both fields VERBATIM (§9 probe), so both are ENABLED and
# evidenced from the labelled-local endpoint source (each newly added via a direct
# observation — neither was in the sampling constant before).


def test_logprobs_and_top_logprobs_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("logprobs", "top_logprobs"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "openrouter:static", path


def test_object_reasoning_effort_is_enabled_in_the_detailed_contract() -> None:
    entry = _parameters()["reasoning.effort"]
    assert entry["gateway"]["status"] == "enabled"
    assert entry["schema"] == {
        "type": "string",
        "enum": ["max", "xhigh", "high", "medium", "low", "minimal", "none"],
    }
    assert entry["provider"] == {
        "support": "supported",
        "source": "openrouter:static",
        "stale": False,
        "deprecated": None,
    }
