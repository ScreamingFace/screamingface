"""Phase 9a (OME-479 §6.3/§9): Gemini enabled rules + generationConfig proof.

FEATURE: Gemini P1 observation overlay — the DISPATCH side. Gemini's own body
builder (``message_adapter.build_generate_content_body``) maps a fixed set of
sampling fields into ``generationConfig``; this phase represents that existing
mapping as gateway rules so the SAME fields the builder honors become
gateway-enabled, and every other caller field fails closed.

STORY: as a caller on either a Gemini API-key or an OAuth (Code Assist) profile,
the sampling params I send (temperature/top_p/max_tokens and native top_k) reach
Gemini's ``generationConfig``; anything the gateway has not reviewed — including a
Gemini-native ``contents`` I try to smuggle — is rejected with a safe 400 before
any credential is read.

INVARIANT (§9 "Projection"): a rule is enabled ONLY with proof the value reaches
the last AIGateway-owned boundary. Here that boundary is
``build_generate_content_body`` itself (OUR code that emits the wire body), pinned
by running the request pipeline exactly as ``routes/chat.py`` +
``plugin.chat_completion`` do — not by asserting a kwarg reached a handler.
INVARIANT: both dispatch paths (direct generateContent and the OAuth Code Assist
envelope) call the SAME builder, so every rule applies under BOTH auth modes —
there is no fabricated auth asymmetry (contrast Anthropic's api-key-only top_k).
INVARIANT (OME-582): ``stop`` is now RULED via the shared union ``STOP_SCHEMA``
(``string | array[string]``); it reaches ``generationConfig`` as ``stopSequences``
under both auth modes, and a wrong-typed array item fails closed as malformed.
"""

from __future__ import annotations

import pytest

from aigateway.core.auth_types import AuthType
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from aigateway.plugins.gemini_provider.message_adapter import build_generate_content_body
from aigateway.plugins.gemini_provider.plugin import GeminiProviderPlugin

_MODEL = "gemini-cli/gemini-2.5-pro"
_MESSAGES = [{"role": "user", "content": "hi"}]
# Mirrors plugin.chat_completion's optional_params harvest: everything top-level
# except these becomes the generationConfig source.
_OPTIONAL_EXCLUDES = {"model", "messages", "api_key", "extra_headers", "timeout"}
_AUTH_MODES: tuple[AuthType, ...] = ("api_key", "oauth")


def _rules(auth_mode: AuthType | None):
    return GeminiProviderPlugin().chat_parameter_rules(model=_MODEL, auth_type=auth_mode)


def _projected(caller_body: dict, *, auth_mode: AuthType) -> dict:
    # The route pipeline (routes/chat.py), minus profile defaults: strip provider
    # controls → fail-closed classify/project → prepare_chat_body.
    plugin = GeminiProviderPlugin()
    projected = classify_and_project_chat_parameters(
        plugin.strip_provider_dispatch_controls(caller_body),
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        auth_mode=auth_mode,
    )
    return plugin.prepare_chat_body(projected)


def _generation_config(caller_body: dict, *, auth_mode: AuthType) -> dict:
    # Reproduces the dispatch harvest: prepared body → optional_params →
    # build_generate_content_body → the generationConfig it emits on the wire.
    prepared = _projected(caller_body, auth_mode=auth_mode)
    optional_params = {k: v for k, v in prepared.items() if k not in _OPTIONAL_EXCLUDES}
    body = build_generate_content_body(prepared["messages"], optional_params)
    return body.get("generationConfig", {})


def test_clean_scalar_params_are_ruled_under_both_modes() -> None:
    for auth_mode in _AUTH_MODES:
        paths = {r.request_path for r in _rules(auth_mode) if auth_mode in r.applicable_auth_modes}
        assert {"temperature", "top_p", "max_tokens", "provider_params.top_k"} <= paths, (
            auth_mode,
            paths,
        )


def test_native_top_k_rule_is_symmetric_across_auth_modes() -> None:
    # Gemini's genuine property: BOTH dispatch paths share build_generate_content_body,
    # so native top_k is enabled under api_key AND oauth (no fabricated asymmetry).
    (rule,) = [r for r in _rules(None) if r.request_path == "provider_params.top_k"]
    assert rule.projection_kind == "provider_native"
    assert rule.target == "top_k"  # projected to the top level the builder reads
    assert set(rule.applicable_auth_modes) == set(_AUTH_MODES)


def test_enabled_scalar_params_reach_generation_config() -> None:
    for auth_mode in _AUTH_MODES:
        config = _generation_config(
            {
                "model": _MODEL,
                "messages": _MESSAGES,
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 128,
            },
            auth_mode=auth_mode,
        )
        # Gemini's builder renames each to its generationConfig key.
        assert config.get("temperature") == 0.7, auth_mode
        assert config.get("topP") == 0.9, auth_mode
        assert config.get("maxOutputTokens") == 128, auth_mode


def test_native_top_k_reaches_generation_config_topK() -> None:
    for auth_mode in _AUTH_MODES:
        prepared = _projected(
            {"model": _MODEL, "messages": _MESSAGES, "provider_params": {"top_k": 40}},
            auth_mode=auth_mode,
        )
        # wrapper consumed; native top_k projected to the top level the harvest reads.
        assert prepared["top_k"] == 40, auth_mode
        assert "provider_params" not in prepared, auth_mode
        config = _generation_config(
            {"model": _MODEL, "messages": _MESSAGES, "provider_params": {"top_k": 40}},
            auth_mode=auth_mode,
        )
        assert config.get("topK") == 40, auth_mode


def test_stop_is_ruled_and_reaches_generation_config_under_both_modes() -> None:
    # OME-582: `stop` is now an ENABLED rule (OpenAI union string | array[string], via
    # the OME-581 schema). It reaches build_generate_content_body's stopSequences under
    # BOTH auth modes — the array form kept, the scalar form wrapped into a list.
    for auth_mode in _AUTH_MODES:
        array_form = _generation_config(
            {"model": _MODEL, "messages": _MESSAGES, "stop": ["\n\n", "END"]},
            auth_mode=auth_mode,
        )
        assert array_form["stopSequences"] == ["\n\n", "END"], auth_mode
        scalar_form = _generation_config(
            {"model": _MODEL, "messages": _MESSAGES, "stop": "STOP"},
            auth_mode=auth_mode,
        )
        assert scalar_form["stopSequences"] == ["STOP"], auth_mode


def test_malformed_stop_fails_closed() -> None:
    # OME-582: the union schema still GUARDS — a non-string array item is malformed and
    # fails closed at classification, never reaching the builder. Enabling a field never
    # means accepting any shape.
    plugin = GeminiProviderPlugin()
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {"model": _MODEL, "messages": _MESSAGES, "stop": [123]},
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
            auth_mode="api_key",
        )
    assert exc.value.rejected == {"stop": "malformed"}


def test_caller_native_contents_is_rejected_fail_closed() -> None:
    # plan step 4 (reject half): a caller cannot smuggle a Gemini-native `contents`
    # array past the gateway — messages→contents is the ONLY supported channel, so a
    # raw `contents` is an unknown field and fails closed before dispatch.
    plugin = GeminiProviderPlugin()
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {
                "model": _MODEL,
                "messages": _MESSAGES,
                "contents": [{"role": "user", "parts": [{"text": "smuggled"}]}],
            },
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
            auth_mode="api_key",
        )
    assert "contents" in exc.value.rejected
    assert exc.value.rejected["contents"] == "unknown"
