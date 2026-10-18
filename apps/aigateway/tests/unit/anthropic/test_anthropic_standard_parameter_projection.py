"""Phase 4 (OME-479) §9: the STANDARD optional parameters, through Anthropic.

Anthropic's answer to the §9 parameter set is mostly NO, and that is the point of
this file. Tools and tool_choice (OME-583) are enabled and pinned against the
INSTALLED litellm ``AnthropicConfig`` transform; response_format (OME-584),
seed + n (OME-585), the penalties (OME-586) and logprobs/top_logprobs (OME-595)
are all EXCLUDED, and each one is proved to fail closed before dispatch.

The seeded ``reasoning_effort`` rule, the Phase 8 widened sampling set and the
OME-579 temperature range live in ``test_anthropic_parameter_projection``.

INVARIANT (§9): an excluded parameter is refused BEFORE the provider is reached —
"not ruled" and "rejected at the door" are asserted as one fact per parameter, so
a rule quietly appearing later cannot leave the refusal behind.

AIDEV-NOTE: ``_MODEL`` / ``_UPSTREAM`` / ``_MESSAGES`` / ``_dispatch_body`` /
``_rules`` below are a verbatim copy of the harness in
``test_anthropic_parameter_projection``, deliberately not a shared import — they
are stateless, and a copy keeps each module independently readable and runnable.
"""

from __future__ import annotations

import pytest
from litellm.llms.anthropic.chat.transformation import AnthropicConfig

from aigateway.core.auth_types import AuthType
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin

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


# --- OME-583 (§9): function calling reaches the installed AnthropicConfig transform ---
#
# FEATURE: first-class function calling. tools[] and tool_choice (string AND object) are
# enabled under both auth modes; each is pinned to the INSTALLED litellm AnthropicConfig
# transform — tools[] map to Anthropic {name, input_schema, type:"custom"}, string
# tool_choice → {"type":"auto"}, object tool_choice → {"type":"tool","name":…}. An
# unadvertised tools[].type / object tool_choice.type fails closed at classification.

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
    }
]


def test_tools_and_tool_choice_are_enabled_under_both_auth_modes() -> None:
    for auth_mode in ("api_key", "oauth"):
        paths = {r.request_path for r in _rules(auth_mode) if auth_mode in r.applicable_auth_modes}
        assert {"tools", "tool_choice"} <= paths, (auth_mode, paths)


