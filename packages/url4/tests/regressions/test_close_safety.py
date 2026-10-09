"""Close is idempotent and safe under concurrency (regression safety net, F5 audit).

Ported from ``evidence/F5-transport/test_lifecycle.py``. Only the two close laws that
hold on the current code are kept. The tests that pin resurrection after close and the
raw RuntimeError during close are not ported: they pin buggy behaviour.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import url4.io.http as http_mod
from url4.io.http import HttpIOLayer
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
async def test_owned_io_concurrent_aclose_is_safe(mock_owned_client):
    owned = _OwnedIO(None)
    io = owned.outbound()
    await io.fetch("https://x/", relative=False)
    await asyncio.gather(owned.aclose(), owned.aclose())  # ref dropped before await
    assert owned._owned is None
    assert len(mock_owned_client) == 1
    assert mock_owned_client[0].is_closed
