from __future__ import annotations

from types import SimpleNamespace

from aigateway.core.loader import load_plugins
from aigateway.core.registry import ProviderRegistry
from aigateway.plugins.ollama_provider import plugin as ollama_plugin
from aigateway.plugins.ollama_provider.plugin import OllamaProviderPlugin


def test_ollama_provider_loads_without_oauth() -> None:
    registry = ProviderRegistry()
    load_plugins(registry)

    plugin = registry.get("ollama")

    assert plugin is not None
    assert plugin.custom_llm_provider == "ollama"
    assert plugin.oauth_config() is None
    assert plugin.oauth_strategy_for("default") is None
    assert plugin.allows_chatless_credential() is True


def test_register_models_exposes_public_ollama_names(monkeypatch) -> None:
    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")
    monkeypatch.setattr(
        ollama_plugin,
        "discover_ollama_models",
        lambda _host: ["llama3:8b", "qwen2.5-coder:7b"],
    )

    entries = OllamaProviderPlugin().register_models()

    assert [entry.model_name for entry in entries] == [
        "ollama/llama3:8b",
        "ollama/qwen2.5-coder:7b",
    ]
    assert entries[0].litellm_params == {
        "model": "ollama_chat/llama3:8b",
        "api_base": "http://localhost:11434",
    }


def test_models_route_includes_discovered_ollama_models(monkeypatch, authenticated_client) -> None:
    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")
    monkeypatch.setattr(ollama_plugin, "discover_ollama_models", lambda _host: ["llama3:8b"])

    response = authenticated_client.get("/v1/models")

    assert response.status_code == 200
    models = {entry["id"]: entry for entry in response.json()["data"]}
    assert models["ollama/llama3:8b"]["owned_by"] == "ollama"


def test_prepare_chat_body_rewrites_model_injects_api_base_and_strips_auth(monkeypatch) -> None:
    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")
    body = {
        "model": "ollama/llama3:8b",
        "messages": [{"role": "user", "content": "hi"}],
        "api_key": "client-token",
        "extra_headers": {
            "Authorization": "Bearer bad",
            "X-Api-Key": "bad",
            "proxy-authorization": "bad",
            "x-trace-id": "trace-1",
        },
    }

    out = OllamaProviderPlugin().prepare_chat_body(body)

    assert out["model"] == "ollama_chat/llama3:8b"
    assert out["api_base"] == "http://localhost:11434"
    assert "api_key" not in out
    assert out["extra_headers"] == {"x-trace-id": "trace-1"}
    assert body["model"] == "ollama/llama3:8b"


def test_prepare_chat_body_leaves_ollama_chat_prefix_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")

    out = OllamaProviderPlugin().prepare_chat_body(
        {"model": "ollama_chat/llama3:8b", "messages": []}
    )

    assert out["model"] == "ollama_chat/llama3:8b"
    assert out["api_base"] == "http://localhost:11434"


def test_public_ollama_chat_prefix_is_not_a_route_level_provider(authenticated_client) -> None:
    response = authenticated_client.post(
        "/v1/chat/completions",
        json={"model": "ollama_chat/llama3:8b", "messages": []},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown provider: ollama_chat"


def test_ollama_chat_without_profile_reaches_plugin(monkeypatch, authenticated_client) -> None:
    captured: dict = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "ollama-test",
                "choices": [{"message": {"content": "pong"}}],
            }
        )

    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")
    monkeypatch.setattr(OllamaProviderPlugin, "chat_completion", fake_chat_completion)

    response = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "ollama/llama3:8b",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 200
    assert captured["model"] == "ollama_chat/llama3:8b"
    assert captured["api_base"] == "http://localhost:11434"


def test_ollama_streaming_is_not_route_rejected(monkeypatch, authenticated_client) -> None:
    async def fake_chat_completion_stream(_self, body):
        yield {"choices": [{"delta": {"content": body["model"]}}]}

    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")
    monkeypatch.setattr(OllamaProviderPlugin, "chat_completion_stream", fake_chat_completion_stream)

    response = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "ollama/llama3:8b",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert 'data: {"choices": [{"delta": {"content": "ollama_chat/llama3:8b"}}]}' in (response.text)
    assert "data: [DONE]" in response.text
