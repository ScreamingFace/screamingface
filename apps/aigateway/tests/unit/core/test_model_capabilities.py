"""Phase 2 (OME-479): canonical model identity + inline /v1/models capabilities.

RED-first for the application-layer composition that turns a provider plugin's
OWN rules/tools/auth-modes into the locked ``/v1/models`` row. Uses lightweight
fake plugins so the mechanism is proven WITHOUT copying any real provider's
inventory (the plan forbids a provider inventory in generic tests).
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.auth_types import AuthType
from aigateway.core.chat_parameters import (
    DuplicateParameterRuleError,
    ParameterProjectionRule,
    ToolCapability,
)
from aigateway.core.model_capabilities import (
    UNSUPPORTED_PARAMETER_BEHAVIOR,
    canonical_model_id,
    model_row,
    parameter_contract_url,
)
from aigateway.core.plugin_base import ModelEntry, PluginSettings, ProviderPluginBase


def _rule(
    request_path: str,
    *,
    auth_modes: tuple[AuthType, ...] = ("api_key",),
) -> ParameterProjectionRule:
    return ParameterProjectionRule(
        request_path=request_path,
        applicable_auth_modes=auth_modes,
        projection_kind="direct",
        cache_behavior="bypass",
        projection_revision="r1",
    )


class _FakePlugin(ProviderPluginBase[PluginSettings]):
    """Minimal plugin stand-in exercising only the capability hooks."""

    def __init__(
        self,
        *,
        provider: str = "faux",
        rules: tuple[ParameterProjectionRule, ...] = (),
        tools: tuple[ToolCapability, ...] = (),
        auth_modes: tuple[AuthType, ...] = ("api_key",),
    ) -> None:
        super().__init__()
        self.custom_llm_provider = provider
        self._rules = rules
        self._tools = tools
        self._auth_modes = auth_modes

    def register_models(self) -> list[ModelEntry]:
        return []

    def chat_parameter_rules(
        self, *, model: str, auth_type: Any = None
    ) -> tuple[ParameterProjectionRule, ...]:
        return self._rules

    def chat_parameter_tools(
        self, *, model: str, auth_type: Any = None
    ) -> tuple[ToolCapability, ...]:
        return self._tools

    def available_auth_modes(self) -> tuple[AuthType, ...]:
        return self._auth_modes


_ENTRY = ModelEntry(model_name="m", litellm_params={})


# --- canonical model identity ------------------------------------------------


@pytest.mark.parametrize(
    "provider,model_name,expected",
    [
        # unprefixed display id gains its provider prefix (AC#1: anthropic).
        ("anthropic", "claude-opus-4-8", "anthropic/claude-opus-4-8"),
        # already-canonical ids pass through unchanged.
        ("ollama", "ollama/llama3:8b", "ollama/llama3:8b"),
        ("openrouter", "openrouter/google/gemini-3.6-flash", "openrouter/google/gemini-3.6-flash"),
        (
            "huggingface",
            "huggingface/openai/gpt-oss-120b:cerebras",
            "huggingface/openai/gpt-oss-120b:cerebras",
        ),
        ("gemini-cli", "gemini-cli/gemini-2.5-flash", "gemini-cli/gemini-2.5-flash"),
        ("codex", "codex/gpt-5.5", "codex/gpt-5.5"),
    ],
)
def test_canonical_model_id_prefixes_only_when_needed(
    provider: str, model_name: str, expected: str
) -> None:
    assert canonical_model_id(custom_llm_provider=provider, model_name=model_name) == expected


def test_canonical_id_never_uses_litellm_transport_prefix() -> None:
    # ollama's litellm model is ollama_chat/<name>, but the public id derives
    # from model_name (ollama/<name>) and must resolve to the 'ollama' plugin.
    canonical = canonical_model_id(custom_llm_provider="ollama", model_name="ollama/llama3:8b")
    assert canonical.split("/", 1)[0] == "ollama"
    assert not canonical.startswith("ollama_chat")


def test_canonical_id_prefix_with_hyphenated_provider_resolves_to_owner() -> None:
    canonical = canonical_model_id(custom_llm_provider="gemini-cli", model_name="gemini-2.5-flash")
    assert canonical == "gemini-cli/gemini-2.5-flash"
    assert canonical.split("/", 1)[0] == "gemini-cli"


# --- same-origin detail URL --------------------------------------------------


def test_parameter_contract_url_is_same_origin_and_percent_encoded() -> None:
    assert parameter_contract_url("codex/gpt-5.5") == "/v1/model-parameters?model=codex%2Fgpt-5.5"
    assert (
        parameter_contract_url("openrouter/google/gemini-3.6-flash")
        == "/v1/model-parameters?model=openrouter%2Fgoogle%2Fgemini-3.6-flash"
    )
    # ':' in HF ids is encoded too, so the query value round-trips to the id.
    assert (
        parameter_contract_url("huggingface/openai/gpt-oss-120b:cerebras")
        == "/v1/model-parameters?model=huggingface%2Fopenai%2Fgpt-oss-120b%3Acerebras"
    )


# --- row composition ---------------------------------------------------------


def test_model_row_emits_locked_hybrid_contract_fields() -> None:
    plugin = _FakePlugin(
        provider="anthropic",
        rules=(
            _rule("temperature", auth_modes=("api_key", "oauth")),
            _rule("max_tokens", auth_modes=("api_key", "oauth")),
        ),
        tools=(
            ToolCapability(
                tool_type="function", provider_support="supported", gateway_status="enabled"
            ),
        ),
        auth_modes=("api_key", "oauth"),
    )
    row = model_row(
        plugin,
        ModelEntry(
            model_name="claude-opus-4-8", litellm_params={"model": "anthropic/claude-opus-4-8"}
        ),
    )
    assert row["id"] == "anthropic/claude-opus-4-8"
    assert row["object"] == "model"
    assert row["owned_by"] == "anthropic"
    assert row["supported_parameters"] == ["max_tokens", "temperature"]  # sorted, deduped
    assert row["supported_tools"] == ["function"]
    assert row["unsupported_parameter_behavior"] == "reject"
    assert UNSUPPORTED_PARAMETER_BEHAVIOR == "reject"
    assert row["parameter_contract_url"] == "/v1/model-parameters?model=anthropic%2Fclaude-opus-4-8"


def test_model_row_summary_excludes_auth_specific_fields() -> None:
    # provider offers BOTH auth modes; a rule enabled for only one is excluded
    # from the conservative profile-independent intersection.
    plugin = _FakePlugin(
        provider="anthropic",
        rules=(
            _rule("temperature", auth_modes=("api_key", "oauth")),
            _rule("reasoning", auth_modes=("api_key",)),
        ),
        auth_modes=("api_key", "oauth"),
    )
    assert model_row(plugin, _ENTRY)["supported_parameters"] == ["temperature"]


def test_model_row_is_empty_when_plugin_declares_no_rules() -> None:
    plugin = _FakePlugin(provider="ollama", auth_modes=())
    row = model_row(
        plugin,
        ModelEntry(
            model_name="ollama/llama3:8b", litellm_params={"model": "ollama_chat/llama3:8b"}
        ),
    )
    assert row["supported_parameters"] == []
    assert row["supported_tools"] == []
    assert row["unsupported_parameter_behavior"] == "reject"
    assert row["id"] == "ollama/llama3:8b"


def test_removing_a_rule_removes_the_summary_entry() -> None:
    # Single-source proof (list side): the summary derives from rules, not a
    # separate inventory, so dropping the rule drops the entry.
    with_rule = _FakePlugin(provider="p", rules=(_rule("temperature"),))
    without = _FakePlugin(provider="p", rules=())
    assert "temperature" in model_row(with_rule, _ENTRY)["supported_parameters"]
    assert "temperature" not in model_row(without, _ENTRY)["supported_parameters"]


def test_model_row_rejects_duplicate_rule_paths() -> None:
    plugin = _FakePlugin(
        provider="p",
        rules=(_rule("temperature"), _rule("temperature", auth_modes=("oauth",))),
    )
    with pytest.raises(DuplicateParameterRuleError):
        model_row(plugin, _ENTRY)
