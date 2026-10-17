"""OME-1537 — Ollama input modalities from ``POST /api/show`` ``capabilities``.

Verified live 2026-10-16 (Ollama 0.21.2): ``qwen2.5vl:3b`` -> ``["completion",
"vision"]``; ``qwen3:14b`` -> ``["completion", "tools", "thinking"]``. ``/api/tags``
carries no capabilities, so each installed model is asked once (cached).

INVARIANT: ``vision`` -> ``image``. ``pdf`` is NEVER reported — the gateway refuses
file parts on Ollama (OME-1641). Any failure to ask is unknown -> text-only.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aigateway.core.model_capabilities import model_row
from aigateway.plugins.ollama_provider import plugin as ollama_plugin
from aigateway.plugins.ollama_provider.discovery import (
    DEFAULT_OLLAMA_HOST,
    clear_ollama_discovery_cache,
    discover_ollama_input_modalities,
    ollama_input_modalities,
)
from aigateway.plugins.ollama_provider.plugin import OllamaProviderPlugin


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_ollama_discovery_cache()
    yield
    clear_ollama_discovery_cache()


class _Server:
    def __init__(self, capabilities: dict[str, object], *, status: int = 200) -> None:
        self._capabilities = capabilities
        self._status = status
        self.asked: list[str] = []

    def factory(self, timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle), timeout=timeout)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/show"
        name = json.loads(request.content)["model"]
        self.asked.append(name)
        if self._status != 200:
            return httpx.Response(self._status, json={"error": "nope"})
        return httpx.Response(200, json={"capabilities": self._capabilities.get(name)})


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        (["completion", "vision"], ("text", "image")),
        (["completion", "tools", "thinking"], ("text",)),
        (["completion", "vision", "pdf", "file"], ("text", "image")),
        ([], ("text",)),
        (None, None),
        ("vision", None),
    ],
)
def test_capabilities_map_vision_to_image_and_never_pdf(
    capabilities: object, expected: tuple[str, ...] | None
) -> None:
    assert ollama_input_modalities(capabilities) == expected


def test_show_is_asked_once_per_model_and_cached() -> None:
    server = _Server({"qwen2.5vl:3b": ["completion", "vision"]})
    for _ in range(3):
        got = discover_ollama_input_modalities(
            DEFAULT_OLLAMA_HOST, "qwen2.5vl:3b", http_client_factory=server.factory
        )
        assert got == ("text", "image")
    assert server.asked == ["qwen2.5vl:3b"]


def test_show_failure_is_unknown() -> None:
    server = _Server({}, status=404)
    assert (
        discover_ollama_input_modalities(
            DEFAULT_OLLAMA_HOST, "gone:1b", http_client_factory=server.factory
        )
        is None
    )


def test_unreachable_host_is_unknown() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(refuse), timeout=timeout)

    assert (
        discover_ollama_input_modalities(DEFAULT_OLLAMA_HOST, "m:1b", http_client_factory=factory)
        is None
    )


def test_malformed_show_body_is_unknown() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    def factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    assert (
        discover_ollama_input_modalities(DEFAULT_OLLAMA_HOST, "m:1b", http_client_factory=factory)
        is None
    )


def test_rows_publish_ollama_vision_as_image_only(monkeypatch) -> None:
    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: DEFAULT_OLLAMA_HOST)
    monkeypatch.setattr(
        ollama_plugin, "discover_ollama_models", lambda _host: ["qwen2.5vl:3b", "qwen3:14b"]
    )
    evidence = {"qwen2.5vl:3b": ("text", "image"), "qwen3:14b": ("text",)}
    monkeypatch.setattr(
        ollama_plugin,
        "discover_ollama_input_modalities",
        lambda _host, name: evidence[name],
    )
    plugin = OllamaProviderPlugin()
    rows = {
        r["id"]: r["input_modalities"]
        for r in map(lambda e: model_row(plugin, e), plugin.register_models())
    }
    assert rows == {"ollama/qwen2.5vl:3b": ["text", "image"], "ollama/qwen3:14b": ["text"]}
