"""The bytes fetch stays on the raw-body path yet keeps the text path's deadline and caps.

After PR #1555 the text paths decode inside the deadline-checked GET; ``fetch_bytes`` must not
inherit that decode (a binary body is never charset-decoded) but must keep the one absolute
deadline (OME-1720) and the raw/decoded byte caps (spec F1b).

FEATURE: image and PDF inputs for url4 sources (epic OME-1529).
STORY: as an operator I expose a node that fetches binary sources; a PNG is returned byte for
byte, never decoded as text, and a source that answers after the total deadline or past the
size cap fails exactly as a text source would.
No network: the guarded transport's inner transport is a mock; the guard's clock is faked.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import FetchRequest

PUBLIC = "93.184.216.34"
# Not valid UTF-8 (0x89, 0xff): any text decode would mangle them.
PNG = b"\x89PNG\r\n\x1a\n\x00\xff\xfe"


class _Clock:
    """A monotonic clock that advances one unit per read; tests jump it with ``now``."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


class _Net:
    def __init__(self) -> None:
        self.handler: Callable[[httpx.Request], httpx.Response] = lambda _r: httpx.Response(200)

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        return [PUBLIC]

    def transport(self) -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(lambda request: self.handler(request))


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> _Net:
    fake = _Net()
    monkeypatch.setattr(guarded_mod, "_inner_transport", fake.transport)
    return fake


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(guarded_mod, "_now", fake)
    return fake


@pytest.fixture
def no_text_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any ``httpx.Response.text`` access fails the test: the bytes path must never decode."""

    def refuse(_self: httpx.Response) -> str:
        raise AssertionError("fetch_bytes decoded the body as text")

    monkeypatch.setattr(httpx.Response, "text", property(refuse))


async def _fetch_bytes(net: _Net, **guard: Any) -> bytes:
    async with HttpIOLayer(guard=SourceGuard(**guard), resolver=net.resolve) as io:
        return (await io.fetch_bytes(FetchRequest("https://example.com/a.png"))).body


async def _failure(net: _Net, **guard: Any) -> ResolutionError:
    with pytest.raises(ResolutionError) as caught:
        await _fetch_bytes(net, **guard)
    return caught.value


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_text_decode")
async def test_fetch_bytes_never_decodes_text_even_with_a_charset(net: _Net) -> None:
    # A charset on the Content-Type is exactly what would make a text decode tempting.
    headers = {"Content-Type": "image/png; charset=utf-8"}
    net.handler = lambda _r: httpx.Response(200, headers=headers, content=PNG)
    assert await _fetch_bytes(net) == PNG


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_text_decode")
async def test_fetch_bytes_that_ends_after_the_deadline_is_a_timeout(
    net: _Net, clock: _Clock
) -> None:
    # An EMPTY body has no chunk to checkpoint on: only the check after reading the raw bytes
    # can catch the late answer.
    def late(_request: httpx.Request) -> httpx.Response:
        clock.now += 1000
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"")

    net.handler = late
    error = await _failure(net, total_timeout=100)
    assert error.code == ErrorCode.SOURCE_TIMEOUT
    assert error.permanent is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_text_decode")
async def test_fetch_bytes_whose_body_read_passes_the_deadline_is_a_timeout(
    net: _Net, clock: _Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mirror of the slow-codec case on the text path (PR #1555, H1): the transport saw the body
    # arrive in time, but handing it over ran past the deadline. The check after reading the
    # raw bytes — not a text decode — must turn that into a timeout.
    raw_content: Any = vars(httpx.Response)["content"]  # the property object itself

    def slow_content(response: httpx.Response) -> bytes:
        clock.now += 1000
        body: bytes = raw_content.fget(response)
        return body

    net.handler = lambda _r: httpx.Response(200, headers={"Content-Type": "image/png"}, content=PNG)
    monkeypatch.setattr(httpx.Response, "content", property(slow_content))
    error = await _failure(net, total_timeout=100)
    assert error.code == ErrorCode.SOURCE_TIMEOUT


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_text_decode")
async def test_fetch_bytes_in_time_still_succeeds(net: _Net, clock: _Clock) -> None:
    net.handler = lambda _r: httpx.Response(200, headers={"Content-Type": "image/png"}, content=PNG)
    assert await _fetch_bytes(net, total_timeout=100) == PNG


@pytest.mark.asyncio
async def test_fetch_bytes_enforces_the_raw_byte_cap(net: _Net) -> None:
    net.handler = lambda _r: httpx.Response(200, headers={"Content-Type": "image/png"}, content=PNG)
    error = await _failure(net, max_bytes=len(PNG) - 1)
    assert error.code == ErrorCode.SOURCE_TOO_LARGE


@pytest.mark.asyncio
async def test_fetch_bytes_enforces_the_decoded_byte_cap(net: _Net) -> None:
    # A small gzip body that inflates past the cap: the decoded size is what counts.
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    bomb = compressor.compress(b"\x00" * 4096) + compressor.flush()
    headers = {"Content-Type": "image/png", "Content-Encoding": "gzip"}
    net.handler = lambda _r: httpx.Response(200, headers=headers, content=bomb)
    error = await _failure(net, max_bytes=1024)
    assert error.code == ErrorCode.SOURCE_TOO_LARGE
