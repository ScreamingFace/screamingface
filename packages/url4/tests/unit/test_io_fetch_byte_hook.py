"""A bytes fetch reads no more than its caller's live byte budget allows (push security review).

FEATURE: image and PDF inputs (epic OME-1529; push security review "resource-cap-defeat",
owner decision 2026-11-03: shared live budget).
STORY: as a node operator, a run's concurrent attachment flights draw from ONE byte budget as
their bytes arrive, so a run cannot make the node download and hold many bodies of up to the
per-response cap before the per-run cap refuses it.

``FetchRequest.on_chunk`` is told the size of every decoded chunk as it arrives (it raises to
abort the read); ``FetchRequest.max_bytes`` is a per-request ceiling, and the stricter of it and
the source guard's ``max_bytes`` wins. No network: the transports are recording mocks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes, fetch_bytes
from url4.io.static import StaticIOLayer

MIB = 1024 * 1024
CHUNK = 64 * 1024
URL = "https://files.example/big.bin"


class _Budget(Exception):
    """The test's stand-in for the caller's budget refusal."""


class _CountingStream(httpx.AsyncByteStream):
    """A body of ``size`` bytes in ``CHUNK`` pieces that records how many were actually read."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        left = self.size
        while left > 0:
            piece = min(CHUNK, left)
            left -= piece
            self.read += piece
            yield b"\0" * piece


