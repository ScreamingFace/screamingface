"""Resource-lifecycle class invariants for HttpIOLayer, _OwnedIO and Url4Node.aclose.

Proposed invariants (what `_check_invariants()` would assert):
  HttpIOLayer   I1  self._client is not None  ->  self._owned is None   (inject XOR own)
                I2  closed  ->  self._owned is None                      (no live client after close)
                I3  closed is terminal: no fetch creates a client after aclose
  _OwnedIO      I4  self._injected is not None  ->  self._owned is None
                I5  closed  ->  self._owned is None, and stays None
The code has no `closed` state at all, so I3/I5 cannot hold by construction —
these tests show what happens instead (resurrection, raw RuntimeError).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import url4.io.http as http_mod
from url4.core.errors import ResolutionError
from url4.io.http import HttpIOLayer
from url4.peer._owned import _OwnedIO
from url4.peer.server import Url4Node


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


async def test_double_close_is_harmless(mock_owned_client):
    io = HttpIOLayer()
    assert await io.fetch("https://x/", relative=False) == "BODY"
    await io.aclose()
    await io.aclose()
    assert io._owned is None


async def test_use_after_close_resurrects_a_client(mock_owned_client):
    io = HttpIOLayer()
    await io.fetch("https://x/", relative=False)
    await io.aclose()
    # I3 says this should be refused; instead a SECOND client is created and owned
    assert await io.fetch("https://x/", relative=False) == "BODY"
    assert len(mock_owned_client) == 2 and io._owned is not None
    await io.aclose()


async def test_fetch_during_aclose_escapes_as_raw_runtime_error(mock_owned_client):
    io = HttpIOLayer()
    await io.fetch("https://x/", relative=False)
    closing = asyncio.create_task(io.aclose())
    await asyncio.sleep(0)  # aclose is now suspended inside client.aclose(); _owned still set
    with pytest.raises(Exception) as info:
        await io.fetch("https://x/", relative=False)
    await closing
    print("\nfetch during aclose raised:", type(info.value).__name__, info.value)
    # The documented contract: "Any HTTP failure surfaces as ResolutionError".
    assert not isinstance(info.value, ResolutionError)
    assert isinstance(info.value, RuntimeError)


async def test_owned_io_resurrects_after_close(mock_owned_client):
    owned = _OwnedIO(None)
    first = owned.outbound()
    await owned.aclose()
    second = owned.outbound()  # I5 violated: a fresh adapter after close
    assert second is not first and owned._owned is second


async def test_node_aclose_then_outbound_fetch_creates_unclosed_adapter(mock_owned_client):
    node = Url4Node("n")
    async with node:
        await node.fetch("https://x/", relative=False)
    # lifespan shutdown == node.aclose(); a request still running afterwards:
    assert await node.fetch("https://x/", relative=False) == "BODY"
    assert node._owned._owned is not None  # nobody will close this one
    await node.aclose()


async def test_owned_io_concurrent_aclose_is_safe(mock_owned_client):
    owned = _OwnedIO(None)
    io = owned.outbound()
    await io.fetch("https://x/", relative=False)
    await asyncio.gather(owned.aclose(), owned.aclose())  # ref dropped before await
    assert owned._owned is None
