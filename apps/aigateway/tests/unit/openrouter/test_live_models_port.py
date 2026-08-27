"""OME-972 U3 — the provider port pair and its gating flags.

INVARIANT (zero egress when off): ``enabled=False`` or ``live_models=False``
answers ``None`` from BOTH port hooks without a single transport dial —
``AIGW_OPENROUTER_LIVE_MODELS=false`` restores exactly today's static listing
behavior with no catalog traffic at all.
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.parameter_discovery import RawResponse
from aigateway.core.plugin_base import ModelEntry, PluginSettings, ProviderPluginBase
from aigateway.plugins.openrouter_provider.live_models import (
    LIVE_MODELS_DISCOVERY_SOURCE,
    LIVE_MODELS_URL,
)
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings


class _CountingClient:
    """Records every dial; serves one canned catalog page."""

    def __init__(self, ids: list[str]) -> None:
        # Strict envelope: the live parser requires links.next + total_count.
        self._body = json.dumps(
            {
                "data": [{"id": i} for i in ids],
                "links": {"next": None},
                "total_count": len(ids),
            }
        )
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        return RawResponse(status=200, content_type="application/json", body=self._body)


# ------------------------------------------------------------------- settings


def test_live_models_defaults_on() -> None:
    # INVARIANT (owner decision): live discovery is the DEFAULT — deployments
    # opt OUT via AIGW_OPENROUTER_LIVE_MODELS=false, not in.
    assert OpenRouterPluginSettings().live_models is True


def test_live_models_env_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_OPENROUTER_LIVE_MODELS", "false")
    assert OpenRouterPluginSettings().live_models is False


# ------------------------------------------------------------------- base port


def test_base_port_pair_is_inert() -> None:
    # WHY: providers without live discovery inherit "no source, no fetch" —
    # core consults the port on EVERY provider, so the default must be a
    # clean None/None, never an abstract method.
    class _BarePlugin(ProviderPluginBase[PluginSettings]):
        custom_llm_provider = "bareprov"
        provider_display_name = "Bare"

        def register_models(self) -> list[ModelEntry]:
            return []

    plugin = _BarePlugin(PluginSettings())
    assert plugin.model_discovery_source() is None


@pytest.mark.asyncio
async def test_base_discover_live_models_returns_none() -> None:
    class _BarePlugin(ProviderPluginBase[PluginSettings]):
        custom_llm_provider = "bareprov"
        provider_display_name = "Bare"

        def register_models(self) -> list[ModelEntry]:
            return []

    client = _CountingClient(["a/b"])
    assert await _BarePlugin(PluginSettings()).discover_live_models(client=client) is None
    assert client.dialed == []


# -------------------------------------------------------------------- gating


@pytest.mark.parametrize(
    "settings",
    [
        OpenRouterPluginSettings(enabled=False, live_models=True),
        OpenRouterPluginSettings(enabled=True, live_models=False),
        OpenRouterPluginSettings(enabled=False, live_models=False),
    ],
    ids=["provider-disabled", "live-disabled", "both-disabled"],
)
@pytest.mark.asyncio
async def test_gated_off_means_none_and_zero_dials(settings: OpenRouterPluginSettings) -> None:
    plugin = OpenRouterProviderPlugin(settings)
    client = _CountingClient(["openai/gpt-5"])
    assert plugin.model_discovery_source() is None
    assert await plugin.discover_live_models(client=client) is None
    assert client.dialed == []


# ------------------------------------------------------------------ live path


def test_enabled_plugin_declares_the_pinned_source() -> None:
    plugin = OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True))
    assert plugin.model_discovery_source() is LIVE_MODELS_DISCOVERY_SOURCE


@pytest.mark.asyncio
async def test_discover_live_models_returns_the_finished_merged_listing() -> None:
    # INVARIANT: the provider owns the merge — operator-explicit entries first
    # (colon variant included), then discovered publishable ids sorted; colon
    # variants from the CATALOG are never auto-published.
    plugin = OpenRouterProviderPlugin(
        OpenRouterPluginSettings(
            enabled=True,
            default_models=["openrouter/deepseek/deepseek-chat-v3.1:free"],
        )
    )
    client = _CountingClient(["qwen/qwen3-coder", "openai/gpt-5", "openai/gpt-5:free"])
    entries = await plugin.discover_live_models(client=client)
    assert entries is not None
    assert [e.model_name for e in entries] == [
        "openrouter/deepseek/deepseek-chat-v3.1:free",
        "openrouter/openai/gpt-5",
        "openrouter/qwen/qwen3-coder",
    ]
    assert client.dialed == [LIVE_MODELS_URL]


@pytest.mark.asyncio
async def test_default_seeds_do_not_survive_a_healthy_snapshot() -> None:
    # INVARIANT (snapshot-or-fallback): compiled default seeds are the
    # FALLBACK — with factory-default settings a healthy snapshot IS the
    # listing, so a retired compiled default disappears when upstream is healthy.
    plugin = OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True))
    entries = await plugin.discover_live_models(client=_CountingClient(["openai/gpt-5"]))
    assert entries is not None
    assert [e.model_name for e in entries] == ["openrouter/openai/gpt-5"]
