"""Fallback among a name's vetted DNS answers after a connection failure (OME-1718).

No network: DNS answers come from an injected resolver and every pinned connection attempt is
answered by an ``httpx.MockTransport`` keyed on the vetted address it was pinned to.

FEATURE: url4 source fetch destination guard (OME-1544) — address fallback (OME-1718).
STORY: as an operator, a source whose first DNS answer is down is still fetched through its
next vetted answer, and a fallback never reaches an address the guard did not vet, never
re-resolves the name and never resends a request that already went out.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard

A1 = "93.184.216.34"
A2 = "93.184.216.35"
A3 = "93.184.216.36"
A4 = "93.184.216.37"

Behaviour = Callable[[httpx.Request], httpx.Response]


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _connect_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("connect timed out", request=request)


def _read_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadError("connection reset after the request was sent", request=request)


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="BODY")


class _Net:
    """A resolver table plus a per-address behaviour for every pinned attempt."""

    def __init__(self) -> None:
        self.dns: dict[str, list[str]] = {}
        self.lookups: list[str] = []
        self.attempts: list[httpx.Request] = []
        self.by_address: dict[str, Behaviour] = {}

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.lookups.append(host)
        return self.dns[host]

    def transport(self) -> httpx.AsyncBaseTransport:
        def attempt(request: httpx.Request) -> httpx.Response:
            self.attempts.append(request)
            return self.by_address.get(request.url.host, _ok)(request)

        return httpx.MockTransport(attempt)


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> _Net:
    fake = _Net()
    monkeypatch.setattr(guarded_mod, "_inner_transport", fake.transport)
    return fake


def _io(net: _Net, **guard: Any) -> HttpIOLayer:
    return HttpIOLayer(guard=SourceGuard(**guard), resolver=net.resolve)


async def _fetch_error(net: _Net, url: str, **guard: Any) -> ResolutionError:
    async with _io(net, **guard) as io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch(url, relative=False)
    return caught.value


@pytest.mark.asyncio
async def test_an_unreachable_first_answer_falls_back_to_the_second(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    net.by_address[A1] = _refuse
    async with _io(net) as io:
        assert await io.fetch("https://example.com/a.txt", relative=False) == "BODY"
    assert [r.url.host for r in net.attempts] == [A1, A2]
    second = net.attempts[1]
    # INVARIANT: the fallback keeps the name's Host header and TLS SNI.
    assert second.headers["host"] == "example.com"
    assert second.extensions["sni_hostname"] == "example.com"
    assert second.url.path == "/a.txt"
    assert net.lookups == ["example.com"]  # no second DNS lookup


@pytest.mark.asyncio
async def test_a_connect_timeout_on_the_first_answer_also_falls_back(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    net.by_address[A1] = _connect_timeout
    async with _io(net) as io:
        assert await io.fetch("https://example.com/", relative=False) == "BODY"
    assert [r.url.host for r in net.attempts] == [A1, A2]


@pytest.mark.asyncio
async def test_a_reachable_first_answer_is_the_only_attempt(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    async with _io(net) as io:
        assert await io.fetch("https://example.com/", relative=False) == "BODY"
    assert [r.url.host for r in net.attempts] == [A1]


@pytest.mark.asyncio
async def test_a_mixed_answer_set_is_refused_before_any_connection(net: _Net) -> None:
    # The private answer is LAST: the whole set is vetted before the first attempt.
    net.dns["mixed.example"] = [A1, A2, "10.0.0.7"]
    net.by_address[A1] = _refuse
    error = await _fetch_error(net, "https://mixed.example/")
    assert error.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert net.attempts == []


@pytest.mark.asyncio
async def test_a_failure_after_the_request_was_sent_is_never_retried(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    net.by_address[A1] = _read_error
    error = await _fetch_error(net, "https://example.com/")
    assert error.code == ErrorCode.RESOLUTION_FAILED
    assert [r.url.host for r in net.attempts] == [A1]  # A2 never sees a resend


@pytest.mark.asyncio
async def test_an_http_error_status_is_never_retried_on_another_address(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    net.by_address[A1] = lambda _r: httpx.Response(503)
    error = await _fetch_error(net, "https://example.com/")
    assert error.permanent is False
    assert [r.url.host for r in net.attempts] == [A1]


@pytest.mark.asyncio
async def test_every_answer_refusing_is_a_resolution_failure(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    net.by_address[A1] = _refuse
    net.by_address[A2] = _refuse
    error = await _fetch_error(net, "https://example.com/")
    assert error.code == ErrorCode.RESOLUTION_FAILED
    assert error.permanent is False
    assert [r.url.host for r in net.attempts] == [A1, A2]


@pytest.mark.asyncio
async def test_every_answer_timing_out_is_a_source_timeout(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    net.by_address[A1] = _connect_timeout
    net.by_address[A2] = _connect_timeout
    error = await _fetch_error(net, "https://example.com/")
    assert error.code == ErrorCode.SOURCE_TIMEOUT
    assert [r.url.host for r in net.attempts] == [A1, A2]


@pytest.mark.asyncio
async def test_fallback_is_bounded_to_the_attempt_limit(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2, A3, A4]
    for address in (A1, A2, A3, A4):
        net.by_address[address] = _refuse
    await _fetch_error(net, "https://example.com/")
    limit = guarded_mod.MAX_ADDRESS_ATTEMPTS
    assert [r.url.host for r in net.attempts] == [A1, A2, A3, A4][:limit]


@pytest.mark.asyncio
async def test_every_attempt_carries_the_connect_timeout(net: _Net) -> None:
    net.dns["example.com"] = [A1, A2]
    net.by_address[A1] = _refuse
    async with _io(net, connect_timeout=2.5) as io:
        await io.fetch("https://example.com/", relative=False)
    assert [r.extensions["timeout"]["connect"] for r in net.attempts] == [2.5, 2.5]


@pytest.mark.asyncio
async def test_hanging_attempts_stop_at_the_total_deadline(
    net: _Net, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every attempt hangs: the fallback never extends the one total deadline.
    async def hang(request: httpx.Request) -> httpx.Response:
        net.attempts.append(request)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(guarded_mod, "_inner_transport", lambda: httpx.MockTransport(hang))
    net.dns["example.com"] = [A1, A2]
    started = time.monotonic()
    error = await _fetch_error(net, "https://example.com/", total_timeout=0.2)
    assert error.code == ErrorCode.SOURCE_TIMEOUT
    assert time.monotonic() - started < 2.0
    assert [r.url.host for r in net.attempts] == [A1]


@pytest.mark.asyncio
async def test_an_ip_literal_has_exactly_one_attempt(net: _Net) -> None:
    net.by_address[A1] = _refuse
    error = await _fetch_error(net, f"https://{A1}/")
    assert error.code == ErrorCode.RESOLUTION_FAILED
    assert [r.url.host for r in net.attempts] == [A1]
    assert net.lookups == []
