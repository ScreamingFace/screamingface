"""The gateway modality backstop at the chat route (OME-1807).

# FEATURE: image and file input (OME-1529). Engine admission (OME-1803) is the primary, fail-closed
# refusal for Benchmark runs; this is the gateway backstop for every other caller.
# INVARIANT (owner decision A, 2026-11-02): a media part is refused with the typed 422
# `unsupported_content_part` only when the routed model's PUBLISHED modalities lack its modality
# (`image_url` needs `image`, `file` needs `pdf`). A model with no published evidence passes as
# before — a cold catalog never refuses traffic that works today.
# INVARIANT (owner decision (i)): chat reads a cached catalog snapshot, never refreshes one — the
# refusal costs no catalog dial and no upstream call, and precedes the cache and credentials.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.plugin_base import ModelEntry
from aigateway.plugins.openrouter_provider import plugin as openrouter_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from aigateway.routes import chat as chat_route

_PDF = {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQK"}}
_PNG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}

_IMAGE_ONLY = "openrouter/mistralai/mistral-small-3.2-24b-instruct"
_PDF_CAPABLE = "openrouter/google/gemini-2.5-flash"
_TEXT_ONLY = "openrouter/meta-llama/llama-3.3-70b-instruct"
_UNPUBLISHED = "openrouter/acme/no-architecture"
_CATALOG_ROWS = [
    {
        "id": "mistralai/mistral-small-3.2-24b-instruct",
        "architecture": {"input_modalities": ["text", "image"]},
    },
    {
        "id": "google/gemini-2.5-flash",
        "architecture": {"input_modalities": ["image", "file", "text"]},
    },
    {"id": "meta-llama/llama-3.3-70b-instruct", "architecture": {"input_modalities": ["text"]}},
    {"id": "acme/no-architecture"},
]


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    """The canned OpenRouter catalogue; records every dial."""

    def __init__(self) -> None:
        self._body = json.dumps(
            {"data": _CATALOG_ROWS, "links": {"next": None}, "total_count": len(_CATALOG_ROWS)}
        )
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        return RawResponse(status=200, content_type="application/json", body=self._body)


class _Seams:
    def __init__(self) -> None:
        self.cache: list[str] = []
        self.credentials: list[str] = []
        self.upstream: list[str] = []


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> _Seams:
    """Records any call into the cache stage, credential resolution or the upstream."""
    seen = _Seams()

    async def cache_probe(_request: Any, *, body: dict[str, Any], **_kwargs: Any) -> Any:
        seen.cache.append(body["model"])
        raise HTTPException(status_code=418, detail="reached the cache stage")

    async def credential_probe(_access: Any, **kwargs: Any) -> Any:
        seen.credentials.append(kwargs["provider"])
        raise HTTPException(status_code=404, detail="provider not connected")

    async def upstream_probe(body: dict[str, Any]) -> Any:
        seen.upstream.append(body["model"])
        raise AssertionError("the upstream must not be called")

    monkeypatch.setattr(chat_route, "look_up_global_cache", cache_probe)
    monkeypatch.setattr(chat_route, "_resolve_credential_target", credential_probe)
    monkeypatch.setattr(openrouter_module.PLUGIN, "chat_completion", upstream_probe)
    return seen


def _install_catalog(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> _CatalogClient:
    monkeypatch.setattr(
        openrouter_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    http = _CatalogClient()
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())
    return http


def _warm(client: TestClient) -> None:
    """Fill the snapshot the way production does: through `/v1/models`."""
    assert client.get("/v1/models").status_code == 200


def _chat(client: TestClient, model: str, *parts: dict[str, Any], stream: bool = False) -> Any:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": ["look", *parts]}],
    }
    if stream:
        body["stream"] = True
    return client.post("/v1/chat/completions", json=body)


def _assert_refused(resp: Any, seams: _Seams, *, part_type: str, modality: str) -> None:
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_content_part"
    assert detail["provider"] == "openrouter"
    assert detail["part_type"] == part_type
    assert detail["reason"] == f"modality_unsupported {modality}"
    assert seams.cache == []
    assert seams.credentials == []
    assert seams.upstream == []


@pytest.mark.parametrize("stream", [False, True], ids=["sync", "stream"])
def test_a_pdf_to_an_image_only_openrouter_model_is_refused_before_any_upstream_call(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    seams: _Seams,
    stream: bool,
) -> None:
    http = _install_catalog(authenticated_client, monkeypatch)
    _warm(authenticated_client)
    dials = len(http.dialed)

    resp = _chat(authenticated_client, _IMAGE_ONLY, _PDF, stream=stream)

    _assert_refused(resp, seams, part_type="file", modality="pdf")
    # 422 is the permanent class: the engine connector maps it to a permanent intent_error.
    assert resp.status_code == 422
    # Decision (i): the refusal read the snapshot and dialed nothing.
    assert len(http.dialed) == dials


def test_an_image_to_the_image_only_model_still_passes(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    _warm(authenticated_client)

    resp = _chat(authenticated_client, _IMAGE_ONLY, _PNG)

    assert resp.status_code == 418, resp.text
    assert seams.cache == [_IMAGE_ONLY]


def test_a_pdf_to_a_pdf_capable_model_passes(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    _warm(authenticated_client)

    resp = _chat(authenticated_client, _PDF_CAPABLE, _PDF, _PNG)

    assert resp.status_code == 418, resp.text
    assert seams.cache == [_PDF_CAPABLE]


def test_a_declared_text_only_model_refuses_an_image(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    _warm(authenticated_client)

    resp = _chat(authenticated_client, _TEXT_ONLY, _PNG)

    _assert_refused(resp, seams, part_type="image_url", modality="image")


def test_a_declared_text_only_model_still_takes_text(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    _warm(authenticated_client)

    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={"model": _TEXT_ONLY, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 418, resp.text
    assert seams.cache == [_TEXT_ONLY]


@pytest.mark.parametrize("model", [_UNPUBLISHED, "openrouter/acme/not-in-the-catalog"])
def test_a_model_without_published_modalities_passes_as_before(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams, model: str
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    _warm(authenticated_client)

    resp = _chat(authenticated_client, model, _PDF, _PNG)

    assert resp.status_code == 418, resp.text
    assert seams.cache == [model]


def test_a_cold_catalog_passes_and_is_never_refreshed_by_chat(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    http = _install_catalog(authenticated_client, monkeypatch)

    resp = _chat(authenticated_client, _IMAGE_ONLY, _PDF)

    # Unknown passes (decision A), and chat never fills the snapshot (decision (i)).
    assert resp.status_code == 418, resp.text
    assert seams.cache == [_IMAGE_ONLY]
    assert http.dialed == []


def test_discovery_switched_off_passes(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    cast(FastAPI, authenticated_client.app).state.model_catalog = None

    resp = _chat(authenticated_client, _IMAGE_ONLY, _PDF)

    assert resp.status_code == 418, resp.text


def test_an_admitted_model_with_published_evidence_is_checked(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    model = "openrouter/acme/admitted:free"
    cast(FastAPI, authenticated_client.app).state.admitted_models[model] = ModelEntry(
        model_name=model, litellm_params={"model": model}, input_modalities=("text", "image")
    )

    resp = _chat(authenticated_client, model, _PDF)

    _assert_refused(resp, seams, part_type="file", modality="pdf")


def test_a_text_only_request_is_unchanged(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, seams: _Seams
) -> None:
    _install_catalog(authenticated_client, monkeypatch)
    _warm(authenticated_client)

    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={"model": _IMAGE_ONLY, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 418, resp.text
    assert seams.cache == [_IMAGE_ONLY]


def test_a_family_table_declared_text_only_model_refuses_an_image(
    authenticated_client: TestClient, seams: _Seams
) -> None:
    # OpenAI declares `o3-mini` text-only in its reviewed family table (OME-1537).
    resp = _chat(authenticated_client, "openai/o3-mini", _PNG)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["reason"] == "modality_unsupported image"
    assert seams.cache == []
    assert seams.credentials == []


@pytest.mark.parametrize(
    "model", ["openai/gpt-3.5-turbo", "openai/gpt-4o-mini", "anthropic/claude-haiku-4-5"]
)
def test_family_tables_refuse_nothing_they_do_not_declare(
    authenticated_client: TestClient, seams: _Seams, model: str
) -> None:
    # gpt-3.5 is OUTSIDE OpenAI's table: unknown at the gateway, so it passes as before (A).
    resp = _chat(authenticated_client, model, _PDF, _PNG)

    assert resp.status_code == 418, resp.text
    assert seams.cache == [model]
