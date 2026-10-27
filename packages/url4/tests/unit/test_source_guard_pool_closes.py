"""Closing the guarded transport's per-host pools never fails a request (PR #1555 review).

No network: every pool is a fake transport whose close can be held open by the test or made to
raise, so a close's failure or slowness can be placed exactly against a request or a shutdown.

FEATURE: url4 source fetch destination guard (OME-1544) — bounded per-host pools (OME-1719).
STORY: as an operator, a socket error while an evicted pool closes is logged, never turned into
the failure of a fetch that succeeded; and shutting the adapter down finishes every close, even
when the shutdown itself is cancelled and retried.
"""

from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.io._guarded_transport import GuardedTransport
from url4.io._host_pools import HostPools
from url4.io.http import SourceGuard

PUBLIC = "93.184.216.34"
POOLS_LOGGER = "url4.io._host_pools"
CLOSE_FAILED = "closing a per-host connection pool failed"
BROKEN_BODY_HOST = "broken-body.example"


class _Closer(httpx.AsyncBaseTransport):
    """A pool whose close can be held on ``gate`` and/or fail with ``error``."""

    def __init__(
        self, *, gate: asyncio.Event | None = None, error: BaseException | None = None
    ) -> None:
        self.gate = gate
        self.error = error
        self.started = asyncio.Event()
        self.closed = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == BROKEN_BODY_HOST:
            return httpx.Response(200, stream=_BrokenBody())
        return httpx.Response(200, stream=_Body())

    async def aclose(self) -> None:
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        self.closed += 1
        if self.error is not None:
            raise self.error


