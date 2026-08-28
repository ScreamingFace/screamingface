from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.connections.port import Caller, Provider
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio


class ProviderCatalog:
    async def providers(self, caller: Caller) -> tuple[Provider, ...]:
        assert caller.identity == {"X-User-Email": "researcher@example.com"}
        return (
            Provider(
                id="ollama",
                display_name="Ollama",
                description="Local models on your machine — no API key required",
                kind="local",
                group="local_and_sessions",
                group_display_name="Local & Sessions",
                color="#52aec5",
                sort_order=10,
                connection_required=False,
                auth_methods=(),
            ),
        )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_engine_exposes_complete_provider_catalog() -> None:
    app = create_app(
        Settings(jwt_secret="route-secret"),
        stream=InMemoryEventStream(),
        provider_catalog=ProviderCatalog(),
    )
    async with _client(app) as client:
        response = await client.get(
            "/v1/providers",
            headers={"X-User-Email": "researcher@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "object": "provider",
            "id": "ollama",
            "display_name": "Ollama",
            "description": "Local models on your machine — no API key required",
            "kind": "local",
            "group": "local_and_sessions",
            "group_display_name": "Local & Sessions",
            "color": "#52aec5",
            "sort_order": 10,
            "connection_required": False,
            "auth_methods": [],
        }
    ]
    assert response.headers["cache-control"] == "private, no-store"


async def test_tauri_origin_can_preflight_engine_api() -> None:
    app = create_app(Settings(jwt_secret="route-secret"), stream=InMemoryEventStream())
    async with _client(app) as client:
        response = await client.options(
            "/v1/providers",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"
