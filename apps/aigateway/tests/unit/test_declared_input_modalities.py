"""OME-1537 — declared input-modality tables for providers without a catalogue field.

Anthropic, Antigravity, Gemini (gemini-cli), Codex and direct OpenAI publish no
per-model modality list the gateway reads, so each plugin declares a reviewed
family table. INVARIANT: a model outside every declared family is unknown and
reports text-only — a new family is never assumed to see.
"""

from __future__ import annotations

import pytest

from aigateway.core.model_capabilities import model_row
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.antigravity_provider.plugin import AntigravityProviderPlugin
from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin
from aigateway.plugins.gemini_provider.plugin import GeminiProviderPlugin
from aigateway.plugins.openai_provider.plugin import OpenAIProviderPlugin

_FULL = ["text", "image", "pdf"]
_TEXT = ["text"]


def _row(plugin: ProviderPluginBase, model_name: str) -> list[str]:
    entry = ModelEntry(model_name=model_name, litellm_params={"model": model_name})
    return model_row(plugin, entry)["input_modalities"]


@pytest.mark.parametrize(
    ("plugin_cls", "model_name", "expected"),
    [
        (AnthropicProviderPlugin, "claude-haiku-4-5", _FULL),
        (AnthropicProviderPlugin, "claude-opus-5", _FULL),
        (AnthropicProviderPlugin, "anthropic/claude-sonnet-4-6", _FULL),
        (AnthropicProviderPlugin, "mystery-model", _TEXT),
        (AntigravityProviderPlugin, "antigravity/gemini-3-flash", _FULL),
        (AntigravityProviderPlugin, "antigravity/claude-sonnet-4-6", _TEXT),
        (GeminiProviderPlugin, "gemini-cli/gemini-2.5-flash", _FULL),
        (GeminiProviderPlugin, "gemini-cli/gemini-3.1-flash-lite", _FULL),
        (GeminiProviderPlugin, "gemini-cli/gemma-3", _TEXT),
        (CodexProviderPlugin, "codex/gpt-5.5", _FULL),
        (CodexProviderPlugin, "codex/gpt-5.3-codex", _FULL),
        (CodexProviderPlugin, "codex/gpt-6-astra", _FULL),
        (CodexProviderPlugin, "codex/o9-preview", _TEXT),
        (OpenAIProviderPlugin, "openai/gpt-4o-mini", _FULL),
        (OpenAIProviderPlugin, "openai/gpt-4.1", _FULL),
        (OpenAIProviderPlugin, "openai/gpt-5-nano", _FULL),
        (OpenAIProviderPlugin, "openai/o3", _FULL),
        (OpenAIProviderPlugin, "openai/o4-mini", _FULL),
        (OpenAIProviderPlugin, "openai/gpt-3.5-turbo", _TEXT),
        (OpenAIProviderPlugin, "openai/o1-mini", _TEXT),
        (OpenAIProviderPlugin, "openai/o3-mini", _TEXT),
    ],
)
def test_declared_family_tables(
    plugin_cls: type[ProviderPluginBase], model_name: str, expected: list[str]
) -> None:
    assert _row(plugin_cls(), model_name) == expected


@pytest.mark.parametrize(
    "plugin_cls",
    [
        AnthropicProviderPlugin,
        AntigravityProviderPlugin,
        GeminiProviderPlugin,
        CodexProviderPlugin,
        OpenAIProviderPlugin,
    ],
)
def test_every_shipped_seed_is_covered_by_its_table(plugin_cls: type[ProviderPluginBase]) -> None:
    # WHY: a seed that silently fell outside its own provider's table would publish
    # text-only for a model the provider documents as multimodal.
    plugin = plugin_cls()
    rows = [model_row(plugin, entry)["input_modalities"] for entry in plugin.register_models()]
    assert rows
    assert all(row == _FULL for row in rows)
