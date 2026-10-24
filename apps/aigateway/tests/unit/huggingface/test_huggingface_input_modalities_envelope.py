"""OME-1537 review (HupBaHa 2026-10-20, finding 3) — a malformed HF catalogue envelope.

An HTTP 200 whose document is not ``{"data": [...]}`` (maintenance page, upstream
envelope change) is NOT fresh evidence. The fetch step raises a sanitized
``DiscoveryError("malformed_json")`` so the model catalog keeps serving its last-good
snapshot instead of replacing it with text-only rows for a whole TTL.

INVARIANT: strictness is on the ENVELOPE only; malformed optional per-row fields on an
otherwise valid catalogue stay lenient (that row is unknown -> text-only).
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.model_capabilities import model_row
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
from aigateway.plugins.huggingface_provider.discovery import discover_router_input_modalities
from aigateway.plugins.huggingface_provider.plugin import HuggingFaceProviderPlugin
from aigateway.plugins.huggingface_provider.settings import HuggingFacePluginSettings

_VISION = "google/gemma-3-4b-it"


class _Client:
    def __init__(self, body: object) -> None:
        self.body = body
        self.dials = 0

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dials += 1
        return RawResponse(status=200, content_type="application/json", body=json.dumps(self.body))


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def now(self) -> float:
        return self.t


def _good() -> dict:
    return {
        "object": "list",
        "data": [{"id": _VISION, "architecture": {"input_modalities": ["text", "image"]}}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [{"error": "maintenance"}, [], {"data": "x"}, {"data": None}, "ok", None],
)
async def test_a_malformed_200_envelope_raises_malformed_json(body: object) -> None:
    with pytest.raises(DiscoveryError) as caught:
        await discover_router_input_modalities(client=_Client(body))
    assert caught.value.reason == "malformed_json"


@pytest.mark.asyncio
async def test_a_valid_envelope_with_malformed_rows_stays_lenient() -> None:
    body = {"data": ["junk", {"id": "x/no-arch"}, *_good()["data"]]}
    assert await discover_router_input_modalities(client=_Client(body)) == {
        _VISION: ("text", "image")
    }


@pytest.mark.asyncio
async def test_a_malformed_200_keeps_the_last_good_image_evidence() -> None:
    plugin = HuggingFaceProviderPlugin(
        HuggingFacePluginSettings.model_validate(
            {"default_models": [f"huggingface/{_VISION}:deepinfra"], "live_modalities": True}
        )
    )
    clock = _Clock()
    catalog = ModelCatalog(clock=clock)
    client = _Client(_good())

    first = await catalog.entries_for(plugin, client=client, limits=None)
    assert first is not None
    assert model_row(plugin, first[0])["input_modalities"] == ["text", "image"]

    # Past the 300 s TTL, inside the 3600 s stale window: the refresh gets maintenance.
    clock.t += 301.0
    client.body = {"error": "maintenance"}
    second = await catalog.entries_for(plugin, client=client, limits=None)

    assert client.dials == 2
    assert second is not None
    assert model_row(plugin, second[0])["input_modalities"] == ["text", "image"]
