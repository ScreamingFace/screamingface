"""Ollama refuses content parts it cannot carry instead of dropping them.

FEATURE: image and file input across the gateway (OME-1529).
STORY: as a caller sending a PDF to an Ollama model, I get a 422 naming the part — not a 200
answer from a model that never saw the file (observed live on 2026-10-16: +7 prompt tokens).

INVARIANT: LiteLLM's `ollama_chat` conversion carries only `image_url` parts (as base64, from any
role) and discards `file` parts, so the Ollama plugin refuses `file` parts and remote image URLs
before dispatch; data-URI images and text pass unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from aigateway.core.content_parts import UnsupportedContentPart, check_messages
from aigateway.plugins.ollama_provider import plugin as ollama_plugin
from aigateway.plugins.ollama_provider.plugin import OllamaProviderPlugin

_PNG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
_PDF = {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQK"}}
_REMOTE = {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}


@pytest.fixture
def plugin(monkeypatch) -> OllamaProviderPlugin:
    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")
    return OllamaProviderPlugin()


def _body(content: Any, role: str = "user") -> dict[str, Any]:
    return {"model": "ollama/qwen2.5vl:3b", "messages": [{"role": role, "content": content}]}


# --- the new core flag ------------------------------------------------------------------------


def test_check_messages_refuses_files_when_not_allowed() -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        check_messages(
            [{"role": "user", "content": [_PDF]}],
            provider="ollama",
            media_roles=frozenset({"user"}),
            allow_remote_images=False,
            allow_files=False,
        )
    assert caught.value.info["part_type"] == "file"
    assert caught.value.info["reason"] == "files_unsupported"


def test_check_messages_still_accepts_files_by_default() -> None:
    # INVARIANT: the OME-1541 plugins keep their behaviour — files are allowed unless refused.
    check_messages(
        [{"role": "user", "content": [_PDF]}],
        provider="codex",
        media_roles=frozenset({"user"}),
        allow_remote_images=True,
    )


# --- the Ollama plugin gate -----------------------------------------------------------------


def test_ollama_refuses_a_pdf_part(plugin: OllamaProviderPlugin) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        plugin.prepare_chat_body(_body(["what code is in this?", _PDF]))
    assert caught.value.status_code == 422
    assert caught.value.info["provider"] == "ollama"
    assert caught.value.info["part_type"] == "file"


def test_ollama_refuses_a_remote_image_url(plugin: OllamaProviderPlugin) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        plugin.prepare_chat_body(_body(["what is this?", _REMOTE]))
    assert caught.value.info["reason"] == "remote_url"


@pytest.mark.parametrize("role", ["user", "system", "assistant", "tool"])
def test_ollama_passes_a_data_uri_image_in_any_role(
    plugin: OllamaProviderPlugin, role: str
) -> None:
    # WHY every role: LiteLLM's ollama_chat conversion carries images from any message.
    out = plugin.prepare_chat_body(_body(["look", _PNG], role=role))
    assert out["messages"][0]["content"] == ["look", _PNG]


def test_ollama_text_only_body_is_unchanged(plugin: OllamaProviderPlugin) -> None:
    out = plugin.prepare_chat_body(_body("hi"))
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    assert out["model"] == "ollama_chat/qwen2.5vl:3b"


# --- through the real route -------------------------------------------------------------------


def test_route_answers_422_for_a_pdf_and_never_dispatches(
    monkeypatch, authenticated_client
) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat_completion(_self, body):
        captured.update(body)
        return SimpleNamespace(model_dump=lambda: {"id": "x", "choices": []})

    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: "http://localhost:11434")
    monkeypatch.setattr(OllamaProviderPlugin, "chat_completion", fake_chat_completion)

    resp = authenticated_client.post("/v1/chat/completions", json=_body(["read it", _PDF]))

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_content_part"
    assert detail["provider"] == "ollama"
    assert detail["part_type"] == "file"
    assert captured == {}
