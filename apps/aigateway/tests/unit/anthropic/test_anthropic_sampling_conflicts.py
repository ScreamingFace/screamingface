"""Anthropic sampling and forced-tool constraints while thinking is active."""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.auth_types import AuthMode
from aigateway.core.parameter_projection import IncompatibleParametersError
from aigateway.plugins.anthropic_provider.thinking import raise_on_thinking_conflict

_MANUAL = "anthropic/claude-sonnet-4-5"
_ADAPTIVE = "anthropic/claude-sonnet-4-6"
_TOOLS = [
    {
        "type": "function",
        "function": {"name": "calc", "parameters": {"type": "object"}},
    }
]


def _paths(
    body: dict[str, Any], *, model: str = _MANUAL, auth_mode: AuthMode = "api_key"
) -> tuple[str, ...]:
    with pytest.raises(IncompatibleParametersError) as excinfo:
        raise_on_thinking_conflict(body, model=model, auth_mode=auth_mode)
    return excinfo.value.paths


@pytest.mark.parametrize(
    ("field", "value", "request_path"),
    [
        ("temperature", 0.2, "temperature"),
        ("top_k", 40, "provider_params.top_k"),
    ],
)
def test_thinking_rejects_incompatible_sampling_fields(
    field: str, value: Any, request_path: str
) -> None:
    body = {"reasoning_effort": "high", "max_tokens": 8192, field: value}

    assert _paths(body) == tuple(sorted((request_path, "reasoning_effort")))


def test_thinking_restricts_top_p_to_the_documented_window() -> None:
    assert _paths({"reasoning_effort": "high", "max_tokens": 8192, "top_p": 0.949}) == (
        "reasoning_effort",
        "top_p",
    )

    for value in (0.95, 1.0):
        raise_on_thinking_conflict(
            {"reasoning_effort": "high", "max_tokens": 8192, "top_p": value},
            model=_MANUAL,
            auth_mode="api_key",
        )


def test_interleaved_oauth_does_not_exempt_sampling_constraints() -> None:
    body = {
        "reasoning_effort": "high",
        "max_tokens": 128,
        "tools": _TOOLS,
        "temperature": 0.2,
    }

    assert _paths(body, auth_mode="oauth") == ("reasoning_effort", "temperature")


def test_adaptive_thinking_still_applies_the_sampling_window() -> None:
    assert _paths(
        {"reasoning_effort": "high", "max_tokens": 1, "top_p": 0.5},
        model=_ADAPTIVE,
    ) == ("reasoning_effort", "top_p")


@pytest.mark.parametrize(
    "tool_choice",
    ["required", {"type": "function", "function": {"name": "calc"}}],
)
def test_manual_thinking_rejects_forced_tool_choice(tool_choice: Any) -> None:
    body = {
        "reasoning_effort": "high",
        "max_tokens": 8192,
        "tools": _TOOLS,
        "tool_choice": tool_choice,
    }

    assert _paths(body) == ("reasoning_effort", "tool_choice")


def test_non_forced_and_adaptive_tool_choices_remain_legal() -> None:
    for tool_choice in ("auto", "none"):
        raise_on_thinking_conflict(
            {
                "reasoning_effort": "high",
                "max_tokens": 8192,
                "tools": _TOOLS,
                "tool_choice": tool_choice,
            },
            model=_MANUAL,
            auth_mode="api_key",
        )
    raise_on_thinking_conflict(
        {
            "reasoning_effort": "high",
            "max_tokens": 1,
            "tools": _TOOLS,
            "tool_choice": "required",
        },
        model=_ADAPTIVE,
        auth_mode="api_key",
    )
