"""The data:-only media guard (OME-1542).

# FEATURE: image and file input across the gateway (OME-1529).
# STORY: as the gateway operator, a caller can never make our process dial a URL of their
# choosing — LiteLLM would fetch `http://` images for Anthropic, any `http*` image for Ollama and
# URL-shaped `file_id`s for the OpenAI wire.
# INVARIANT: image and file parts are accepted only as `data:` URIs; a reference is refused with
# the typed 422 (`unsupported_content_part`). Text is never inspected.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.content_parts import UnsupportedContentPart
from aigateway.core.media_intake import refuse_remote_media

PNG = "data:image/png;base64,iVBORw0KGgo="
PDF = "data:application/pdf;base64,JVBERi0xLjQK"


def _user(*parts: Any) -> list[dict[str, Any]]:
    return [{"role": "user", "content": list(parts)}]


def _image(url: Any) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": url}}


def _refusal(messages: Any, *, allow: bool = False) -> dict[str, str]:
    with pytest.raises(UnsupportedContentPart) as caught:
        refuse_remote_media(messages, provider="anthropic", allow_remote_image_urls=allow)
    assert caught.value.status_code == 422
    assert caught.value.info["code"] == "unsupported_content_part"
    assert caught.value.info["provider"] == "anthropic"
    return caught.value.info


# --- accepted ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "see https://example.com/a.png"}],
        _user({"type": "text", "text": "see http://10.0.0.1/a.png"}),
        _user(_image(PNG)),
        _user({"type": "image_url", "image_url": PNG}),
        _user({"type": "file", "file": {"file_data": PDF, "filename": "a.pdf"}}),
        _user({"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}}),
        [{"role": "assistant", "content": [{"type": "thinking", "thinking": "https://x.y"}]}],
        [{"role": "assistant", "content": None, "tool_calls": []}],
        [{"role": "tool", "content": [{"type": "tool_result", "content": "https://x.y/z"}]}],
        ["not a mapping", {"role": "user", "content": 7}],
        [],
    ],
)
def test_text_and_inline_media_pass(messages: Any) -> None:
    refuse_remote_media(messages, provider="anthropic", allow_remote_image_urls=False)


# --- image_url ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a.png",
        "http://127.0.0.1:9/a.png",
        "HTTPS://EXAMPLE.COM/A.PNG",
        "  http://example.com/a.png",
    ],
)
def test_a_remote_image_url_is_refused(url: str) -> None:
    info = _refusal(_user(_image(url)))
    assert info["part_type"] == "image_url"
    assert info["reason"] == "remote_url"


def test_a_bare_string_remote_image_url_is_refused() -> None:
    info = _refusal(_user({"type": "image_url", "image_url": "https://example.com/a.png"}))
    assert info["reason"] == "remote_url"


@pytest.mark.parametrize(
    "url", ["iVBORw0KGgo=", "file:///etc/passwd", "ftp://example.com/a.png", "", None, 3]
)
def test_an_image_that_is_not_a_data_uri_is_refused(url: Any) -> None:
    info = _refusal(_user(_image(url)))
    assert info["part_type"] == "image_url"
    assert info["reason"] == "not_data_uri"


def test_the_opt_in_lets_http_image_urls_through() -> None:
    # Codex: OpenAI fetches the URL, our process never dials it (OME-1541 decision).
    refuse_remote_media(
        _user(_image("https://example.com/a.png")),
        provider="codex",
        allow_remote_image_urls=True,
    )


def test_the_opt_in_does_not_relax_files() -> None:
    info = _refusal(
        _user({"type": "file", "file": {"file_id": "https://example.com/a.pdf"}}), allow=True
    )
    assert info["reason"] == "remote_url"


def test_the_opt_in_does_not_relax_non_data_images() -> None:
    info = _refusal(_user(_image("file:///etc/passwd")), allow=True)
    assert info["reason"] == "not_data_uri"


# --- file ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "file_id", ["https://example.com/a.pdf", "http://example.com/a.pdf", "www.example.com/a.pdf"]
)
def test_a_url_shaped_file_id_is_refused_as_remote(file_id: str) -> None:
    info = _refusal(_user({"type": "file", "file": {"file_id": file_id}}))
    assert info["part_type"] == "file"
    assert info["reason"] == "remote_url"


def test_an_opaque_file_id_is_refused() -> None:
    info = _refusal(_user({"type": "file", "file": {"file_id": "file-abc123"}}))
    assert info["part_type"] == "file"
    assert info["reason"] == "file_id"


def test_a_remote_file_data_is_refused() -> None:
    info = _refusal(_user({"type": "file", "file": {"file_data": "https://example.com/a.pdf"}}))
    assert info["reason"] == "remote_url"


@pytest.mark.parametrize("file", [{"file_data": "JVBERi0="}, {}, "nope"])
def test_a_file_that_is_not_a_data_uri_is_refused(file: Any) -> None:
    info = _refusal(_user({"type": "file", "file": file}))
    assert info["part_type"] == "file"
    assert info["reason"] == "not_data_uri"


def test_a_file_carrying_data_and_a_url_id_is_still_refused() -> None:
    info = _refusal(_user({"type": "file", "file": {"file_data": PDF, "file_id": "www.x.y/a"}}))
    assert info["reason"] == "remote_url"


# --- any other part: URL-bearing keys at any depth ------------------------------------------------


@pytest.mark.parametrize(
    "part",
    [
        {"type": "video_url", "video_url": {"url": "https://example.com/v.mp4"}},
        {"type": "image", "source": {"type": "url", "url": "http://example.com/a.png"}},
        {"type": "document", "source": {"type": "url", "url": "https://example.com/a.pdf"}},
        {"type": "input_image", "image_url": "https://example.com/a.png"},
        {"type": "audio_url", "audio_url": "www.example.com/a.wav"},
        {
            "type": "tool_result",
            "content": [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}],
        },
    ],
)
def test_a_url_nested_in_any_other_part_is_refused(part: dict[str, Any]) -> None:
    info = _refusal(_user(part))
    assert info["reason"] == "remote_url"
    assert info["part_type"] == part["type"]


def test_the_opt_in_does_not_relax_other_parts() -> None:
    info = _refusal(
        _user({"type": "video_url", "video_url": {"url": "https://example.com/v.mp4"}}),
        allow=True,
    )
    assert info["reason"] == "remote_url"


@pytest.mark.parametrize("role", ["system", "assistant", "tool", "developer"])
def test_every_role_is_checked(role: str) -> None:
    info = _refusal([{"role": role, "content": [_image("https://example.com/a.png")]}])
    assert info["reason"] == "remote_url"


def test_a_part_nested_too_deeply_is_refused_rather_than_walked_forever() -> None:
    part: dict[str, Any] = {"type": "x", "url": "data:,"}
    for _ in range(100):
        part = {"type": "x", "inner": part}
    info = _refusal(_user(part))
    assert info["reason"] == "too_deep"
