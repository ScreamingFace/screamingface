"""The close-capability port and the shared lazy-owned-io helper.

STORY: as an SDK embedder I can rely on a Client/Url4Node closing the transport
it created and never the one I injected; ``_OwnedIO`` is the one place that rule
lives (F2/F7).
"""

from __future__ import annotations

import pytest

from url4.io.layer import IOLayer, SupportsClose
from url4.io.static import StaticIOLayer
from url4.peer._owned import _OwnedIO

pytestmark = pytest.mark.asyncio


class _TrackedIO:
    """A minimal IOLayer that records its own closes."""

    def __init__(self, closed: list[bool]) -> None:
        self._closed = closed

    async def fetch(self, target: str, *, relative: bool) -> str:
        return target

    async def aclose(self) -> None:
        self._closed.append(True)


async def test_supports_close_is_a_runtime_capability() -> None:
    # a closer is recognized by the aclose name alone (structural, runtime_checkable)
    assert isinstance(_TrackedIO([]), SupportsClose)
    assert not isinstance(StaticIOLayer(), SupportsClose)
    assert isinstance(_TrackedIO([]), IOLayer)


async def test_real_factory_builds_an_httpx_layer_and_closes() -> None:
    # Exercises the default lazy transport import with no network: HttpIOLayer
    # creates its httpx client only on first fetch, so creation+close is safe.
    from url4.io.http import HttpIOLayer

    owner = _OwnedIO(None)
    assert isinstance(owner.outbound(), HttpIOLayer)
    await owner.aclose()


async def test_injected_layer_is_returned_and_never_closed() -> None:
    injected = StaticIOLayer(fetch_map={"https://x": "content"})
    owner = _OwnedIO(injected)
    assert owner.outbound() is injected
    await owner.aclose()
    assert await owner.outbound().fetch("https://x", relative=False) == "content"


async def test_owned_layer_is_created_once_closed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    created: list[int] = []

    def fake_http_io() -> IOLayer:
        created.append(1)
        return _TrackedIO(closed)

    monkeypatch.setattr("url4.peer._owned._http_io", fake_http_io)
    owner = _OwnedIO(None)
    first = owner.outbound()
    assert owner.outbound() is first  # created lazily and reused
    assert created == [1]
    await owner.aclose()
    assert closed == [True]


async def test_close_is_idempotent_and_a_fresh_adapter_follows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    def fake_http_io() -> IOLayer:
        return _TrackedIO(closed)

    monkeypatch.setattr("url4.peer._owned._http_io", fake_http_io)
    owner = _OwnedIO(None)
    first = owner.outbound()
    await owner.aclose()
    await owner.aclose()  # a second close of an already-closed owner is a no-op
    assert closed == [True]
    assert owner.outbound() is not first


async def test_async_context_manager_closes_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    def fake_http_io() -> IOLayer:
        return _TrackedIO(closed)

    monkeypatch.setattr("url4.peer._owned._http_io", fake_http_io)
    async with _OwnedIO(None) as owner:
        owner.outbound()
        assert closed == []
    assert closed == [True]


async def test_exception_info_passes_through_the_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    # __aexit__ takes *exc_info untouched, so an exception raised in the body
    # still propagates while the owned layer is closed.
    closed: list[bool] = []

    def fake_http_io() -> IOLayer:
        return _TrackedIO(closed)

    monkeypatch.setattr("url4.peer._owned._http_io", fake_http_io)

    with pytest.raises(RuntimeError, match="boom"):
        async with _OwnedIO(None) as owner:
            owner.outbound()
            raise RuntimeError("boom")
    assert closed == [True]
