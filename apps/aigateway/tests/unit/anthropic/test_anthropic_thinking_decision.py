"""OME-640: the provider-local thinking-conflict decision, and the tables under it.

FEATURE: one effective parameter contract. ``raise_on_thinking_conflict`` is the
provider-local predicate the route calls; this file exercises it DIRECTLY across
the full cross-product of model, auth mode, effort, max_tokens and tool use, where
the route-level tests in ``test_anthropic_thinking_conflict`` can only reach a few
combinations each.

INVARIANT: the budget and model tables are DERIVED, never guessed — they are what
the INSTALLED litellm transform actually emits. The pins at the end of this file
are what turn a litellm upgrade that changes the mapping into a red gate instead
of a silent drift in when the constraint applies.

AIDEV-NOTE: ``_TOOLS`` is defined here as well as in the route-level file. The two
are independent fixtures for independent files, matching how every other parameter
test module in this suite carries its own — not a shared constant to keep in sync.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.auth_types import AuthMode
from aigateway.core.parameter_projection import IncompatibleParametersError
from aigateway.core.standard_parameters import REASONING_EFFORT_SCHEMA
from aigateway.plugins.anthropic_provider.parameters import anthropic_chat_parameter_rules
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from aigateway.plugins.anthropic_provider.thinking import (
    INTERLEAVED_BETA_MODELS,
    MANUAL_THINKING_BUDGETS,
    MANUAL_THINKING_MODELS,
    raise_on_thinking_conflict,
)

_TOOLS = [
    {
        "type": "function",
        "function": {"name": "calc", "parameters": {"type": "object", "properties": {}}},
    }
]


# --- the provider-local decision procedure ------------------------------------


@pytest.mark.parametrize(
    ("model", "auth_mode", "effort", "max_tokens", "tools", "conflicts"),
    [
        # manual model, api_key: the budget ladder, at and around each boundary
        ("claude-sonnet-4-5", "api_key", "minimal", 1024, False, True),
        ("claude-sonnet-4-5", "api_key", "minimal", 1025, False, False),
        ("claude-sonnet-4-5", "api_key", "low", 1024, False, True),
        ("claude-sonnet-4-5", "api_key", "low", 1025, False, False),
        ("claude-sonnet-4-5", "api_key", "medium", 2048, False, True),
        ("claude-sonnet-4-5", "api_key", "medium", 2049, False, False),
        ("claude-sonnet-4-5", "api_key", "high", 4096, False, True),
        ("claude-sonnet-4-5", "api_key", "high", 4097, False, False),
        # tools do not help without oauth
        ("claude-sonnet-4-5", "api_key", "high", 128, True, True),
        # oauth needs BOTH the honoring model and tools
        ("claude-sonnet-4-5", "oauth", "high", 128, True, False),
        ("claude-sonnet-4-5", "oauth", "high", 128, False, True),
        ("claude-haiku-4-5", "oauth", "high", 128, True, True),
        ("claude-haiku-4-5", "api_key", "high", 128, False, True),
        # adaptive models are never constrained
        ("claude-opus-4-8", "api_key", "high", 1, False, False),
        ("claude-opus-4-7", "oauth", "high", 1, False, False),
        ("claude-sonnet-4-6", "api_key", "high", 1, False, False),
        # non-triggers
        ("claude-sonnet-4-5", "api_key", "none", 1, False, False),
        ("claude-sonnet-4-5", "api_key", None, 1, False, False),
        ("claude-sonnet-4-5", "api_key", "high", None, False, False),
    ],
)
def test_the_decision_procedure(
    model: str,
    auth_mode: AuthMode,
    effort: str | None,
    max_tokens: int | None,
    tools: bool,
    conflicts: bool,
) -> None:
    body: dict[str, Any] = {}
    if effort is not None:
        body["reasoning_effort"] = effort
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools:
        body["tools"] = _TOOLS

    def _run() -> None:
        raise_on_thinking_conflict(body, model=f"anthropic/{model}", auth_mode=auth_mode)

    if conflicts:
        with pytest.raises(IncompatibleParametersError) as excinfo:
            _run()
        assert excinfo.value.paths == ("max_tokens", "reasoning_effort")
    else:
        _run()


def test_an_empty_tools_array_is_not_tool_use() -> None:
    # An empty array is a syntactically valid `tools` value that engages no tool
    # at all, so it cannot bring interleaved thinking into effect.
    with pytest.raises(IncompatibleParametersError):
        raise_on_thinking_conflict(
            {"reasoning_effort": "high", "max_tokens": 128, "tools": []},
            model="anthropic/claude-sonnet-4-5",
            auth_mode="oauth",
        )


def test_an_unregistered_model_is_not_constrained() -> None:
    # The table is a closed world of REGISTERED models. An id it does not name is
    # left alone rather than guessed at — guessing "manual" would refuse a legal
    # request on a model nobody reviewed.
    raise_on_thinking_conflict(
        {"reasoning_effort": "high", "max_tokens": 1},
        model="anthropic/claude-something-new",
        auth_mode="api_key",
    )


# --- the tables are DERIVED, and drift turns the gate red ----------------------


def test_the_budget_table_matches_the_installed_transform() -> None:
    # INVARIANT: the table is not a guess — it is what the INSTALLED litellm
    # AnthropicConfig actually emits. Pinning it here means a litellm upgrade that
    # changes the mapping fails this test instead of silently drifting the
    # gateway's idea of when the constraint applies.
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    settings = AnthropicPluginSettings()
    registered = [entry.model_name for entry in settings.models]
    efforts = [value for value in (REASONING_EFFORT_SCHEMA.enum or ()) if value != "none"]

    # WHY: litellm 1.94 added `custom_llm_provider` as a required parameter here. It did
    # NOT replace `llm_provider`, which still defaults to "anthropic" — so passing
    # "anthropic" reproduces the pre-upgrade call exactly rather than changing what is
    # being asserted. See OME-735.
    # AIDEV-NOTE: `_map_reasoning_effort` is a litellm PRIVATE method, which is why a
    # routine minor bump breaks this gate. If it breaks again, re-anchor onto the public
    # `litellm.get_optional_params` already used further down this file.
    manual: dict[str, dict[str, int]] = {}
    for model in registered:
        for effort in efforts:
            mapped = AnthropicConfig._map_reasoning_effort(
                effort, model, custom_llm_provider="anthropic"
            )
            assert mapped is not None
            budget = mapped.get("budget_tokens")
            if budget is None:
                assert mapped.get("type") == "adaptive"
                continue
            assert mapped.get("type") == "enabled"
            manual.setdefault(model, {})[effort] = budget

    assert set(manual) == MANUAL_THINKING_MODELS
    for model in manual:
        assert manual[model] == MANUAL_THINKING_BUDGETS, model


def test_disabling_thinking_really_emits_no_budget() -> None:
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    for model in MANUAL_THINKING_MODELS:
        assert (
            AnthropicConfig._map_reasoning_effort("none", model, custom_llm_provider="anthropic")
            is None
        )


def test_litellm_raises_max_tokens_only_when_the_caller_omits_it() -> None:
    # The premise behind "an absent max_tokens never conflicts". If litellm ever
    # stops auto-raising, this fails and the omission branch must be revisited.
    import litellm

    with_max = litellm.get_optional_params(
        model="claude-sonnet-4-5",
        custom_llm_provider="anthropic",
        reasoning_effort="high",
        max_tokens=128,
    )
    without_max = litellm.get_optional_params(
        model="claude-sonnet-4-5",
        custom_llm_provider="anthropic",
        reasoning_effort="high",
    )

    assert with_max["max_tokens"] == 128
    assert with_max["thinking"]["budget_tokens"] == 4096
    assert without_max["max_tokens"] > without_max["thinking"]["budget_tokens"]


def test_every_constrained_model_is_registered() -> None:
    registered = {entry.model_name for entry in AnthropicPluginSettings().models}

    assert MANUAL_THINKING_MODELS <= registered
    assert INTERLEAVED_BETA_MODELS <= MANUAL_THINKING_MODELS


def test_the_interleaved_beta_is_actually_sent_on_the_oauth_path() -> None:
    # The exemption's other premise. If this header ever leaves the OAuth
    # settings, the OAuth branch stops being justified.
    assert "interleaved-thinking-2025-05-14" in AnthropicPluginSettings().beta


def test_the_conflict_fields_project_to_their_request_paths() -> None:
    # The seam reads the PROJECTED body, so it can only see these fields while
    # their rule target equals their request path. If a future rule relocated
    # max_tokens, the check would silently stop firing — this fails first.
    rules = {
        rule.request_path: rule
        for rule in anthropic_chat_parameter_rules(model="anthropic/claude-sonnet-4-5")
    }

    for path in ("reasoning_effort", "max_tokens", "tools"):
        assert rules[path].target == path
