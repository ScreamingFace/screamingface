"""Gemini, Antigravity and Codex carry images and PDFs natively (OME-1541).

# FEATURE: image and file input across the gateway (OME-1529).
# INVARIANT: text-only requests are byte-identical to the pre-OME-1541 flatten.
# INVARIANT: no adapter drops a non-text part — it is translated, or the plugin's
# `prepare_chat_body` refuses it with a typed 422 before dispatch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from aigateway.core.content_parts import UnsupportedContentPart
from aigateway.plugins.antigravity_provider.message_adapter import (
    build_generate_content_body as build_antigravity,
)
from aigateway.plugins.codex_provider.chat_handler import _build_payload
from aigateway.plugins.gemini_provider.message_adapter import (
    build_generate_content_body as build_gemini,
)

PNG_B64 = "iVBORw0KGgo="
PDF_B64 = "JVBERi0xLjQK"
PNG_URI = f"data:image/png;base64,{PNG_B64}"
PDF_URI = f"data:application/pdf;base64,{PDF_B64}"

GEMINI_BUILDERS: list[Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, Any]]] = [
    build_gemini,
    build_antigravity,
]


def _image(url: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": url}}


def _pdf() -> dict[str, Any]:
    return {"type": "file", "file": {"file_data": PDF_URI, "filename": "r.pdf"}}


# --- Gemini and Antigravity ------------------------------------------------------------------


@pytest.mark.parametrize("build", GEMINI_BUILDERS)
def test_gemini_text_only_shape_is_unchanged(build) -> None:
    body = build(
        [
            {"role": "system", "content": [{"type": "text", "text": "s1"}, "s2"]},
            {"role": "user", "content": [{"type": "text", "text": "a"}, {"text": "b"}]},
            {"role": "assistant", "content": "c"},
        ],
        {},
    )
    assert body["systemInstruction"] == {"parts": [{"text": "s1\ns2"}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "a\nb"}]},
        {"role": "model", "parts": [{"text": "c"}]},
    ]


@pytest.mark.parametrize("build", GEMINI_BUILDERS)
def test_gemini_interleaves_text_and_inline_data_in_order(build) -> None:
    body = build(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "one"},
                    {"type": "text", "text": "two"},
                    _image(PNG_URI),
                    {"type": "text", "text": "three"},
                    _pdf(),
                ],
            }
        ],
        {},
    )
    assert body["contents"] == [
        {
            "role": "user",
            "parts": [
                # consecutive text keeps the legacy newline join
                {"text": "one\ntwo"},
                {"inlineData": {"mimeType": "image/png", "data": PNG_B64}},
                {"text": "three"},
                {"inlineData": {"mimeType": "application/pdf", "data": PDF_B64}},
            ],
        }
    ]


@pytest.mark.parametrize("build", GEMINI_BUILDERS)
def test_gemini_image_only_turn_is_kept(build) -> None:
    body = build([{"role": "user", "content": [_image(PNG_URI)]}], {})
    assert body["contents"] == [
        {"role": "user", "parts": [{"inlineData": {"mimeType": "image/png", "data": PNG_B64}}]}
    ]


@pytest.mark.parametrize("build", GEMINI_BUILDERS)
def test_gemini_adapter_refuses_remote_image_if_it_slips_past_the_gate(build) -> None:
    # WHY: defence in depth — `prepare_chat_body` refuses this first; the adapter must still
    # never drop it.
    with pytest.raises(UnsupportedContentPart):
        build([{"role": "user", "content": [_image("https://example.com/a.png")]}], {})


# --- Codex -------------------------------------------------------------------------------------


def test_codex_text_only_payload_is_unchanged() -> None:
    payload = _build_payload(
        "codex/gpt-5.4-mini",
        [
            {"role": "system", "content": "s"},
            {"role": "user", "content": [{"type": "text", "text": "a"}, "b"]},
            {"role": "assistant", "content": "c"},
        ],
        {},
    )
    assert payload["instructions"] == "s"
    assert payload["input"] == [
        {"role": "user", "content": "a\nb"},
        {"role": "assistant", "content": "c"},
    ]


def test_codex_user_media_becomes_input_parts_in_order() -> None:
    payload = _build_payload(
        "codex/gpt-5.4-mini",
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    _image(PNG_URI),
                    _image("https://example.com/a.png"),
                    _pdf(),
                ],
            }
        ],
        {},
    )
    assert payload["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "look"},
                {"type": "input_image", "image_url": PNG_URI},
                {"type": "input_image", "image_url": "https://example.com/a.png"},
                {"type": "input_file", "filename": "r.pdf", "file_data": PDF_URI},
            ],
        }
    ]


def test_codex_file_without_filename_gets_a_default() -> None:
    payload = _build_payload(
        "codex/gpt-5.4-mini",
        [{"role": "user", "content": [{"type": "file", "file": {"file_data": PDF_URI}}]}],
        {},
    )
    assert payload["input"][0]["content"] == [
        {"type": "input_file", "filename": "attachment.pdf", "file_data": PDF_URI}
    ]


def test_codex_adapter_refuses_media_on_assistant_if_it_slips_past_the_gate() -> None:
    with pytest.raises(UnsupportedContentPart):
        _build_payload(
            "codex/gpt-5.4-mini", [{"role": "assistant", "content": [_image(PNG_URI)]}], {}
        )


# --- the pre-dispatch gate in each plugin -----------------------------------------------------


def _plugins() -> list[tuple[str, Any]]:
    from aigateway.plugins.antigravity_provider.plugin import AntigravityProviderPlugin
    from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin
    from aigateway.plugins.gemini_provider.plugin import GeminiProviderPlugin

    return [
        ("gemini-cli", GeminiProviderPlugin.__new__(GeminiProviderPlugin)),
        ("antigravity", AntigravityProviderPlugin.__new__(AntigravityProviderPlugin)),
        ("codex", CodexProviderPlugin.__new__(CodexProviderPlugin)),
    ]


@pytest.mark.parametrize(("provider", "plugin"), _plugins())
def test_prepare_chat_body_passes_text_and_inline_media(provider: str, plugin: Any) -> None:
    body = {"model": "m", "messages": [{"role": "user", "content": ["hi", _image(PNG_URI)]}]}
    assert plugin.prepare_chat_body(body)["messages"] == body["messages"]


@pytest.mark.parametrize(("provider", "plugin"), _plugins())
def test_prepare_chat_body_refuses_media_in_system_message(provider: str, plugin: Any) -> None:
    body = {"model": "m", "messages": [{"role": "system", "content": [_image(PNG_URI)]}]}
    with pytest.raises(UnsupportedContentPart) as caught:
        plugin.prepare_chat_body(body)
    assert caught.value.status_code == 422
    assert caught.value.info["provider"] == provider


@pytest.mark.parametrize(("provider", "plugin"), _plugins())
def test_prepare_chat_body_refuses_unknown_part_types(provider: str, plugin: Any) -> None:
    audio = {"type": "input_audio", "input_audio": {"data": "x", "format": "wav"}}
    body = {"model": "m", "messages": [{"role": "user", "content": [audio]}]}
    with pytest.raises(UnsupportedContentPart) as caught:
        plugin.prepare_chat_body(body)
    assert caught.value.info["part_type"] == "input_audio"


@pytest.mark.parametrize(
    ("provider", "plugin", "allowed"),
    [(name, plugin, name == "codex") for name, plugin in _plugins()],
)
def test_prepare_chat_body_remote_image_only_for_codex(
    provider: str, plugin: Any, allowed: bool
) -> None:
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": [_image("https://example.com/a.png")]}],
    }
    if allowed:
        plugin.prepare_chat_body(body)
        return
    with pytest.raises(UnsupportedContentPart) as caught:
        plugin.prepare_chat_body(body)
    assert caught.value.info["reason"] == "remote_url"
