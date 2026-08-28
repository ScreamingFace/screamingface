from __future__ import annotations


def test_provider_catalog_includes_keyless_and_disabled_catalogs(authenticated_client) -> None:
    response = authenticated_client.get("/v1/provider-catalog")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    providers = {row["id"]: row for row in body["data"]}
    assert providers["anthropic"] == {
        "object": "provider",
        "id": "anthropic",
        "display_name": "Anthropic",
        "description": "Claude models direct from Anthropic",
        "kind": "api",
        "group": "providers",
        "group_display_name": "Providers",
        "color": "#ca492c",
        "sort_order": 100,
        "connection_required": True,
        "auth_methods": ["api_key", "oauth"],
    }
    assert providers["ollama"]["connection_required"] is False
    assert providers["ollama"]["auth_methods"] == []
    assert providers["ollama"]["kind"] == "local"
    assert providers["openrouter"]["kind"] == "hub"


def test_provider_catalog_requires_auth(client) -> None:
    response = client.get("/v1/provider-catalog")

    assert response.status_code == 401
