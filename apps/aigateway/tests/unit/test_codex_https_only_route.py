"""Codex forwards only https image URLs (owner decision on PR #1479, 2026-10-20).

FEATURE: image and file input across the gateway (OME-1529, OME-1542).
INVARIANT: no plaintext image URL is ever forwarded — not even a local one. OpenAI fetches
Codex image URLs, so a local http address could not be reached anyway, and for every other
provider a local address is exactly the SSRF target the data:-only rule exists to refuse.
"""

from __future__ import annotations

import pytest

from aigateway.core.content_parts import UnsupportedContentPart
from aigateway.core.media_intake import refuse_remote_media

from .test_chat_remote_media_route import _body, cache_probe  # noqa: F401  (fixture reuse)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a.png",
        "HTTP://example.com/a.png",
        "http://localhost:8000/a.png",
        "http://127.0.0.1/a.png",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_codex_refuses_a_plaintext_image_url(url: str) -> None:
    with pytest.raises(UnsupportedContentPart) as caught:
        refuse_remote_media(
            [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}],
            provider="codex",
            allow_remote_image_urls=True,
        )
    assert caught.value.info["reason"] == "remote_url_not_https"


def test_codex_still_forwards_an_https_image_url() -> None:
    refuse_remote_media(
        [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
                ],
            }
        ],
        provider="codex",
        allow_remote_image_urls=True,
    )


def test_route_refuses_a_plaintext_image_url_for_codex_before_the_cache(
    authenticated_client,
    cache_probe: list[str],  # noqa: F811
) -> None:
    http_image = {"type": "image_url", "image_url": {"url": "http://example.com/a.png"}}
    resp = authenticated_client.post("/v1/chat/completions", json=_body("codex/gpt-5", http_image))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "remote_url_not_https"
    assert cache_probe == []
