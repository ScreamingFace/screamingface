"""Phase 9c (OME-479 §4.4/§Phase 9 step 2): Gemini detail overlay + auth-split evidence.

FEATURE: Gemini P1 observation overlay — the detailed /v1/model-parameters document
AND the profile-independent /v1/models summary, each derived from ONE provider-local
source. Gemini is the first provider whose EVIDENCE varies by auth mode: the public
generativelanguage API publishes a Discovery schema (rich evidence), while the OAuth
Code Assist envelope has none (only the reviewed builder mapping) — so public
Discovery never overclaims OAuth.

STORY: on an api-key connection I can see Gemini's public GenerationConfig surface —
including frequencyPenalty/seed as visible-but-disabled — and that temperature/top_p/
max_tokens/top_k are projected; on an OAuth (Code Assist) connection I see ONLY the
fields the gateway can actually prove reach that envelope, never a public-only field.

INVARIANT (§4.4): an observation NEVER enables a field; only a rule does — `stop` now
has a rule (OME-582), so it is ENABLED (→ stopSequences) under both modes.
INVARIANT (step 2): a public-only field (no OAuth evidence) does NOT appear in the
OAuth contract at all — honest absence, never an overclaimed OAuth capability.
INVARIANT: NO network — the detail endpoint composes from labelled-static evidence.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import inline_supported_parameters
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.plugins.gemini_provider.plugin import GeminiProviderPlugin

_MODEL = "gemini-cli/gemini-2.5-pro"
_DISCOVERY = "gemini:discovery"
_CODE_ASSIST = "gemini:code-assist"
_RULED = ("temperature", "top_p", "max_tokens", "provider_params.top_k")


def _parameters(auth_mode: AuthType) -> dict[str, Any]:
    # Mirrors routes/model_parameters.py: the SAME plugin hooks, the SAME composer —
    # only the profile resolution (auth_mode) is supplied directly.
    plugin = GeminiProviderPlugin()
    document = build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="gemini-cli",
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )
    return document["parameters"]


def test_ruled_fields_enabled_with_discovery_evidence_under_api_key() -> None:
    params = _parameters("api_key")
    for path in _RULED:
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == _DISCOVERY, path


def test_ruled_fields_enabled_with_code_assist_evidence_under_oauth() -> None:
    # SAME rules apply (no auth asymmetry), but the evidence provenance differs:
    # under OAuth the enabled fields carry Code Assist provenance, not Discovery.
    params = _parameters("oauth")
    for path in _RULED:
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == _CODE_ASSIST, path


def test_public_only_fields_are_visible_but_disabled_under_api_key() -> None:
    # the public Discovery surface exposes natives the builder does not yet forward:
    # visible (provider supports) but DISABLED (projection_not_implemented).
    params = _parameters("api_key")
    for path in (
        "provider_params.frequencyPenalty",
        "provider_params.presencePenalty",
        "provider_params.seed",
        "provider_params.candidateCount",
    ):
        entry = params[path]
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == _DISCOVERY, path
        assert entry["gateway"]["status"] == "disabled", path
        assert entry["gateway"]["reason"] == "projection_not_implemented", path


def test_public_only_fields_are_absent_under_oauth() -> None:
    # step 2 / test-matrix "Gemini": public Discovery must not overclaim OAuth. A
    # field with NO Code Assist evidence and no rule simply is not in the contract.
    params = _parameters("oauth")
    for path in (
        "provider_params.frequencyPenalty",
        "provider_params.presencePenalty",
        "provider_params.seed",
        "provider_params.candidateCount",
    ):
        assert path not in params, path


def test_stop_is_enabled_under_both_modes() -> None:
    # OME-582: stop is now RULED, so it is ENABLED under BOTH evidence sets while keeping
    # the observation's provenance (support/source unchanged).
    cases: tuple[tuple[AuthType, str], ...] = (("api_key", _DISCOVERY), ("oauth", _CODE_ASSIST))
    for auth_mode, source in cases:
        entry = _parameters(auth_mode)["stop"]
        assert entry["provider"]["support"] == "supported", auth_mode
        assert entry["provider"]["source"] == source, auth_mode
        assert entry["gateway"]["status"] == "enabled", auth_mode


def test_inline_summary_keeps_symmetric_top_k() -> None:
    # the "no fabricated asymmetry" payoff: top_k is enabled under BOTH modes, so —
    # unlike Anthropic's api-key-only top_k — it stays in the conservative summary.
    plugin = GeminiProviderPlugin()
    summary = set(
        inline_supported_parameters(
            plugin.chat_parameter_rules(model=_MODEL, auth_type=None),
            available_auth_modes=("api_key", "oauth"),
        )
    )
    assert {"temperature", "top_p", "max_tokens", "provider_params.top_k"} <= summary
    assert "stop" in summary  # OME-582: now ruled + enabled under both modes
    assert "provider_params.frequencyPenalty" not in summary  # observed, never ruled


def test_sources_are_auth_scoped_labelled_static_or_rule_only() -> None:
    # under each auth mode every observation carries THAT mode's single label; no
    # cross-contamination between the public and Code Assist evidence sets.
    api_sources = {e["provider"]["source"] for e in _parameters("api_key").values()}
    assert api_sources <= {_DISCOVERY, "none"}
    oauth_sources = {e["provider"]["source"] for e in _parameters("oauth").values()}
    assert oauth_sources <= {_CODE_ASSIST, "none"}


def test_every_public_field_is_visible_with_a_status_under_api_key() -> None:
    # "expose ALL provider params": each labelled public field is visible under
    # api_key with a status — enabled when ruled, disabled-but-visible otherwise.
    params = _parameters("api_key")
    for path in (
        "temperature",
        "top_p",
        "max_tokens",
        "stop",
        "provider_params.top_k",
        "provider_params.frequencyPenalty",
        "provider_params.presencePenalty",
        "provider_params.seed",
        "provider_params.candidateCount",
    ):
        assert path in params, path


# --- OME-583: function calling — Gemini enables tools ONLY (no tool_choice) --------
#
# FEATURE: first-class function calling. Gemini's build_generate_content_body maps
# tools[] → functionDeclarations (§9), so `tools` is ENABLED under both auth modes and
# carries THAT mode's evidence provenance. But the builder emits NO toolConfig, so
# `tool_choice` has no wire home — it stays UNRULED and UNOBSERVED, hence absent from the
# contract (honest: the gateway never advertises a control it cannot honor).


def _document(auth_mode: AuthType) -> dict[str, Any]:
    plugin = GeminiProviderPlugin()
    return build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="gemini-cli",
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )


def test_tools_is_enabled_under_both_modes_with_auth_scoped_evidence() -> None:
    cases: tuple[tuple[AuthType, str], ...] = (("api_key", _DISCOVERY), ("oauth", _CODE_ASSIST))
    for auth_mode, source in cases:
        entry = _parameters(auth_mode)["tools"]
        assert entry["gateway"]["status"] == "enabled", auth_mode
        assert entry["provider"]["support"] == "supported", auth_mode
        assert entry["provider"]["source"] == source, auth_mode


def test_tool_choice_is_absent_under_both_modes() -> None:
    # §9: the builder emits no toolConfig, so tool_choice is neither ruled nor observed —
    # it must NOT appear in the contract at all (honest absence, never disabled-but-listed).
    for auth_mode in ("api_key", "oauth"):
        assert "tool_choice" not in _parameters(auth_mode), auth_mode


def test_tools_section_reports_function_enabled() -> None:
    tools_section = _document("api_key")["tools"]
    assert tools_section == {
        "function": {"provider_support": "supported", "gateway_status": "enabled"}
    }


def test_tools_in_summary_but_tool_choice_absent() -> None:
    plugin = GeminiProviderPlugin()
    summary = set(
        inline_supported_parameters(
            plugin.chat_parameter_rules(model=_MODEL, auth_type=None),
            available_auth_modes=("api_key", "oauth"),
        )
    )
    assert "tools" in summary
    assert "tool_choice" not in summary
