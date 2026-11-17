"""OME-1946 — an upstream 415 on an image request is the typed content-part refusal.

STORY: a Hugging Face router call to `moonshotai/Kimi-K3:deepinfra` carrying a GIF came back
`415 {"error":{"message":"Upstream error from DeepInfra: Unsupported media type",...}}`. The
gateway rendered it as a generic `provider_error`, so the url4 caller never learned the model
cannot take that part. It now answers the 422 `unsupported_content_part` refusal the Engine
connector translates to url4 `intent_error` — once (no retry), and never into the cache.
A 415 on a text-only request is not about a part and keeps today's mapping.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from litellm.exceptions import APIError

from aigateway.core.request_cache import RequestCacheWrite

_CHAT_PATH = "/v1/chat/completions"
_PATCH_TARGET = (
    "aigateway.plugins.huggingface_provider.plugin.HuggingFaceProviderPlugin.chat_completion"
)
_MODEL = "huggingface/moonshotai/Kimi-K3:deepinfra"
_HF_KEY = "hf_route_media_415_key_1234567890abcd"
_GIF = {"type": "image_url", "image_url": {"url": "data:image/gif;base64,R0lGODlhAQABAAAAACw="}}
_UPSTREAM = "Upstream error from DeepInfra: Unsupported media type"


class _Rejecting:
    """The upstream: every dispatch answers the DeepInfra 415, as LiteLLM raises it."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _body: dict[str, Any]) -> Any:
        self.calls += 1
        raise APIError(
            status_code=415,
            message=f"HuggingfaceException - {_UPSTREAM}",
            llm_provider="huggingface",
            model=_MODEL,
        )


class _MemoryStore:
    def __init__(self) -> None:
        self.set_calls: list[RequestCacheWrite] = []

    def cache_available(self) -> bool:
        return True

    async def get(self, _key_hash: str) -> dict[str, Any] | None:
        return None

    async def set_if_absent(self, entry: RequestCacheWrite) -> str:
        self.set_calls.append(entry)
        return "stored"


@pytest.fixture
def hf_client(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> TestClient:
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self: Any, _plugin: Any, _provider: str, _api_key: str) -> Any:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    resp = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert resp.status_code == 200, resp.text
    client.headers.update({"Authorization": f"Bearer {resp.json()['token']}"})
    resp = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "huggingface", "api_key": _HF_KEY, "label": "hf"},
    )
    assert resp.status_code == 201, resp.text
    return client


def _send(client: TestClient, content: Any) -> tuple[Any, _Rejecting, _MemoryStore]:
    store = _MemoryStore()
    cast(Any, client.app).state.request_cache_store = store
    upstream = _Rejecting()
    with patch(_PATCH_TARGET, upstream):
        resp = client.post(
            _CHAT_PATH,
            json={"model": _MODEL, "messages": [{"role": "user", "content": content}]},
        )
    return resp, upstream, store


def test_a_415_on_an_image_request_is_the_content_part_refusal(hf_client: TestClient) -> None:
    resp, upstream, store = _send(hf_client, [{"type": "text", "text": "what is this?"}, _GIF])

    assert resp.status_code == 422, resp.text
    # The exact `detail` the Engine connector reads (`_refusal_detail` -> `intent_error_for`).
    assert resp.json()["detail"] == {
        "code": "unsupported_content_part",
        "provider": "huggingface",
        "part_type": "image_url",
        "reason": "provider_unsupported_media image/gif",
        "message": (
            "huggingface cannot accept a image_url content part: "
            "provider_unsupported_media image/gif"
        ),
    }
    assert upstream.calls == 1, "a 415 refusal must not be retried"
    assert store.set_calls == [], "a refusal must never be cached"


def test_a_415_on_a_text_only_request_keeps_the_provider_mapping(hf_client: TestClient) -> None:
    resp, upstream, store = _send(hf_client, "hello")

    assert resp.status_code == 415, resp.text
    assert resp.json()["detail"]["code"] == "provider_error"
    assert upstream.calls == 1
    assert store.set_calls == []


def test_a_plugin_authored_415_on_an_image_request_is_the_refusal_too(
    hf_client: TestClient,
) -> None:
    # The other dispatch-failure branch: a plugin that speaks HTTP itself raises HTTPException.
    from fastapi import HTTPException

    calls: list[int] = []

    async def _raise(_self: Any, _body: dict[str, Any]) -> Any:
        calls.append(1)
        raise HTTPException(status_code=415, detail={"code": "provider_error"})

    cast(Any, hf_client.app).state.request_cache_store = _MemoryStore()
    with patch(_PATCH_TARGET, _raise):
        resp = hf_client.post(
            _CHAT_PATH,
            json={"model": _MODEL, "messages": [{"role": "user", "content": ["look", _GIF]}]},
        )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "unsupported_content_part"
    assert calls == [1]
