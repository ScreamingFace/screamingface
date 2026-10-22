"""OME-1537 — OpenRouter catalogue ``architecture.input_modalities`` on ``/v1/models``.

Payload shape verified live 2026-10-16 (``GET /api/v1/models?output_modalities=text``):
each row carries ``architecture.input_modalities`` — a list drawn from ``text``,
``image``, ``file``, ``audio``, ``video`` in no fixed order.

INVARIANT: ``file`` maps to ``pdf`` (OpenRouter's PDF guide: PDFs travel as the
``file`` content type and reach a model natively when it supports file input);
audio/video are outside the gateway vocabulary and are dropped; a row with no or
malformed evidence is UNKNOWN and therefore text-only — never vision.
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.model_capabilities import model_row
from aigateway.core.parameter_discovery import RawResponse
from aigateway.plugins.openrouter_provider.live_models import (
    LIVE_MODELS_URL,
    fetch_live_model_catalog,
    fetch_live_model_ids,
    live_listing_entries,
    map_openrouter_modalities,
    parse_page_input_modalities,
)
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings


def _row(model_id: str, modalities: object = None, *, architecture: object = ...) -> dict:
    row: dict[str, object] = {"id": model_id}
    if architecture is not ...:
        row["architecture"] = architecture
    elif modalities is not None:
        row["architecture"] = {"input_modalities": modalities, "output_modalities": ["text"]}
    return row


def _page(
    rows: list[dict], *, next_url: str | None = None, total: int | None = None
) -> RawResponse:
    payload = {
        "data": rows,
        "links": {"next": next_url},
        "total_count": len(rows) if total is None else total,
    }
    return RawResponse(status=200, content_type="application/json", body=json.dumps(payload))


class _RoutingClient:
    def __init__(self, responses: dict[str, RawResponse]) -> None:
        self._responses = responses
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        return self._responses[url]


# ---------------------------------------------------------------- mapping


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["text"], ("text",)),
        (["file", "image", "text"], ("text", "image", "pdf")),
        (["text", "image", "video", "audio"], ("text", "image")),
        (["audio", "file", "image", "text", "video"], ("text", "image", "pdf")),
        (["image"], ("text", "image")),
        ([], None),
        ("text,image", None),
        (None, None),
        ([1, {"x": 1}], None),
    ],
)
def test_map_openrouter_modalities(raw: object, expected: tuple[str, ...] | None) -> None:
    assert map_openrouter_modalities(raw) == expected


def test_parse_page_reads_each_rows_architecture() -> None:
    payload = {
        "data": [
            _row("google/gemini-2.5-flash", ["text", "image", "file", "audio", "video"]),
            _row("mistral/text-only", ["text"]),
            _row("no/architecture"),
            _row("bad/architecture", architecture="vision"),
            _row("bad/list", architecture={"input_modalities": "image"}),
        ],
        "links": {"next": None},
        "total_count": 5,
    }
    assert parse_page_input_modalities(payload) == {
        "google/gemini-2.5-flash": ("text", "image", "pdf"),
        "mistral/text-only": ("text",),
    }


def test_parse_page_tolerates_a_non_envelope() -> None:
    # The strict parser already refused a malformed page; this projection never raises.
    assert parse_page_input_modalities([]) == {}
    assert parse_page_input_modalities({"data": "x"}) == {}
    assert parse_page_input_modalities({"data": ["x", {"id": 3}]}) == {}


# ---------------------------------------------------------------- the walk


@pytest.mark.asyncio
async def test_fetch_catalog_collects_ids_and_modalities_across_pages() -> None:
    second = "/api/v1/models?output_modalities=text&limit=250&offset=250"
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page([_row("a/vision", ["image", "text"])], next_url=second, total=2),
            f"{LIVE_MODELS_URL}&offset=250": _page([_row("b/plain", ["text"])], total=2),
        }
    )
    catalog = await fetch_live_model_catalog(client=client)
    assert catalog.ids == ("a/vision", "b/plain")
    assert catalog.input_modalities == {"a/vision": ("text", "image"), "b/plain": ("text",)}


@pytest.mark.asyncio
async def test_fetch_ids_still_returns_only_the_ids() -> None:
    client = _RoutingClient({LIVE_MODELS_URL: _page([_row("a/x", ["text", "image"])])})
    assert await fetch_live_model_ids(client=client) == ("a/x",)


# ---------------------------------------------------------------- the listing


def test_listing_attaches_evidence_to_discovered_and_operator_entries() -> None:
    settings = OpenRouterPluginSettings(
        enabled=True, default_models=["openrouter/a/vision", "openrouter/c/unlisted"]
    )
    entries = live_listing_entries(
        settings,
        ("a/vision", "b/plain", "d/silent"),
        input_modalities={"a/vision": ("text", "image", "pdf"), "b/plain": ("text",)},
    )
    by_name = {entry.model_name: entry.input_modalities for entry in entries}
    assert by_name == {
        "openrouter/a/vision": ("text", "image", "pdf"),
        "openrouter/c/unlisted": None,
        "openrouter/b/plain": ("text",),
        "openrouter/d/silent": None,
    }


def test_listing_without_evidence_is_unchanged() -> None:
    settings = OpenRouterPluginSettings(enabled=True)
    entries = live_listing_entries(settings, ("a/x",))
    assert [entry.input_modalities for entry in entries] == [None]


@pytest.mark.asyncio
async def test_live_listing_rows_publish_catalogue_modalities() -> None:
    plugin = OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True, live_models=True))
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page(
                [
                    _row("google/gemini-2.5-flash", ["text", "image", "file", "audio"]),
                    _row("qwen/qwen3-coder", ["text"]),
                    _row("x/unknown"),
                ]
            )
        }
    )
    entries = await plugin.discover_live_models(client=client)
    assert entries is not None
    rows = {row["id"]: row["input_modalities"] for row in (model_row(plugin, e) for e in entries)}
    assert rows["openrouter/google/gemini-2.5-flash"] == ["text", "image", "pdf"]
    assert rows["openrouter/qwen/qwen3-coder"] == ["text"]
    assert rows["openrouter/x/unknown"] == ["text"]


def test_seed_fallback_rows_are_text_only() -> None:
    plugin = OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True))
    rows = [model_row(plugin, entry) for entry in plugin.register_models()]
    assert rows
    assert all(row["input_modalities"] == ["text"] for row in rows)