class _Body(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"body"


class _BrokenBody(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"part"
        raise httpx.ReadError("connection reset mid-body")


async def _resolve(host: str, port: int) -> Sequence[str]:
    return [PUBLIC]


@pytest.fixture
def broken(monkeypatch: pytest.MonkeyPatch) -> list[_Closer]:
    """Every per-host pool the guarded transport makes fails when it is closed."""
    made: list[_Closer] = []

    def factory() -> httpx.AsyncBaseTransport:
        made.append(_Closer(error=OSError("socket close failed")))
        return made[-1]

    monkeypatch.setattr(guarded_mod, "_inner_transport", factory)
    return made


def _client(max_hosts: int) -> tuple[httpx.AsyncClient, GuardedTransport]:
    transport = GuardedTransport(SourceGuard(), resolver=_resolve, max_hosts=max_hosts)
    return httpx.AsyncClient(transport=transport, trust_env=False), transport


async def _closes_settle(pools: HostPools) -> None:
    """Let every close started so far finish, without awaiting through the request path."""
    await asyncio.wait(set(pools._closing))


def _close_failures(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == POOLS_LOGGER and r.message == CLOSE_FAILED]


@pytest.mark.asyncio
async def test_a_failing_close_of_an_evicted_busy_pool_never_fails_a_request(
    broken: list[_Closer], caplog: pytest.LogCaptureFixture
) -> None:
    # Review finding (Ionesio, _host_pools.py:121): the last release awaited the close, so its
    # OSError came out of `response.aclose()` and failed a fetch whose body was fully read.
    caplog.set_level(logging.WARNING)
    client, transport = _client(max_hosts=1)
    in_flight = await client.send(client.build_request("GET", "https://a.example/"), stream=True)
    assert (await client.get("https://b.example/")).content == b"body"  # evicts busy a.example
    assert await in_flight.aread() == b"body"  # its release starts the failing close: no raise
    await in_flight.aclose()
    await _closes_settle(transport._pools)
    a_pool = broken[0]
    assert a_pool.closed == 1
    (record,) = _close_failures(caplog)
    assert isinstance(record.exc_info and record.exc_info[1], OSError)
    with pytest.raises(ExceptionGroup):
        await transport.aclose()  # b.example's own failing close is reported at shutdown


@pytest.mark.asyncio
async def test_a_failing_close_of_an_idle_victim_never_fails_the_evicting_request(
    broken: list[_Closer], caplog: pytest.LogCaptureFixture
) -> None:
    # Review finding (Ionesio, _host_pools.py:108): acquire("b") awaited idle victim a's close,
    # so a's OSError failed b's request — and a's close time counted against b's deadline.
    caplog.set_level(logging.WARNING)
    client, transport = _client(max_hosts=1)
    assert (await client.get("https://a.example/")).content == b"body"
    assert (await client.get("https://b.example/")).content == b"body"
    await _closes_settle(transport._pools)
    assert broken[0].closed == 1
    assert len(_close_failures(caplog)) == 1


@pytest.mark.asyncio
async def test_a_drop_path_close_failure_is_logged_not_left_unretrieved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Review finding (Ionesio, _host_pools.py:147): a close started from a release/drop has no
    # awaiter; a failure there must be logged, not end as "Task exception was never retrieved".
    caplog.set_level(logging.WARNING)
    victim = _Closer(error=OSError("socket close failed"))
    made = iter([victim, _Closer()])
    pools = HostPools(lambda: next(made), limit=1)
    lease = await pools.acquire("a.example")
    await pools.acquire("b.example")  # evicts a.example while its lease is held
    await lease.release()  # starts the failing close; never raises into the releaser
    await _closes_settle(pools)
    del lease
    gc.collect()
    assert victim.closed == 1
    assert len(_close_failures(caplog)) == 1
    assert not [r for r in caplog.records if "never retrieved" in r.getMessage()]


@pytest.mark.asyncio
async def test_a_cancelled_shutdown_abandons_no_close_and_a_retry_completes_them() -> None:
    # Review finding (HupBaHa 2): cancelling aclose() cancelled the closes it gathered, and a
    # later aclose() had nothing left to finish them with.
    gate = asyncio.Event()
    made = [_Closer(gate=gate), _Closer(gate=gate)]
    supply = iter(made)
    pools = HostPools(lambda: next(supply), limit=2)
    for host in ("a.example", "b.example"):
        await (await pools.acquire(host)).release()
    shutdown = asyncio.create_task(pools.aclose())
    await made[0].started.wait()
    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    gate.set()
    await pools.aclose()
    assert [pool.closed for pool in made] == [1, 1]


@pytest.mark.asyncio
async def test_shutdown_waits_for_every_close_and_reports_failures_as_a_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Review finding (Ionesio, _host_pools.py:147): gather() without return_exceptions returned
    # at the first failed close while the others still ran.
    caplog.set_level(logging.WARNING)
    gate = asyncio.Event()
    error = OSError("socket close failed")
    failing, slow = _Closer(error=error), _Closer(gate=gate)
    supply = iter([failing, slow])
    pools = HostPools(lambda: next(supply), limit=2)
    for host in ("a.example", "b.example"):
        await (await pools.acquire(host)).release()
    shutdown = asyncio.create_task(pools.aclose())
    await slow.started.wait()
    assert not shutdown.done()
    gate.set()
    with pytest.raises(ExceptionGroup) as caught:
        await shutdown
    assert caught.value.exceptions == (error,)
    assert slow.closed == 1  # the slow close finished before shutdown reported anything
    assert len(_close_failures(caplog)) == 1


@pytest.mark.asyncio
async def test_a_failing_close_never_replaces_the_request_s_own_error(
    broken: list[_Closer], caplog: pytest.LogCaptureFixture
) -> None:
    # Review finding (HupBaHa, last paragraph): cleanup must not replace an in-flight exception.
    # The body read fails; releasing the evicted pool then starts a close that fails too.
    caplog.set_level(logging.WARNING)
    client, transport = _client(max_hosts=1)
    request = client.build_request("GET", f"https://{BROKEN_BODY_HOST}/")
    in_flight = await client.send(request, stream=True)
    await client.get("https://b.example/")  # evicts the busy pool
    with pytest.raises(httpx.ReadError, match="mid-body"):
        await in_flight.aread()
    await in_flight.aclose()
    await _closes_settle(transport._pools)
    assert broken[0].closed == 1
    assert len(_close_failures(caplog)) == 1
    with pytest.raises(ExceptionGroup):
        await transport.aclose()
