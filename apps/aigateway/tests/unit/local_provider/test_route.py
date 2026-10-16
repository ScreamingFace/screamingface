from __future__ import annotations

import json
from typing import cast

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.plugins.local_provider import plugin as plugin_module
from aigateway.plugins.local_provider.settings import LocalPluginSettings


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        del timeout_s, max_bytes
        assert url == "http://127.0.0.1:1234/v1/models"
        return RawResponse(
            status=200,
            content_type="application/json",
            body=json.dumps({"object": "list", "data": [{"id": "fixture:model"}]}),
        )


def _install_catalog(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=_CatalogClient(),
        cache=ObservationCache(
            clock=_Clock(),
            limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8),
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())


def test_models_and_chat_routes_use_the_local_provider(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    async def upstream(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:1234/v1/chat/completions"
        assert json.loads(request.content)["model"] == "fixture:model"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-local",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture:model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(plugin_module.PLUGIN, "settings", LocalPluginSettings(enabled=True))
    monkeypatch.setattr(plugin_module.PLUGIN, "_transport", httpx.MockTransport(upstream))
    _install_catalog(authenticated_client)

    listing = authenticated_client.get("/v1/models")
    assert listing.status_code == 200
    assert "local/fixture:model" in {row["id"] for row in listing.json()["data"]}

    response = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "pong"


def test_chat_route_works_before_model_listing_after_gateway_restart(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    async def upstream(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "fixture:model"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    monkeypatch.setattr(plugin_module.PLUGIN, "settings", LocalPluginSettings(enabled=True))
    monkeypatch.setattr(plugin_module.PLUGIN, "_transport", httpx.MockTransport(upstream))

    response = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "pong"


def test_non_finite_upstream_json_is_sanitized_at_the_route(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    upstream = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(b'{"choices":[{"message":{"content":"pong"}}],"usage":{"total_tokens":NaN}}'),
        )
    )
    monkeypatch.setattr(plugin_module.PLUGIN, "settings", LocalPluginSettings(enabled=True))
    monkeypatch.setattr(plugin_module.PLUGIN, "_transport", upstream)

    response = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "provider_error",
        "message": "The local model response is invalid.",
    }


def test_disabled_local_provider_refuses_route_dispatch_without_egress(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    def fail_if_called(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled local provider performed egress")

    monkeypatch.setattr(plugin_module.PLUGIN, "settings", LocalPluginSettings(enabled=False))
    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "_transport",
        httpx.MockTransport(fail_if_called),
    )

    response = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "local/fixture:model",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "provider_unavailable",
        "message": "The local model provider is disabled.",
    }
