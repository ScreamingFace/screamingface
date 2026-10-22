"""One `data:` URI validator and one remote-scheme rule for intake and parser (OME-1542, review 2).

# FEATURE: image and file input across the gateway (OME-1529).
# INVARIANT: the ingress guard (`media_intake`) and the parser (`content_parts`) agree — a value
# the guard admits as inline media is one the parser accepts, so nothing passes ingress only to
# fail after the cache stage and credential resolution. The envelope is the engine-conformant
# `_DATA_URI_RE` plus a payload that is non-empty, strictly valid base64.
# INVARIANT: validation is linear-time on caller input up to the body cap — a pathological value
# completes in well under 100 ms (a ReDoS was just found in url4).
# INVARIANT: URI schemes are case-insensitive (RFC 3986 §3.1); a remote image URL is recognised
# whatever its case and carried on with the scheme lowercased.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from aigateway.core.content_parts import (
    MediaPart,
    RemoteImagePart,
    UnsupportedContentPart,
    parse_content,
    parse_data_uri,
)
from aigateway.core.media_intake import refuse_remote_media

_MALFORMED = [
    "data:",
    "data:not-a-media-uri",
    "data:image/png;base64,%%%",
    "data:image/png;base64,",
    "data:image/png,iVBORw0KGgo=",
    "data:;base64,iVBORw0KGgo=",
    "data:image/png;base64,iVBORw0KGgo",  # missing padding
    "data:image/png;base64,iVBO Rw0KGgo=",  # whitespace is not base64
    "data:image/png;base64,iVBORw0KGgo=\n",
    "data:image/png;base64,=iVBORw0KGgo",  # padding not at the end
    "data:image/png;base64,iVBORw0KGgo=é",
]


@pytest.mark.parametrize("value", _MALFORMED)
def test_a_malformed_data_uri_does_not_parse(value: str) -> None:
    assert parse_data_uri(value) is None


@pytest.mark.parametrize(
    ("value", "mime", "data"),
    [
        ("data:image/png;base64,iVBORw0KGgo=", "image/png", "iVBORw0KGgo="),
        ("data:Image/PNG;name=x.png;base64,iVBORw0KGgo=", "image/png", "iVBORw0KGgo="),
        ("data:application/pdf;base64,JVBERi0xLjQK", "application/pdf", "JVBERi0xLjQK"),
        ("data:audio/wav;base64,UklGRg==", "audio/wav", "UklGRg=="),
    ],
)
def test_a_well_formed_data_uri_parses(value: str, mime: str, data: str) -> None:
    parsed = parse_data_uri(value)
    assert parsed is not None
    assert (parsed.mime, parsed.data) == (mime, data)


def _image(url: Any) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": url}}


def _file(data: Any) -> dict[str, Any]:
    return {"type": "file", "file": {"file_data": data}}


@pytest.mark.parametrize("value", _MALFORMED)
@pytest.mark.parametrize("make", [_image, _file], ids=["image", "file"])
def test_the_intake_guard_and_the_parser_both_refuse_a_malformed_data_uri(
    make: Any, value: str
) -> None:
    messages = [{"role": "user", "content": [make(value)]}]
    with pytest.raises(UnsupportedContentPart) as caught:
        refuse_remote_media(messages, provider="anthropic", allow_remote_image_urls=False)
    assert caught.value.info["reason"] == "not_data_uri"
    with pytest.raises(UnsupportedContentPart):
        parse_content(messages[0]["content"], provider="gemini")


def test_a_valid_data_uri_passes_both() -> None:
    messages = [{"role": "user", "content": [_image("data:image/png;base64,iVBORw0KGgo=")]}]
    refuse_remote_media(messages, provider="anthropic", allow_remote_image_urls=False)
    [part] = parse_content(messages[0]["content"], provider="gemini")
    assert isinstance(part, MediaPart)


_BIG = 8 * 1024 * 1024


# WHY builders, not values: eight 8 MiB strings built at collection would sit in memory for the
# whole session; each is built inside its own test and freed after it.
_PATHOLOGICAL: dict[str, Any] = {
    "params": lambda: "data:a/b" + ";base64" * (_BIG // 7),
    "params-trailing": lambda: "data:a/b" + ";base64;" * (_BIG // 8),
    "short-params": lambda: "data:a/b" + ";a" * (_BIG // 2),
    "no-slash": lambda: "data:" + "a" * _BIG,
    "long-mime": lambda: "data:" + "+" * (_BIG // 2) + "/" + "+" * (_BIG // 2),
    "bad-tail": lambda: "data:image/png;base64," + "A" * _BIG + "%",
    "bad-length": lambda: "data:image/png;base64," + "A" * (_BIG - 1),
    "commas": lambda: "data:image/png;base64," + ";base64," * (_BIG // 8),
}


@pytest.mark.parametrize("name", sorted(_PATHOLOGICAL))
def test_a_pathological_value_is_rejected_in_linear_time(name: str) -> None:
    value = _PATHOLOGICAL[name]()
    started = time.perf_counter()
    assert parse_data_uri(value) is None
    elapsed = time.perf_counter() - started
    assert elapsed < 0.1, f"{elapsed * 1000:.1f} ms"


def test_a_cap_sized_valid_payload_parses_in_linear_time() -> None:
    value = "data:image/png;base64," + "AAAA" * (_BIG // 4)
    started = time.perf_counter()
    assert parse_data_uri(value) is not None
    assert time.perf_counter() - started < 0.1


# --- remote scheme ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "normalized"),
    [
        ("HTTPS://example.com/A.png", "https://example.com/A.png"),
        ("Https://example.com/a.png", "https://example.com/a.png"),
        ("hTTp://example.com/a.png", "http://example.com/a.png"),
        ("https://example.com/a.png", "https://example.com/a.png"),
    ],
)
def test_the_parser_recognises_a_remote_scheme_in_any_case(url: str, normalized: str) -> None:
    [part] = parse_content([_image(url)], provider="codex")
    assert isinstance(part, RemoteImagePart)
    assert part.url == normalized


@pytest.mark.parametrize("url", ["HTTPS://example.com/a.png", "hTtPs://example.com/a.png"])
def test_the_codex_opt_in_admits_a_mixed_case_https_image(url: str) -> None:
    refuse_remote_media(
        [{"role": "user", "content": [_image(url)]}],
        provider="codex",
        allow_remote_image_urls=True,
    )
