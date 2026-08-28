from __future__ import annotations

import httpx
import pytest

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller

pytestmark = pytest.mark.asyncio


def _row(
    provider: str,
    display_name: str,
    *,
    connection_required: bool,
) -> dict[str, object]:
    local = provider == "ollama"
    return {
        "object": "provider",
        "id": provider,
        "display_name": display_name,
        "description": f"{display_name} models",
        "kind": "local" if local else "hub",
        "group": "local_and_sessions" if local else "hubs",
        "group_display_name": "Local & Sessions" if local else "Hubs",
        "color": "#52aec5" if local else "#937098",
        "sort_order": 10 if local else 200,
        "connection_required": connection_required,
        "auth_methods": ["api_key"] if connection_required else [],
    }


async def test_catalog_adapter_includes_keyless_providers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    _row("ollama", "Ollama", connection_required=False),
                    _row("openrouter", "OpenRouter", connection_required=True),
                ],
            },
        )

    adapter = AigatewayConnections(
        httpx.AsyncClient(
            base_url="http://aigateway.test",
            transport=httpx.MockTransport(handler),
        )
    )

    providers = await adapter.providers(Caller({"X-User-Email": "alice@example.com"}))

    assert [(provider.id, provider.connection_required) for provider in providers] == [
        ("ollama", False),
        ("openrouter", True),
    ]
    assert [request.url.path for request in seen] == ["/v1/provider-catalog"]
    await adapter.aclose()
