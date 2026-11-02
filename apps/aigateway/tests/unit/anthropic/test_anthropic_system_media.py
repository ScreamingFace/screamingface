"""Anthropic refuses media in a system message instead of dropping it (OME-1542).

# FEATURE: image and file input across the gateway (OME-1529).
# STORY: as a caller who put an image in the system prompt, I get a 422 naming it — not a 200
# answer from a model that never saw the image (the OAuth path kept only the system text blocks;
# the API-key path sent LiteLLM's `{"type": "image_url", "text": null}` upstream).
# INVARIANT: a system message (or a top-level `system` field) with a non-text part is refused in
# `prepare_chat_body`, on both auth paths, and the cache never answers such a body.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.content_parts import UnsupportedContentPart
from aigateway.core.plugin_base import CacheBypass
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin

_PNG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
_PDF = {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQK"}}
_MODEL = "anthropic/claude-haiku-4-5"


def _body(system: Any, *, top_level: bool = False) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": "hi"}]
    body: dict[str, Any] = {"model": _MODEL, "messages": messages}
    if top_level:
        body["system"] = system
    else:
        messages.insert(0, {"role": "system", "content": system})
    return body


@pytest.mark.parametrize("part", [_PNG, _PDF], ids=["image", "file"])
@pytest.mark.parametrize("top_level", [False, True], ids=["message", "top-level"])
def test_media_in_the_system_prompt_is_refused(part: dict[str, Any], top_level: bool) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        AnthropicProviderPlugin().prepare_chat_body(_body(["be brief", part], top_level=top_level))
    info = caught.value.info
    assert caught.value.status_code == 422
    assert info["provider"] == "anthropic"
    assert info["reason"] == "media in a system message"


@pytest.mark.parametrize(
    "system",
    [
        "be brief",
        [{"type": "text", "text": "be brief", "cache_control": {"type": "ephemeral"}}],
        ["be brief"],
        "",
    ],
)
@pytest.mark.parametrize("top_level", [False, True], ids=["message", "top-level"])
def test_a_text_system_prompt_is_unchanged(system: Any, top_level: bool) -> None:
    body = _body(system, top_level=top_level)
    out = AnthropicProviderPlugin().prepare_chat_body(body)
    assert out["messages"] == body["messages"]
    assert out.get("system") == body.get("system")


def test_media_in_a_user_message_is_still_carried() -> None:
    body = {"model": _MODEL, "messages": [{"role": "user", "content": ["look", _PNG]}]}
    out = AnthropicProviderPlugin().prepare_chat_body(body)
    assert out["messages"] == body["messages"]


@pytest.mark.parametrize("top_level", [False, True], ids=["message", "top-level"])
def test_the_cache_never_answers_a_system_media_body(top_level: bool) -> None:
    # WHY: prepare runs after the cache stage; an entry stored while the OAuth path still dropped
    # the image must not answer the request the gateway now refuses.
    projected = AnthropicProviderPlugin().global_cache_projection(
        _body(["be brief", _PNG], top_level=top_level)
    )
    assert isinstance(projected, CacheBypass)


def test_a_text_system_prompt_still_keys() -> None:
    projected = AnthropicProviderPlugin().global_cache_projection(_body("be brief"))
    assert not isinstance(projected, CacheBypass)
