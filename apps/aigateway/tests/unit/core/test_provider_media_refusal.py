"""A provider's 415 on a media request is the gateway's content-part refusal (OME-1946).

# FEATURE: image and file input (OME-1529). A provider that rejects a part's media type with
# HTTP 415 (seen: Hugging Face router -> DeepInfra, a GIF) is refusing the PART, which is
# exactly what `unsupported_content_part` names. A 415 on a text-only request is not about a
# part and keeps the generic provider mapping.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.content_parts import provider_media_refusal

_GIF = {"type": "image_url", "image_url": {"url": "data:image/gif;base64,R0lGODlhAQABAAAAACw="}}
_PNG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
_PDF = {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQK"}}
_REMOTE = {"type": "image_url", "image_url": {"url": "https://example.com/cat.gif"}}


def _user(*parts: Any) -> list[dict[str, Any]]:
    return [{"role": "user", "content": ["look", *parts]}]


def test_415_on_an_inline_image_names_the_provider_refusal_and_mime() -> None:
    refusal = provider_media_refusal(415, _user(_GIF), provider="huggingface")

    assert refusal is not None
    assert refusal.status_code == 422
    assert refusal.info == {
        "code": "unsupported_content_part",
        "provider": "huggingface",
        "part_type": "image_url",
        "reason": "provider_unsupported_media image/gif",
        "message": (
            "huggingface cannot accept a image_url content part: "
            "provider_unsupported_media image/gif"
        ),
    }
    assert refusal.detail == refusal.info


def test_415_on_a_file_part_names_the_file_part_type() -> None:
    refusal = provider_media_refusal(415, _user(_PDF), provider="openrouter")

    assert refusal is not None
    assert refusal.info["part_type"] == "file"
    assert refusal.info["reason"] == "provider_unsupported_media application/pdf"


def test_every_distinct_mime_is_named_once_in_request_order() -> None:
    messages = [*_user(_GIF, _PNG, _GIF), {"role": "user", "content": [_PDF]}]

    refusal = provider_media_refusal(415, messages, provider="huggingface")

    assert refusal is not None
    assert refusal.info["part_type"] == "image_url"
    assert refusal.info["reason"] == (
        "provider_unsupported_media image/gif,image/png,application/pdf"
    )


def test_a_remote_image_has_no_known_mime() -> None:
    refusal = provider_media_refusal(415, _user(_REMOTE), provider="openai")

    assert refusal is not None
    assert refusal.info["part_type"] == "image_url"
    assert refusal.info["reason"] == "provider_unsupported_media"


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "hi"}],
        [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        [],
        None,
        "not-a-list",
        [None, 3, {"role": "user", "content": [None, 7, {"type": "text"}]}],
    ],
)
def test_415_without_a_media_part_is_not_a_content_part_refusal(messages: Any) -> None:
    assert provider_media_refusal(415, messages, provider="huggingface") is None


@pytest.mark.parametrize("status", [None, 400, 413, 422, 500, True])
def test_only_a_415_is_translated(status: Any) -> None:
    assert provider_media_refusal(status, _user(_GIF), provider="huggingface") is None
