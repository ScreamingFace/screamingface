"""OME-1537 — Hugging Face router ``architecture.input_modalities`` on ``/v1/models``.

The router catalogue (``router.huggingface.co/v1/models``, census 2026-10-16: 135
rows, every one ``["text"]`` or ``["text", "image"]``) already carries the field the
backend-capability parser reads. This unit reads it for the LISTING too.

INVARIANT: the listing source never changes WHAT is listed — the configured entries
come back verbatim, only enriched. A model absent from the catalogue (or a failed
read, which falls back to seeds) is unknown and reports text-only.
INVARIANT: the source is OFF unless ``AIGW_HUGGINGFACE_LIVE_MODALITIES`` is set —
Hugging Face is always loaded, so a default-on source would dial the router on every
cold ``/v1/models`` listing in every deployment and test.
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.model_capabilities import model_row
from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
from aigateway.plugins.huggingface_provider.discovery import (
    MODELS_URL,
    parse_router_input_modalities,
)
from aigateway.plugins.huggingface_provider.plugin import HuggingFaceProviderPlugin
from aigateway.plugins.huggingface_provider.settings import HuggingFacePluginSettings

_VISION = "google/gemma-3-4b-it"
_TEXT = "openai/gpt-oss-20b"


def _catalog(rows: list[object]) -> dict:
    return {"object": "list", "data": rows}


def _row(model_id: str, modalities: object) -> dict:
    return {
        "id": model_id,
        "architecture": {"input_modalities": modalities, "output_modalities": ["text"]},
        "providers": [{"provider": "deepinfra"}],
    }


class _Client:
    def __init__(self, body: object, *, status: int = 200) -> None:
        self._body = body
        self._status = status
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        return RawResponse(
            status=self._status, content_type="application/json", body=json.dumps(self._body)
        )


def _settings(**overrides: object) -> HuggingFacePluginSettings:
    base: dict[str, object] = {
        "default_models": [
            f"huggingface/{_VISION}:deepinfra",
            f"huggingface/{_TEXT}:deepinfra",
            "huggingface/absent/model",
        ],
        "live_modalities": True,
    }
    base.update(overrides)
    return HuggingFacePluginSettings.model_validate(base)


# ---------------------------------------------------------------- parser


def test_parser_maps_text_and_image_and_drops_the_rest() -> None:
    catalog = _catalog(
        [
            _row(_VISION, ["text", "image"]),
            _row(_TEXT, ["text"]),
            _row("x/av", ["text", "audio", "video"]),
            _row("x/bad", "image"),
            {"id": "x/no-arch"},
            {"architecture": {"input_modalities": ["image"]}},
            "junk",
        ]
    )
    assert parse_router_input_modalities(catalog) == {
        _VISION: ("text", "image"),
        _TEXT: ("text",),
        "x/av": ("text",),
    }


def test_parser_tolerates_a_non_catalogue() -> None:
    assert parse_router_input_modalities([]) == {}
    assert parse_router_input_modalities({"data": "x"}) == {}


def test_parser_refuses_an_oversized_catalogue() -> None:
    with pytest.raises(DiscoveryError):
        parse_router_input_modalities(_catalog([{"id": f"a/{i}"} for i in range(10_001)]))


# ---------------------------------------------------------------- listing source


def test_source_is_off_by_default() -> None:
    plugin = HuggingFaceProviderPlugin(HuggingFacePluginSettings())
    assert plugin.model_discovery_source() is None


@pytest.mark.asyncio
async def test_off_means_not_attempted_and_no_dial() -> None:
    plugin = HuggingFaceProviderPlugin(_settings(live_modalities=False))
    client = _Client(_catalog([]))
    assert await plugin.discover_live_models(client=client) is None
    assert client.dialed == []


@pytest.mark.asyncio
async def test_listing_enriches_the_configured_entries_only() -> None:
    plugin = HuggingFaceProviderPlugin(_settings())
    assert plugin.model_discovery_source() is not None
    client = _Client(_catalog([_row(_VISION, ["text", "image"]), _row(_TEXT, ["text"])]))

    entries = await plugin.discover_live_models(client=client)

    assert client.dialed == [MODELS_URL]
    assert entries is not None
    assert [e.model_name for e in entries] == [e.model_name for e in plugin.register_models()]
    rows = {row["id"]: row["input_modalities"] for row in (model_row(plugin, e) for e in entries)}
    assert rows == {
        f"huggingface/{_VISION}:deepinfra": ["text", "image"],
        f"huggingface/{_TEXT}:deepinfra": ["text"],
        "huggingface/absent/model": ["text"],
    }


@pytest.mark.asyncio
async def test_a_failed_read_propagates_so_the_catalog_falls_back_to_seeds() -> None:
    plugin = HuggingFaceProviderPlugin(_settings())
    with pytest.raises(DiscoveryError):
        await plugin.discover_live_models(client=_Client({"error": "x"}, status=503))


def test_seed_rows_are_text_only() -> None:
    plugin = HuggingFaceProviderPlugin(_settings())
    assert {model_row(plugin, e)["input_modalities"][0] for e in plugin.register_models()} == {
        "text"
    }
    assert all(len(model_row(plugin, e)["input_modalities"]) == 1 for e in plugin.register_models())