def test_tools_reach_the_installed_transform_as_custom_tools() -> None:
    prepared = _dispatch_body(
        {"model": _MODEL, "messages": _MESSAGES, "tools": _TOOLS},
        auth_mode="api_key",
    )
    assert prepared["tools"] == _TOOLS  # projected onto the dispatch body verbatim
    # Installed final transform (litellm AnthropicConfig): OpenAI tools[] become
    # Anthropic custom tools — pinned against the installed library, not assumed.
    cfg = AnthropicConfig()
    mapped = cfg.map_openai_params(
        non_default_params={"tools": _TOOLS},
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
    assert body["tools"][0]["name"] == "get_weather"
    assert body["tools"][0]["type"] == "custom"


def test_string_tool_choice_reaches_the_installed_transform() -> None:
    prepared = _dispatch_body(
        {"model": _MODEL, "messages": _MESSAGES, "tools": _TOOLS, "tool_choice": "auto"},
        auth_mode="api_key",
    )
    assert prepared["tool_choice"] == "auto"
    cfg = AnthropicConfig()
    mapped = cfg.map_openai_params(
        non_default_params={"tools": _TOOLS, "tool_choice": "auto"},
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
    # Anthropic's shape for "let the model decide".
    assert body["tool_choice"] == {"type": "auto"}


def test_object_tool_choice_reaches_the_installed_transform() -> None:
    choice = {"type": "function", "function": {"name": "get_weather"}}
    prepared = _dispatch_body(
        {"model": _MODEL, "messages": _MESSAGES, "tools": _TOOLS, "tool_choice": choice},
        auth_mode="oauth",
    )
    assert prepared["tool_choice"] == choice
    cfg = AnthropicConfig()
    mapped = cfg.map_openai_params(
        non_default_params={"tools": _TOOLS, "tool_choice": choice},
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
    # OpenAI named-function choice becomes Anthropic's forced-tool shape.
    assert body["tool_choice"] == {"type": "tool", "name": "get_weather"}


def test_unadvertised_tool_type_is_rejected_before_dispatch() -> None:
    # a tools[].type the provider never advertised fails closed as malformed at
    # classification — before the route returns to credential access.
    plugin = AnthropicProviderPlugin()
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {"model": _MODEL, "messages": _MESSAGES, "tools": [{"type": "web_search"}]},
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
            auth_mode="api_key",
        )
    assert exc.value.rejected == {"tools": "malformed"}


def test_unadvertised_object_tool_choice_type_is_rejected_before_dispatch() -> None:
    plugin = AnthropicProviderPlugin()
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {"model": _MODEL, "messages": _MESSAGES, "tool_choice": {"type": "web_search"}},
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
            auth_mode="api_key",
        )
    assert exc.value.rejected == {"tool_choice": "malformed"}


# --- OME-584 (§9): response_format is EXCLUDED on Anthropic --------------------
#
# The installed AnthropicConfig does NOT carry response_format as response_format:
# {"type":"json_object"} is dropped, and {"type":"json_schema"} is rewritten into a
# synthetic json_tool_call tool + forced tool_choice (§9 probe) — never reaching the wire
# as response_format, and it would collide with the tools channel. So response_format is
# intentionally UNRULED; a caller value fails closed at classification. Pinned by a test
# so the exclusion is deliberate, not accidental omission.


def test_response_format_is_not_ruled_for_anthropic() -> None:
    assert "response_format" not in {r.request_path for r in _rules(None)}


def test_response_format_fails_closed_before_dispatch() -> None:
    plugin = AnthropicProviderPlugin()
    with pytest.raises(UnsupportedParametersError) as exc:
        classify_and_project_chat_parameters(
            {"model": _MODEL, "messages": _MESSAGES, "response_format": {"type": "json_object"}},
            rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
            auth_mode="api_key",
        )
    assert exc.value.rejected == {"response_format": "unknown"}


# --- OME-585 (§9): seed + n are EXCLUDED on Anthropic -------------------------
#
# The installed AnthropicConfig's get_supported_openai_params carries NEITHER seed nor n
# (§9 probe: litellm would drop both), so they have no home on the Anthropic wire. They are
# intentionally UNRULED; a caller value fails closed at classification. Pinned by a test so
# the exclusion is deliberate, not accidental omission.


def test_seed_and_n_are_not_ruled_for_anthropic() -> None:
    ruled = {r.request_path for r in _rules(None)}
    assert "seed" not in ruled
    assert "n" not in ruled


def test_seed_and_n_fail_closed_before_dispatch() -> None:
    plugin = AnthropicProviderPlugin()
    for path, value in (("seed", 42), ("n", 3)):
        with pytest.raises(UnsupportedParametersError) as exc:
            classify_and_project_chat_parameters(
                {"model": _MODEL, "messages": _MESSAGES, path: value},
                rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
                auth_mode="api_key",
            )
        assert exc.value.rejected == {path: "unknown"}


# --- OME-586 (§9): frequency_penalty + presence_penalty are EXCLUDED on Anthropic --
#
# The installed AnthropicConfig's get_supported_openai_params carries NEITHER penalty (§9
# probe: map_openai_params drops both), so they have no home on the Anthropic wire. They are
# intentionally UNRULED; a caller value fails closed at classification. Pinned by a test so
# the exclusion is deliberate, not accidental omission.


def test_penalties_are_not_ruled_for_anthropic() -> None:
    ruled = {r.request_path for r in _rules(None)}
    assert "frequency_penalty" not in ruled
    assert "presence_penalty" not in ruled


def test_penalties_fail_closed_before_dispatch() -> None:
    plugin = AnthropicProviderPlugin()
    for path in ("frequency_penalty", "presence_penalty"):
        with pytest.raises(UnsupportedParametersError) as exc:
            classify_and_project_chat_parameters(
                {"model": _MODEL, "messages": _MESSAGES, path: 0.5},
                rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
                auth_mode="api_key",
            )
        assert exc.value.rejected == {path: "unknown"}


# --- OME-595: logprobs + top_logprobs are UNRULED for Anthropic --------------
#
# The installed AnthropicConfig's get_supported_openai_params carries NEITHER field (§9
# probe: map_openai_params drops both), so they have no home on the Anthropic wire. They are
# intentionally UNRULED; a caller value fails closed at classification. Pinned by a test so
# the exclusion is deliberate, not accidental omission.


def test_logprobs_are_not_ruled_for_anthropic() -> None:
    ruled = {r.request_path for r in _rules(None)}
    assert "logprobs" not in ruled
    assert "top_logprobs" not in ruled


def test_logprobs_fail_closed_before_dispatch() -> None:
    plugin = AnthropicProviderPlugin()
    for path, value in (("logprobs", True), ("top_logprobs", 5)):
        with pytest.raises(UnsupportedParametersError) as exc:
            classify_and_project_chat_parameters(
                {"model": _MODEL, "messages": _MESSAGES, path: value},
                rules=plugin.chat_parameter_rules(model=_MODEL, auth_type="api_key"),
                auth_mode="api_key",
            )
        assert exc.value.rejected == {path: "unknown"}
