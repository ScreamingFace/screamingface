"""Every provider declares how its inference sends are observed (contract C7).

# FEATURE: Router Recipe extension Unit 5.1 — no provider may serve chat or classification through
# an unobserved inference transport, because the attempt header would then report a false `0`.
# INVARIANT: the table below is the transport inventory recorded in the Unit ledger. A new plugin
# fails here until it is placed in one family and its observer is proven.
"""

from __future__ import annotations

from aigateway.core.loader import load_plugins
from aigateway.core.plugin_base import ProviderPluginBase
from aigateway.core.registry import ProviderRegistry
from aigateway.core.upstream_attempts import LITELLM_HTTP, PLUGIN_HTTP
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.antigravity_provider.plugin import AntigravityProviderPlugin
from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin
from aigateway.plugins.gemini_provider.plugin import GeminiProviderPlugin
from aigateway.plugins.huggingface_provider.plugin import HuggingFaceProviderPlugin
from aigateway.plugins.local_provider.plugin import LocalProviderPlugin
from aigateway.plugins.ollama_provider.plugin import OllamaProviderPlugin
from aigateway.plugins.openai_provider.plugin import OpenAIProviderPlugin
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

INVENTORY: dict[type[ProviderPluginBase], str] = {
    AnthropicProviderPlugin: LITELLM_HTTP,
    OpenRouterProviderPlugin: LITELLM_HTTP,
    HuggingFaceProviderPlugin: LITELLM_HTTP,
    OllamaProviderPlugin: LITELLM_HTTP,
    OpenAIProviderPlugin: PLUGIN_HTTP,
    GeminiProviderPlugin: PLUGIN_HTTP,
    CodexProviderPlugin: PLUGIN_HTTP,
    AntigravityProviderPlugin: PLUGIN_HTTP,
    LocalProviderPlugin: PLUGIN_HTTP,
    RemoteEndpointPlugin: PLUGIN_HTTP,
}


def test_every_loaded_provider_is_in_the_inventory() -> None:
    registry = ProviderRegistry()
    load_plugins(registry)

    loaded = {type(plugin) for plugin in registry.all()}
    assert loaded == set(INVENTORY) - {RemoteEndpointPlugin}


def test_each_provider_declares_its_inventoried_send_path() -> None:
    assert {cls: cls.upstream_send_path for cls in INVENTORY} == INVENTORY


def test_a_provider_that_declares_nothing_has_no_send_path() -> None:
    # WHY no default: a guessed family would hide an unobserved transport behind a false `0`.
    assert ProviderPluginBase.upstream_send_path is None
