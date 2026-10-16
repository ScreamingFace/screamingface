"""Unit tests for the neutral content-part translator (OME-1541).

# FEATURE: image and file input across the gateway (OME-1529).
# INVARIANT: no non-text part is ever dropped silently — it parses into a part, or raises
# `UnsupportedContentPart` (422) naming the provider and the part type.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from aigateway.core.content_parts import (
    MediaPart,
    RemoteImagePart,
    TextPart,
    UnsupportedContentPart,
    check_messages,
    parse_content,
    text_of,
)

PNG_B64 = "iVBORw0KGgo="
PDF_B64 = "JVBERi0xLjQK"


def _image(url: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": url}}


def _file(data: str, filename: str | None = None) -> dict[str, Any]:
    file: dict[str, Any] = {"file_data": data}
    if filename is not None:
        file["filename"] = filename
    return {"type": "file", "file": file}


# --- parse_content: text keeps today's lenient behaviour ---------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (None, []),
        ("hello", [TextPart("hello")]),
        ("", [TextPart("")]),
        (["a", "b"], [TextPart("a"), TextPart("b")]),
        ([{"type": "text", "text": "a"}], [TextPart("a")]),
        # WHY: the old flatteners accepted any dict carrying `text`/`content`; keep that.
        ([{"type": "input_text", "text": "a"}], [TextPart("a")]),
        ([{"content": "a"}], [TextPart("a")]),
        # empty text and non-dict junk were skipped before, and still are
        ([{"type": "text", "text": ""}, {"type": "text"}, None, 3], []),
    ],
)
def test_parse_text_content(content: Any, expected: list[Any]) -> None:
    assert parse_content(content, provider="p") == expected


def test_parse_non_list_non_str_content_is_stringified() -> None:
    assert parse_content(42, provider="p") == [TextPart("42")]


# --- parse_content: media ------------------------------------------------------------------


def test_parse_data_uri_image_keeps_base64_verbatim() -> None:
    parts = parse_content([_image(f"data:image/png;base64,{PNG_B64}")], provider="p")
    assert parts == [MediaPart(kind="image", mime="image/png", data=PNG_B64)]


def test_parse_image_url_given_as_bare_string() -> None:
    part = {"type": "image_url", "image_url": f"data:image/jpeg;base64,{PNG_B64}"}
    assert parse_content([part], provider="p") == [
        MediaPart(kind="image", mime="image/jpeg", data=PNG_B64)
    ]


def test_parse_data_uri_mime_is_lowercased_and_parameters_ignored() -> None:
    parts = parse_content([_image(f"data:Image/PNG;name=x.png;base64,{PNG_B64}")], provider="p")
    assert parts == [MediaPart(kind="image", mime="image/png", data=PNG_B64)]


@pytest.mark.parametrize("url", ["https://example.com/a.png", "http://example.com/a.png"])
def test_parse_remote_image(url: str) -> None:
    assert parse_content([_image(url)], provider="p") == [RemoteImagePart(url)]


def test_parse_pdf_file_part_with_filename() -> None:
    parts = parse_content([_file(f"data:application/pdf;base64,{PDF_B64}", "r.pdf")], provider="p")
    assert parts == [MediaPart(kind="file", mime="application/pdf", data=PDF_B64, filename="r.pdf")]


def test_parse_preserves_interleaved_order() -> None:
    content = [
        {"type": "text", "text": "before"},
        _image(f"data:image/png;base64,{PNG_B64}"),
        {"type": "text", "text": "after"},
    ]
    assert parse_content(content, provider="p") == [
        TextPart("before"),
        MediaPart(kind="image", mime="image/png", data=PNG_B64),
        TextPart("after"),
    ]


def test_media_part_data_uri_round_trips() -> None:
    assert (
        MediaPart(kind="image", mime="image/png", data=PNG_B64).data_uri
        == f"data:image/png;base64,{PNG_B64}"
    )


# --- parse_content: refusals ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("part", "part_type"),
    [
        ({"type": "input_audio", "input_audio": {"data": "x", "format": "wav"}}, "input_audio"),
        ({"type": "video_url", "video_url": {"url": "https://x"}}, "video_url"),
        (_image("data:image/png,notbase64"), "image_url"),
        (_image("data:image/png;base64,"), "image_url"),
        (_image("ftp://example.com/a.png"), "image_url"),
        ({"type": "image_url", "image_url": {}}, "image_url"),
        (_file("https://example.com/r.pdf"), "file"),
        ({"type": "file", "file": {"file_id": "file-123"}}, "file"),
    ],
)
def test_parse_unsupported_part_raises_422(part: dict[str, Any], part_type: str) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        parse_content([part], provider="gemini-cli")
    assert caught.value.status_code == 422
    detail = caught.value.info
    assert detail["code"] == "unsupported_content_part"
    assert detail["provider"] == "gemini-cli"
    assert detail["part_type"] == part_type


# --- text_of: the legacy flatten -----------------------------------------------------------


def test_text_of_joins_text_parts_with_newline() -> None:
    assert text_of([TextPart("a"), TextPart("b")]) == "a\nb"


def test_text_of_empty_is_empty_string() -> None:
    assert text_of([]) == ""


# --- check_messages: the pre-dispatch gate ----------------------------------------------------


def test_check_messages_accepts_text_only_and_user_media() -> None:
    check_messages(
        [
            {"role": "system", "content": "s"},
            {"role": "user", "content": [_image(f"data:image/png;base64,{PNG_B64}")]},
            {"role": "assistant", "content": "ok"},
        ],
        provider="p",
        media_roles=frozenset({"user"}),
        allow_remote_images=False,
    )


@pytest.mark.parametrize("role", ["system", "tool", "assistant"])
def test_check_messages_refuses_media_outside_allowed_roles(role: str) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        check_messages(
            [{"role": role, "content": [_image(f"data:image/png;base64,{PNG_B64}")]}],
            provider="codex",
            media_roles=frozenset({"user"}),
            allow_remote_images=True,
        )
    assert caught.value.info["reason"] == f"media in a {role} message"


def test_check_messages_refuses_remote_image_when_not_allowed() -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        check_messages(
            [{"role": "user", "content": [_image("https://example.com/a.png")]}],
            provider="gemini-cli",
            media_roles=frozenset({"user"}),
            allow_remote_images=False,
        )
    assert caught.value.info["reason"] == "remote_url"


def test_check_messages_allows_remote_image_when_allowed() -> None:
    check_messages(
        [{"role": "user", "content": [_image("https://example.com/a.png")]}],
        provider="codex",
        media_roles=frozenset({"user"}),
        allow_remote_images=True,
    )


def test_check_messages_skips_non_dict_messages() -> None:
    check_messages(
        cast(list[dict[str, Any]], [None, "x"]),
        provider="p",
        media_roles=frozenset({"user"}),
        allow_remote_images=False,
    )


# --- review of PR #1431: detail, MIME family, untyped parts ----------------------------------


@pytest.mark.parametrize("detail", ["auto", "low", "high"])
def test_parse_image_keeps_detail(detail: str) -> None:
    data = {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{PNG_B64}", "detail": detail},
    }
    remote = {
        "type": "image_url",
        "image_url": {"url": "https://example.com/a.png", "detail": detail},
    }
    assert parse_content([data, remote], provider="p") == [
        MediaPart(kind="image", mime="image/png", data=PNG_B64, detail=detail),
        RemoteImagePart("https://example.com/a.png", detail=detail),
    ]


def test_parse_image_without_detail_leaves_it_unset() -> None:
    assert parse_content([_image("https://example.com/a.png")], provider="p") == [
        RemoteImagePart("https://example.com/a.png", detail=None)
    ]


def test_parse_image_refuses_unknown_detail() -> None:
    part = {
        "type": "image_url",
        "image_url": {"url": "https://example.com/a.png", "detail": "ultra"},
    }
    with pytest.raises(UnsupportedContentPart) as caught:
        parse_content([part], provider="codex")
    assert caught.value.info["part_type"] == "image_url"
    assert caught.value.info["reason"] == "invalid detail 'ultra'"


@pytest.mark.parametrize(
    ("part", "part_type", "mime"),
    [
        # INVARIANT: an audio/video payload wrapped in an image or file envelope is refused,
        # never dispatched as input_image / input_file / inlineData.
        (_image("data:audio/wav;base64,UklGRg=="), "image_url", "audio/wav"),
        (_image("data:video/mp4;base64,AAAAIGZ0eXA="), "image_url", "video/mp4"),
        (_image(f"data:application/pdf;base64,{PDF_B64}"), "image_url", "application/pdf"),
        (_file("data:video/mp4;base64,AAAAIGZ0eXA="), "file", "video/mp4"),
        (_file("data:audio/mpeg;base64,SUQz"), "file", "audio/mpeg"),
        (_file(f"data:image/png;base64,{PNG_B64}"), "file", "image/png"),
    ],
)
def test_parse_refuses_mime_outside_the_part_family(
    part: dict[str, Any], part_type: str, mime: str
) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        parse_content([part], provider="gemini-cli")
    assert caught.value.info["part_type"] == part_type
    assert caught.value.info["reason"] == f"unsupported_mime {mime}"


@pytest.mark.parametrize(
    "part",
    [{}, {"image": "x"}, {"type": 7}, {"text": 3}, {"content": ["nested"]}],
)
def test_parse_refuses_untyped_non_text_mapping(part: dict[str, Any]) -> None:
    # INVARIANT: fail closed — a mapping that is neither text nor a known media part is
    # refused, not skipped (skipping is the silent drop this module exists to end).
    with pytest.raises(UnsupportedContentPart) as caught:
        parse_content([part], provider="p")
    assert caught.value.info["part_type"] == "untyped"


@pytest.mark.parametrize("detail", [[], {}, ["high"], {"level": "high"}, 1, True])
def test_parse_image_refuses_non_string_detail_with_422(detail: Any) -> None:
    # INVARIANT: content is untrusted JSON — an unhashable `detail` must reach the typed 422,
    # never a TypeError (a 500) from set membership.
    part = {
        "type": "image_url",
        "image_url": {"url": "https://example.com/x.png", "detail": detail},
    }
    with pytest.raises(UnsupportedContentPart) as caught:
        parse_content([part], provider="codex")
    assert caught.value.info["part_type"] == "image_url"
    assert caught.value.info["reason"] == f"invalid detail {detail!r}"
