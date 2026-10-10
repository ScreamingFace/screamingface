"""Closing is final, and close is idempotent and safe under concurrency (E8, F5 audit).

Closing an adapter is final (E8): after ``aclose`` a fetch or ``outbound()`` raises
RuntimeError and never builds a new client or adapter. The RuntimeError is deliberate:
use after close is a caller bug, not a ResolutionError. Close is also idempotent and
safe under concurrency. The F5 tests are ported from ``evidence/F5-transport/test_lifecycle.py``.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import url4.io.http as http_mod
from url4.io.http import HttpIOLayer
from url4.io.static import StaticIOLayer
from url4.peer._owned import _OwnedIO


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="BODY")


class _SlowCloseTransport(httpx.MockTransport):
    """A transport whose aclose yields to the loop, like a real pool draining."""

    async def aclose(self) -> None:
        await asyncio.sleep(0.05)


@pytest.fixture
def mock_owned_client(monkeypatch):
    """Make HttpIOLayer's OWNED client use a mock transport (white-box, test-only)."""
    created: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def factory(**kw):
        c = real(transport=_SlowCloseTransport(_ok), **kw)
        created.append(c)
        return c

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", factory)
    return created


@pytest.mark.asyncio
async def test_double_close_is_harmless(mock_owned_client):
    io = HttpIOLayer()
    assert await io.fetch("https://x/", relative=False) == "BODY"
    await io.aclose()
    await io.aclose()
    assert io._owned is None
    assert len(mock_owned_client) == 1
    assert mock_owned_client[0].is_closed


@pytest.mark.asyncio
async def test_double_close_then_fetch_raises(mock_owned_client):
    io = HttpIOLayer()
    assert await io.fetch("https://x/", relative=False) == "BODY"
    await io.aclose()
    await io.aclose()
    with pytest.raises(RuntimeError, match="HttpIOLayer is closed"):
        await io.fetch("https://x/", relative=False)
    assert io._owned is None
    assert len(mock_owned_client) == 1  # no new client was built after close


@pytest.mark.asyncio
async def test_injected_client_is_not_closed_and_fetch_after_close_raises():
    client = httpx.AsyncClient(transport=httpx.MockTransport(_ok))
    io = HttpIOLayer(client=client)
    await io.aclose()
    with pytest.raises(RuntimeError, match="HttpIOLayer is closed"):
        await io.fetch("https://x/", relative=False)
    assert not client.is_closed  # closed is final for the adapter, not the client
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_during_aclose_raises(mock_owned_client):
    io = HttpIOLayer()
    assert await asyncio.wait_for(io.fetch("https://x/", relative=False), 5) == "BODY"
    closing = asyncio.create_task(io.aclose())
    await asyncio.sleep(0)  # aclose runs up to its await in the slow transport close
    assert not closing.done()  # the close is still awaiting its 50 ms drain
    with pytest.raises(RuntimeError, match="HttpIOLayer is closed"):
        await asyncio.wait_for(io.fetch("https://x/", relative=False), 5)
    await asyncio.wait_for(closing, 5)
    assert mock_owned_client[0].is_closed


@pytest.mark.asyncio
async def test_owned_io_concurrent_aclose_is_safe(mock_owned_client):
    owned = _OwnedIO(None)
    io = owned.outbound()
    await io.fetch("https://x/", relative=False)
    await asyncio.gather(owned.aclose(), owned.aclose())  # ref dropped before await
    assert owned._owned is None
    assert len(mock_owned_client) == 1
    assert mock_owned_client[0].is_closed


@pytest.mark.asyncio
async def test_owned_outbound_after_close_raises():
    owned = _OwnedIO(None)
    owned.outbound()
    await owned.aclose()
    with pytest.raises(RuntimeError, match="its owned IO adapter was closed"):
        owned.outbound()


@pytest.mark.asyncio
async def test_injected_outbound_after_close_is_still_returned():
    injected = StaticIOLayer()
    owned = _OwnedIO(injected)
    await owned.aclose()
    assert owned.outbound() is injected
