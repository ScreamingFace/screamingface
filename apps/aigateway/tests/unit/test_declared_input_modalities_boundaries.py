"""OME-1537 review (HupBaHa 2026-10-20, finding 4) — family boundaries and alias targets.

A declared family key matches only at a FAMILY BOUNDARY: the whole model id, or the
key followed by a delimiter (``-`` ``.`` ``:`` ``@`` ``/`` ``_``). A key that itself
ends in a delimiter (``claude-``) already names its boundary. Without this rule
``gpt-5`` claimed ``gpt-50`` and ``o3`` claimed ``o30`` — unknown models published as
multimodal, violating ``unknown => text``.

Anthropic aliases are operator-configurable (``settings.models``), so the table is
applied to the ROUTED upstream model (``litellm_params["model"]``), not the alias.
"""

from __future__ import annotations

import pytest

from aigateway.core.input_modalities import (
    TEXT_IMAGE_PDF,
    TEXT_ONLY,
    declared_family_modalities,
)
from aigateway.core.model_capabilities import model_row
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin
from aigateway.plugins.openai_provider.plugin import OpenAIProviderPlugin

_FULL = ["text", "image", "pdf"]
_TEXT = ["text"]

_TABLE = (("gpt-5", TEXT_IMAGE_PDF), ("o3", TEXT_IMAGE_PDF), ("claude-", TEXT_IMAGE_PDF))


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5", TEXT_IMAGE_PDF),
        ("gpt-5.1", TEXT_IMAGE_PDF),
        ("gpt-5-mini", TEXT_IMAGE_PDF),
        ("gpt-5:latest", TEXT_IMAGE_PDF),
        ("gpt-5@2026-01-01", TEXT_IMAGE_PDF),
        ("gpt-5_preview", TEXT_IMAGE_PDF),
        ("gpt-50", TEXT_ONLY),
        ("gpt-5x", TEXT_ONLY),
        ("o3", TEXT_IMAGE_PDF),
        ("o3-pro", TEXT_IMAGE_PDF),
        ("o30", TEXT_ONLY),
        ("o3o", TEXT_ONLY),
        ("claude-anything", TEXT_IMAGE_PDF),
        ("claudette", TEXT_ONLY),
    ],
)
def test_family_key_matches_only_at_a_family_boundary(
    model: str, expected: tuple[str, ...]
) -> None:
    assert declared_family_modalities(model, _TABLE) == expected


def _row(plugin: ProviderPluginBase, model_name: str, upstream: str | None = None) -> list[str]:
    entry = ModelEntry(model_name=model_name, litellm_params={"model": upstream or model_name})
    return model_row(plugin, entry)["input_modalities"]


@pytest.mark.parametrize(
    ("plugin_cls", "model_name"),
    [
        (OpenAIProviderPlugin, "openai/gpt-50"),
        (OpenAIProviderPlugin, "openai/o30"),
        (OpenAIProviderPlugin, "openai/o40"),
        (OpenAIProviderPlugin, "openai/gpt-4oo"),
        (OpenAIProviderPlugin, "openai/gpt-4.10"),
        (CodexProviderPlugin, "codex/gpt-50"),
        (CodexProviderPlugin, "codex/gpt-60"),
    ],
)
def test_near_prefix_unknown_models_are_text_only(
    plugin_cls: type[ProviderPluginBase], model_name: str
) -> None:
    assert _row(plugin_cls(), model_name) == _TEXT


def test_anthropic_alias_to_an_unknown_target_is_text_only() -> None:
    assert _row(AnthropicProviderPlugin(), "claude-alias", "anthropic/mystery") == _TEXT


def test_anthropic_friendly_alias_to_a_claude_target_is_multimodal() -> None:
    assert _row(AnthropicProviderPlugin(), "friendly", "anthropic/claude-sonnet-4-6") == _FULL


def test_anthropic_entry_without_a_string_target_falls_back_to_its_name() -> None:
    entry = ModelEntry(model_name="claude-haiku-4-5", litellm_params={})
    assert model_row(AnthropicProviderPlugin(), entry)["input_modalities"] == _FULL
