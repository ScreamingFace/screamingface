"""The data:-only guard through the real chat route (OME-1542).

# FEATURE: image and file input across the gateway (OME-1529).
# INVARIANT: every provider but Codex refuses a remote image/file reference with the typed 422
# BEFORE the cache stage — so a refused request can neither hit nor fill the cache — and before any
# credential is resolved or anything is dispatched. Codex forwards https image URLs (OpenAI fetches
# them, not us) and is the only provider that does.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from aigateway.routes import chat as chat_route

_REMOTE_IMAGE = {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
_REMOTE_FILE = {"type": "file", "file": {"file_id": "https://example.com/a.pdf"}}
_PNG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}

_GUARDED_MODELS = [
    "anthropic/claude-haiku-4-5",
    "ollama/qwen2.5vl:3b",
    "openai/gpt-4o-mini",
    "openrouter/google/gemini-2.5-flash",
    "huggingface/Qwen/Qwen2.5-VL-7B-Instruct",
    "local/qwen2.5vl:3b",
    "gemini-cli/gemini-2.5-flash",
    "antigravity/gemini-3-pro",
]


class _ReachedCache(Exception):
    pass


@pytest.fixture
def cache_probe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replaces the cache stage: records that the request got that far, then stops it with 418."""
    reached: list[str] = []

    async def probe(_request: Any, *, body: dict[str, Any], **_kwargs: Any) -> Any:
        reached.append(body["model"])
        raise HTTPException(status_code=418, detail="reached the cache stage")

    monkeypatch.setattr(chat_route, "look_up_global_cache", probe)
    return reached


def _body(model: str, *parts: Any) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": ["look", *parts]}]}


@pytest.mark.parametrize("model", _GUARDED_MODELS)
@pytest.mark.parametrize("part", [_REMOTE_IMAGE, _REMOTE_FILE], ids=["image", "file"])
def test_a_remote_reference_is_refused_before_the_cache_stage(
    authenticated_client, cache_probe: list[str], model: str, part: dict[str, Any]
) -> None:
    resp = authenticated_client.post("/v1/chat/completions", json=_body(model, part))

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_content_part"
    assert detail["reason"] == "remote_url"
    assert detail["provider"] == model.split("/", 1)[0]
    assert cache_probe == []


@pytest.mark.parametrize("model", _GUARDED_MODELS)
def test_inline_media_passes_the_guard(
    authenticated_client, cache_probe: list[str], model: str
) -> None:
    resp = authenticated_client.post("/v1/chat/completions", json=_body(model, _PNG))

    assert resp.status_code == 418, resp.text
    assert cache_probe == [model]


def test_a_streaming_request_is_refused_too(authenticated_client, cache_probe: list[str]) -> None:
    body = _body("anthropic/claude-haiku-4-5", _REMOTE_IMAGE) | {"stream": True}

    resp = authenticated_client.post("/v1/chat/completions", json=body)

    assert resp.status_code == 422, resp.text
    assert cache_probe == []


def test_codex_forwards_an_https_image_url(authenticated_client, cache_probe: list[str]) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions", json=_body("codex/gpt-5", _REMOTE_IMAGE)
    )

    assert resp.status_code == 418, resp.text
    assert cache_probe == ["codex/gpt-5"]


def test_codex_still_refuses_a_remote_file(authenticated_client, cache_probe: list[str]) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions", json=_body("codex/gpt-5", _REMOTE_FILE)
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "remote_url"
    assert cache_probe == []


def test_only_codex_forwards_remote_image_urls(authenticated_client) -> None:
    registry = authenticated_client.app.state.providers
    forwarding = sorted(
        plugin.custom_llm_provider for plugin in registry.all() if plugin.forwards_remote_image_urls
    )
    assert forwarding == ["codex"]


def test_no_provider_that_forwards_urls_can_key_the_cache(authenticated_client) -> None:
    # INVARIANT (spec §4): a cached request never carries a URL, so URL-keyed entries cannot exist.
    # A forwarding provider must keep the base `global_cache_projection` (always CacheBypass).
    from aigateway.core.plugin_base import ProviderPluginBase

    registry = authenticated_client.app.state.providers
    for plugin in registry.all():
        if plugin.forwards_remote_image_urls:
            assert (
                type(plugin).global_cache_projection is ProviderPluginBase.global_cache_projection
            ), plugin.custom_llm_provider
