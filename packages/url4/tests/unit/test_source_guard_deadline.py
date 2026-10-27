"""One absolute source deadline, enforced through body decoding (OME-1720).

No network: DNS answers come from an injected resolver and every connection is an
``httpx.MockTransport``. Most tests replace the guard's monotonic clock (``_now``) with a fake
one, so "the deadline passed while decoding" is deterministic rather than a race with the CPU.

FEATURE: url4 source fetch destination guard (OME-1544) — body-phase deadline (OME-1720).
STORY: as an operator, a source that streams compressed input decoding to nothing (empty gzip
members) is cut off at the total deadline with ``x.source_timeout`` — it never succeeds late.
"""

from __future__ import annotations

import asyncio
import codecs
import zlib
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import FetchRequest

PUBLIC = "93.184.216.34"


def _gzip(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    return compressor.compress(data) + compressor.flush()


EMPTY_MEMBER = _gzip(b"")


class _Clock:
    """A monotonic clock that advances ``step`` on every read (each read is one checkpoint)."""

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        self.now += self.step
        return self.now


class _Body(httpx.AsyncByteStream):
    """Chunks delivered without ever suspending, unless ``hang_after`` says otherwise."""

    def __init__(
        self,
        chunks: list[bytes],
        *,
        hang_after: int | None = None,
        on_chunk: Callable[[], None] | None = None,
    ) -> None:
        self.chunks = chunks
        self.hang_after = hang_after
        self.on_chunk = on_chunk
        self.yielded = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, chunk in enumerate(self.chunks):
            if self.hang_after is not None and index >= self.hang_after:
                await asyncio.Event().wait()
            if self.on_chunk is not None:
                self.on_chunk()
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _Net:
    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []
        self.handler: Callable[[httpx.Request], httpx.Response] = lambda _r: httpx.Response(200)

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        return [PUBLIC]

    def transport(self) -> httpx.AsyncBaseTransport:
        def record(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            return self.handler(request)

        return httpx.MockTransport(record)


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


def _gzip_response(body: _Body, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, headers={"Content-Encoding": "gzip", **headers}, stream=body)


async def _fetch(net: _Net, **guard: Any) -> str:
    async with HttpIOLayer(guard=SourceGuard(**guard), resolver=net.resolve) as io:
        return await io.fetch("https://example.com/", relative=False)


async def _timed_out(net: _Net, **guard: Any) -> ResolutionError:
    with pytest.raises(ResolutionError) as caught:
        await _fetch(net, **guard)
    assert caught.value.code == ErrorCode.SOURCE_TIMEOUT
    assert caught.value.permanent is False
    return caught.value


@pytest.mark.asyncio
async def test_empty_gzip_members_past_the_deadline_never_succeed(net: _Net, clock: _Clock) -> None:
    # ONE raw chunk (well under a decode step) of 500 members that decode to nothing, then a
    # real one: without a checkpoint inside the decode loop the fetch returned "late".
    body = _Body([EMPTY_MEMBER * 500 + _gzip(b"late")])
    net.handler = lambda _r: _gzip_response(body)
    await _timed_out(net, total_timeout=100)
    assert body.closed  # the source stream is closed on timeout
    assert clock.reads < 200  # checkpoints stopped decoding long before the 500th member


@pytest.mark.asyncio
async def test_chunks_that_overrun_the_deadline_stop_the_read(net: _Net, clock: _Clock) -> None:
    # Each chunk costs 20 units of (fake) time spent decoding to nothing, and the stream never
    # suspends — so asyncio's own timeout, on the loop's clock, could never fire.
    def spend() -> None:
        clock.now += 20

    body = _Body([EMPTY_MEMBER * 50] * 10 + [_gzip(b"late")], on_chunk=spend)
    net.handler = lambda _r: _gzip_response(body)
    await _timed_out(net, total_timeout=50)
    assert body.yielded < len(body.chunks)
    assert body.closed


@pytest.mark.asyncio
async def test_a_fetch_that_ends_after_the_deadline_is_a_timeout(net: _Net, clock: _Clock) -> None:
    # An EMPTY body has no chunk to checkpoint on: the result is still checked against the
    # deadline before it is returned.
    def slow(_request: httpx.Request) -> httpx.Response:
        clock.now += 1000
        return httpx.Response(200, stream=_Body([]))  # a stream that yields no chunk at all

    net.handler = slow
    await _timed_out(net, total_timeout=100)


@pytest.mark.asyncio
async def test_the_deadline_is_shared_across_redirect_hops(net: _Net, clock: _Clock) -> None:
    # Each hop alone fits in the budget; together they do not.
    def hop(request: httpx.Request) -> httpx.Response:
        members = _Body([EMPTY_MEMBER] * 30 + ([_gzip(b"ok")] if request.url.path == "/b" else []))
        if request.url.path == "/a":
            return _gzip_response(members, 302, Location="/b")
        return _gzip_response(members)

    async def run(total: float) -> str:
        async with HttpIOLayer(guard=SourceGuard(total_timeout=total), resolver=net.resolve) as io:
            return await io.fetch("https://example.com/a", relative=False)

    net.handler = hop
    assert await run(1000) == "ok"
    first, second = net.sent
    deadline = first.extensions[guarded_mod.FETCH_STATE].deadline
    assert deadline is not None
    assert second.extensions[guarded_mod.FETCH_STATE].deadline == deadline
    with pytest.raises(ResolutionError) as caught:
        await run(45)
    assert caught.value.code == ErrorCode.SOURCE_TIMEOUT


@pytest.mark.asyncio
async def test_the_stream_is_closed_when_the_fetch_is_cancelled(net: _Net) -> None:
    started = asyncio.Event()
    body = _Body([_gzip(b"a"), _gzip(b"b")], hang_after=1, on_chunk=started.set)
    net.handler = lambda _r: _gzip_response(body)
    task = asyncio.create_task(_fetch(net))
    await started.wait()  # the first chunk is out; the stream now hangs on the second
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert body.closed


@pytest.mark.asyncio
async def test_empty_members_between_real_ones_still_decode(net: _Net, clock: _Clock) -> None:
    body = _Body([EMPTY_MEMBER * 3 + _gzip(b"hel") + EMPTY_MEMBER + _gzip(b"lo")])
    net.handler = lambda _r: _gzip_response(body)
    assert await _fetch(net, total_timeout=1000) == "hello"


@pytest.mark.asyncio
async def test_the_decoded_cap_still_applies_under_the_deadline(net: _Net, clock: _Clock) -> None:
    body = _Body([_gzip(b"x" * 64)])
    net.handler = lambda _r: _gzip_response(body)
    with pytest.raises(ResolutionError) as caught:
        await _fetch(net, total_timeout=1000, max_bytes=16)
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE


@pytest.mark.asyncio
async def test_a_transport_request_without_a_deadline_is_not_timed(net: _Net) -> None:
    # A request built outside HttpIOLayer carries no FetchState deadline; only caps apply.
    net.handler = lambda _r: _gzip_response(_Body([EMPTY_MEMBER * 10 + _gzip(b"ok")]))
    transport = guarded_mod.GuardedTransport(SourceGuard(), resolver=net.resolve)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        response = await client.get("https://example.com/")
    assert response.text == "ok"


@pytest.mark.asyncio
async def test_a_non_suspending_body_still_honours_an_external_cancel(net: _Net) -> None:
    # Review finding (OME-1720): the stream never suspends on its own, so only the capped
    # stream's yield to the event loop lets a cancellation in before the body is fully read.
    holder: list[asyncio.Task[str]] = []

    def cancel_soon() -> None:
        if body.yielded == 0:
            asyncio.get_running_loop().call_soon(holder[0].cancel)

    body = _Body([b"a" * 16] * 8, on_chunk=cancel_soon)
    net.handler = lambda _r: httpx.Response(200, stream=body)
    holder.append(asyncio.create_task(_fetch(net)))
    with pytest.raises(asyncio.CancelledError):
        await holder[0]
    assert body.yielded < len(body.chunks)
    assert body.closed


SLOW_CHARSET = "url4-test-slow"


@pytest.fixture
def slow_charset(clock: _Clock) -> Iterator[list[float]]:
    """A registered charset whose every decode call costs ``cost[0]`` units of (fake) time."""
    cost = [0.0]
    ascii_codec = codecs.lookup("ascii")

    class _SlowDecoder(codecs.IncrementalDecoder):
        def decode(self, input: bytes, final: bool = False) -> str:
            clock.now += cost[0]
            return bytes(input).decode("ascii")

    def search(name: str) -> codecs.CodecInfo | None:
        if name.replace("_", "-") != SLOW_CHARSET:
            return None
        return codecs.CodecInfo(
            ascii_codec.encode,
            ascii_codec.decode,
            incrementaldecoder=_SlowDecoder,
            name=SLOW_CHARSET,
        )

    codecs.register(search)
    try:
        yield cost
    finally:
        codecs.unregister(search)


async def _fetch_text(net: _Net, *, extended: bool) -> str:
    async with HttpIOLayer(guard=SourceGuard(total_timeout=100), resolver=net.resolve) as io:
        if extended:
            return (await io.fetch_ex(FetchRequest("https://example.com/"))).body
        return await io.fetch("https://example.com/", relative=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("extended", [False, True], ids=["fetch", "fetch_ex"])
async def test_slow_charset_decoding_never_produces_a_late_success(
    net: _Net, slow_charset: list[float], extended: bool
) -> None:
    # Review finding (PR #1555, H1): the body arrived in time, but converting it to text ran
    # after the last deadline check — a slow charset decoder returned "ok" past the deadline.
    def text(_request: httpx.Request) -> httpx.Response:
        headers = {"Content-Type": f"text/plain; charset={SLOW_CHARSET}"}
        return httpx.Response(200, headers=headers, stream=_Body([b"ok"]))

    net.handler = text
    assert await _fetch_text(net, extended=extended) == "ok"  # a fast decode still succeeds
    slow_charset[0] = 1000
    with pytest.raises(ResolutionError) as caught:
        await _fetch_text(net, extended=extended)
    assert caught.value.code == ErrorCode.SOURCE_TIMEOUT
