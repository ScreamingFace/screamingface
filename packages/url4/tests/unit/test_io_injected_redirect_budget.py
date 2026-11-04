"""An injected client's redirect bodies draw from the URL4 byte limiter too (PR #1482 review).

FEATURE: image and PDF inputs (epic OME-1529; push security review "resource-cap-defeat").
STORY: as a node operator who injects my own ``httpx.AsyncClient(follow_redirects=True)``, a
hostile 3xx with a large body is refused by the request's ``max_bytes`` and charged to its
live ``on_chunk`` budget before it is buffered, exactly as the final body is.

WHY: with ``follow_redirects=True`` httpx ``aread()``s every redirect body before returning the
final response, so a cap applied only to that final response is too late. URL4 drives the
redirects itself and reads each hop through its limiter. No network: mock transports only.
"""

from __future__ import annotations

import httpx
import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest

URL = "https://files.example/start"
NEXT = "https://files.example/final"


class _Hook:
    def __init__(self) -> None:
        self.seen = 0

    def __call__(self, size: int) -> None:
        self.seen += size


def _chain(redirect_body: bytes, final_body: bytes, seen: list[httpx.Request]):
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == URL:
            return httpx.Response(302, content=redirect_body, headers={"location": NEXT})
        return httpx.Response(200, content=final_body, headers={"content-type": "image/png"})

    return answer


@pytest.mark.asyncio
async def test_an_oversized_redirect_body_is_refused_and_charged_to_the_hook() -> None:
    seen: list[httpx.Request] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_chain(b"r" * 4096, b"x", seen)), follow_redirects=True
    )
    hook = _Hook()
    try:
        with pytest.raises(ResolutionError) as caught:
            await HttpIOLayer(client=client).fetch_bytes(
                FetchRequest(URL, max_bytes=1024, on_chunk=hook)
            )
    finally:
        await client.aclose()
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    # INVARIANT: the redirect's bytes reached the live budget before they were held.
    assert hook.seen == 4096
    assert [str(r.url) for r in seen] == [URL]  # the next hop was never requested


@pytest.mark.asyncio
async def test_every_hops_bytes_reach_the_hook_exactly_once() -> None:
    seen: list[httpx.Request] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_chain(b"r" * 512, b"x" * 600, seen)),
        follow_redirects=True,
    )
    hook = _Hook()
    try:
        got = await HttpIOLayer(client=client).fetch_bytes(
            FetchRequest(URL, max_bytes=1024, on_chunk=hook)
        )
    finally:
        await client.aclose()
    assert got.body == b"x" * 600 and got.media_type == "image/png"
    assert hook.seen == 512 + 600
    assert [str(r.url) for r in seen] == [URL, NEXT]


@pytest.mark.asyncio
async def test_a_client_that_does_not_follow_redirects_still_does_not() -> None:
    seen: list[httpx.Request] = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(_chain(b"r", b"x", seen)))
    try:
        with pytest.raises(ResolutionError):
            await HttpIOLayer(client=client).fetch_bytes(FetchRequest(URL))
    finally:
        await client.aclose()
    assert [str(r.url) for r in seen] == [URL]


@pytest.mark.asyncio
async def test_a_cross_origin_hop_drops_the_clients_authorization() -> None:
    # WHY: the hops are built by httpx's own redirect builder, so its header hygiene holds.
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "files.example":
            return httpx.Response(302, headers={"location": "https://other.example/x"})
        return httpx.Response(200, content=b"ok")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(answer),
        follow_redirects=True,
        headers={"authorization": "Bearer secret"},
    )
    try:
        got = await HttpIOLayer(client=client).fetch_bytes(FetchRequest(URL))
    finally:
        await client.aclose()
    assert got.body == b"ok"
    assert "authorization" in seen[0].headers
    assert "authorization" not in seen[1].headers