class _Hook:
    """An ``on_chunk`` that counts what it is told and raises past ``limit``."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit
        self.seen = 0
        self.calls = 0

    def __call__(self, size: int) -> None:
        self.calls += 1
        self.seen += size
        if self.limit is not None and self.seen > self.limit:
            raise _Budget(self.seen)


async def _public(host: str, port: int) -> Sequence[str]:
    return ["93.184.216.34"]


class _Server:
    """Answers every guarded request with a fresh counting body of ``size`` bytes."""

    def __init__(self) -> None:
        self.size = 20 * MIB
        self.streams: list[_CountingStream] = []

    @property
    def read(self) -> int:
        return self.streams[-1].read


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    served = _Server()

    def transport() -> httpx.AsyncBaseTransport:
        def answer(request: httpx.Request) -> httpx.Response:
            stream = _CountingStream(served.size)
            served.streams.append(stream)
            return httpx.Response(200, stream=stream, headers={"content-type": "image/png"})

        return httpx.MockTransport(answer)

    monkeypatch.setattr(guarded_mod, "_inner_transport", transport)
    return served


async def _fetch(request: FetchRequest) -> FetchedBytes:
    io = HttpIOLayer(resolver=_public)
    try:
        return await io.fetch_bytes(request)
    finally:
        await io.aclose()


@pytest.mark.asyncio
async def test_on_chunk_aborts_a_20_mib_body_after_about_8_mb_on_the_guarded_path(
    server: _Server,
) -> None:
    hook = _Hook(limit=8_000_000)
    with pytest.raises(_Budget):
        await _fetch(FetchRequest(URL, on_chunk=hook))
    read = server.read
    # INVARIANT: the read stops within one chunk of the budget, not at the 20 MiB guard cap.
    assert 8_000_000 < read <= 8_000_000 + CHUNK
    assert hook.seen <= 8_000_000 + CHUNK


@pytest.mark.asyncio
async def test_on_chunk_sees_every_decoded_byte_exactly_once_on_the_guarded_path(
    server: _Server,
) -> None:
    server.size = 3 * MIB + 7
    hook = _Hook()
    got = await _fetch(FetchRequest(URL, on_chunk=hook))
    assert len(got.body) == 3 * MIB + 7
    assert hook.seen == 3 * MIB + 7  # counted once — never by both the transport and the reader
    assert hook.calls > 1  # streamed, not told once after the whole body was held


@pytest.mark.asyncio
async def test_max_bytes_stricter_than_the_guard_cap_wins(server: _Server) -> None:
    with pytest.raises(ResolutionError) as caught:
        await _fetch(FetchRequest(URL, max_bytes=1_000_000))
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    assert caught.value.permanent is True
    assert server.read <= 1_000_000 + CHUNK


@pytest.mark.asyncio
async def test_max_bytes_looser_than_the_guard_cap_leaves_the_guard_cap(
    server: _Server,
) -> None:
    server.size = 20 * MIB + 1  # one byte over the guard's own 20 MiB cap
    with pytest.raises(ResolutionError) as caught:
        await _fetch(FetchRequest(URL, max_bytes=10**12))
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    assert server.read <= 20 * MIB + CHUNK


@pytest.mark.asyncio
async def test_max_bytes_at_exactly_the_body_size_passes(server: _Server) -> None:
    server.size = 1_000_000
    got = await _fetch(FetchRequest(URL, max_bytes=1_000_000))
    assert len(got.body) == 1_000_000


@pytest.mark.asyncio
async def test_on_chunk_is_honoured_by_an_injected_client() -> None:
    streams: list[_CountingStream] = []

    def answer(request: httpx.Request) -> httpx.Response:
        stream = _CountingStream(20 * MIB)
        streams.append(stream)
        return httpx.Response(200, stream=stream, headers={"content-type": "image/png"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    hook = _Hook(limit=8_000_000)
    try:
        with pytest.raises(_Budget):
            await HttpIOLayer(client=client).fetch_bytes(FetchRequest(URL, on_chunk=hook))
    finally:
        await client.aclose()
    assert 8_000_000 < streams[0].read <= 8_000_000 + CHUNK


@pytest.mark.asyncio
async def test_max_bytes_is_honoured_by_an_injected_client() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_CountingStream(2 * MIB))

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    try:
        with pytest.raises(ResolutionError) as caught:
            await HttpIOLayer(client=client).fetch_bytes(FetchRequest(URL, max_bytes=MIB))
    finally:
        await client.aclose()
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE


@pytest.mark.asyncio
async def test_static_layer_checks_the_hook_after_its_whole_read() -> None:
    io = StaticIOLayer({URL: b"x" * 100})
    hook = _Hook()
    got = await io.fetch_bytes(FetchRequest(URL, on_chunk=hook))
    assert got.body == b"x" * 100
    assert (hook.seen, hook.calls) == (100, 1)
    with pytest.raises(_Budget):
        await io.fetch_bytes(FetchRequest(URL, on_chunk=_Hook(limit=99)))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest(URL, max_bytes=99))
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    assert (await io.fetch_bytes(FetchRequest(URL, max_bytes=100))).body == b"x" * 100


@pytest.mark.asyncio
async def test_text_only_adapter_fallback_checks_the_hook_too() -> None:
    class _TextOnly:
        async def fetch(self, target: str, *, relative: bool) -> str:
            return "y" * 50

        async def fetch_ex(self, request: FetchRequest) -> FetchResult:
            return FetchResult("y" * 50, "text/plain")

    hook = _Hook()
    got = await fetch_bytes(_TextOnly(), FetchRequest(URL, on_chunk=hook))
    assert got.body == b"y" * 50 and hook.seen == 50
    with pytest.raises(ResolutionError) as caught:
        await fetch_bytes(_TextOnly(), FetchRequest(URL, max_bytes=49))
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE


def test_the_hook_is_not_part_of_a_requests_identity() -> None:
    # WHY: requests are compared and hashed as replay keys; a per-call hook must not split them.
    assert FetchRequest(URL, on_chunk=_Hook()) == FetchRequest(URL, on_chunk=_Hook())
    assert hash(FetchRequest(URL, on_chunk=_Hook())) == hash(FetchRequest(URL))


@pytest.mark.asyncio
async def test_a_redirect_hops_body_draws_from_the_hook_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY: httpx reads (and holds) a redirect's body itself before following it, so a hostile
    # 3xx with a large body must draw from the same live budget as the final body.
    hops: list[_CountingStream] = []

    def transport() -> httpx.AsyncBaseTransport:
        def answer(request: httpx.Request) -> httpx.Response:
            stream = _CountingStream(5 * MIB)
            hops.append(stream)
            return httpx.Response(302, stream=stream, headers={"location": URL + "?next"})

        return httpx.MockTransport(answer)

    monkeypatch.setattr(guarded_mod, "_inner_transport", transport)
    with pytest.raises(_Budget):
        await _fetch(FetchRequest(URL, on_chunk=_Hook(limit=MIB)))
    assert len(hops) == 1 and hops[0].read <= MIB + CHUNK
