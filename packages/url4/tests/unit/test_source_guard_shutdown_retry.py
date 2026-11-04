"""A cancelled public shutdown never makes a pool-close failure unreachable (PR #1555 review 4).

No network and no sleeps: the guarded transport's per-host pool is a fake whose close is held on
an event and then fails, so the shutdown can be cancelled mid-close and retried.

FEATURE: url4 source fetch destination guard (OME-1544) — bounded per-host pools (OME-1719).
STORY: as an SDK embedder, if my ``HttpIOLayer``/``Client``/``Url4Node`` shutdown is cancelled
(a timeout around it, a cancelled task) and I retry it, the retry still reports the close failure
— it never silently reports a clean shutdown.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import IOLayer
from url4.peer._owned import _OwnedIO

PUBLIC = "93.184.216.34"


class _Body(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"body"


class _FailingClose(httpx.AsyncBaseTransport):
    """A per-host pool whose close waits on ``gate`` and then fails."""

    def __init__(self, gate: asyncio.Event, error: Exception) -> None:
        self.gate = gate
        self.error = error
        self.started = asyncio.Event()
        self.ended = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Body())

    async def aclose(self) -> None:
        self.started.set()
        try:
            await self.gate.wait()
            raise self.error
        finally:
            self.ended.set()


async def _resolve(host: str, port: int) -> Sequence[str]:
    return [PUBLIC]


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> _FailingClose:
    made = _FailingClose(asyncio.Event(), OSError("socket close failed"))
    monkeypatch.setattr(guarded_mod, "_inner_transport", lambda: made)
    return made


async def _cancel_mid_close(closing: asyncio.Task[None], pool: _FailingClose) -> None:
    await pool.started.wait()
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    pool.gate.set()
    await pool.ended.wait()  # the close fails while no shutdown is waiting for it


@pytest.mark.asyncio
async def test_a_cancelled_adapter_shutdown_retry_reports_the_close_failure(
    pool: _FailingClose,
) -> None:
    io = HttpIOLayer(guard=SourceGuard(), resolver=_resolve)
    assert await io.fetch("https://a.example/", relative=False) == "body"
    await _cancel_mid_close(asyncio.create_task(io.aclose()), pool)
    with pytest.raises(ExceptionGroup) as caught:
        await io.aclose()
    assert caught.value.exceptions == (pool.error,)
    await io.aclose()  # observed once by a caller that was not cancelled: now a no-op
    assert io._owned is None


@pytest.mark.asyncio
async def test_concurrent_adapter_shutdowns_share_one_close(pool: _FailingClose) -> None:
    io = HttpIOLayer(guard=SourceGuard(), resolver=_resolve)
    await io.fetch("https://a.example/", relative=False)
    first, second = asyncio.create_task(io.aclose()), asyncio.create_task(io.aclose())
    await pool.started.wait()
    pool.gate.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert all(isinstance(result, ExceptionGroup) for result in results)


@pytest.mark.asyncio
async def test_a_cancelled_client_or_node_shutdown_retry_reports_the_close_failure(
    pool: _FailingClose, monkeypatch: pytest.MonkeyPatch
) -> None:
    def http_io() -> IOLayer:
        return HttpIOLayer(guard=SourceGuard(), resolver=_resolve)

    monkeypatch.setattr("url4.peer._owned._http_io", http_io)
    owned = _OwnedIO(None)
    assert await owned.outbound().fetch("https://a.example/", relative=False) == "body"
    await _cancel_mid_close(asyncio.create_task(owned.aclose()), pool)
    with pytest.raises(ExceptionGroup) as caught:
        await owned.aclose()
    assert caught.value.exceptions == (pool.error,)
    await owned.aclose()
    assert owned._owned is None
    with pytest.raises(RuntimeError, match="closed"):
        owned.outbound()


class _GatedLayer:
    """An owned IO layer whose own close is held on ``gate`` and then fails."""

    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate
        self.closes = 0

    async def fetch(self, target: str, *, relative: bool) -> str:
        return target

    async def aclose(self) -> None:
        self.closes += 1
        await self.gate.wait()
        raise ExceptionGroup("closing failed", [OSError("socket close failed")])


@pytest.mark.asyncio
async def test_owned_io_keeps_its_close_across_a_cancelled_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    layer = _GatedLayer(gate)
    monkeypatch.setattr("url4.peer._owned._http_io", lambda: layer)
    owned = _OwnedIO(None)
    owned.outbound()
    closing = asyncio.create_task(owned.aclose())
    done, _ = await asyncio.wait({closing}, timeout=0)
    assert not done
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    gate.set()
    with pytest.raises(ExceptionGroup):
        await owned.aclose()
    assert layer.closes == 1  # the retry awaited the SAME close; it did not start another
