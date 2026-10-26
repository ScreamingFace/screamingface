"""The guarded transport's per-host connection pools stay bounded (OME-1719).

No network: every per-host pool is a recording ``httpx.MockTransport`` whose responses can be
held open, so a test can keep a request in flight while other host names evict its pool.

FEATURE: url4 source fetch destination guard (OME-1544) — bounded per-host pools (OME-1719).
STORY: as an operator running a long-lived Client or Url4Node, fetching from ever more host
names never grows the guard's retained pools past a fixed bound, and no request in flight is
ever cut off when its host's pool is evicted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.io._guarded_transport import GuardedTransport
from url4.io._host_pools import HostPools
from url4.io.http import HttpIOLayer, SourceGuard

PUBLIC = "93.184.216.34"


class _Held(httpx.AsyncByteStream):
    """A two-chunk body that records whether it was closed."""

    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"held-"
        yield b"body"

    async def aclose(self) -> None:
        self.closed = True


class _Pool(httpx.MockTransport):
    """One per-host pool: records which host it served and whether it was closed."""

    def __init__(self, net: _Net) -> None:
        super().__init__(self._handle)
        self.net = net
        self.hosts: list[str] = []
        self.closed = 0

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.hosts.append(request.headers["host"])
        if self.net.refuse:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, stream=_Held())

    async def aclose(self) -> None:
        self.closed += 1


class _Net:
    def __init__(self) -> None:
        self.pools: list[_Pool] = []
        self.refuse = False

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        return [PUBLIC]

    def transport(self) -> httpx.AsyncBaseTransport:
        pool = _Pool(self)
        self.pools.append(pool)
        return pool

    def pool_for(self, host: str) -> list[_Pool]:
        return [pool for pool in self.pools if host in pool.hosts]


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> _Net:
    fake = _Net()
    monkeypatch.setattr(guarded_mod, "_inner_transport", fake.transport)
    return fake


def _client(net: _Net, max_hosts: int) -> tuple[httpx.AsyncClient, GuardedTransport]:
    transport = GuardedTransport(SourceGuard(), resolver=net.resolve, max_hosts=max_hosts)
    return httpx.AsyncClient(transport=transport, trust_env=False), transport


async def _get(client: httpx.AsyncClient, host: str) -> bytes:
    response = await client.get(f"https://{host}/")
    return response.content


async def _open(client: httpx.AsyncClient, host: str) -> httpx.Response:
    """A request left IN FLIGHT: its headers arrived, its body is not read or closed."""
    return await client.send(client.build_request("GET", f"https://{host}/"), stream=True)


@pytest.mark.asyncio
async def test_many_host_names_never_exceed_the_default_bound(net: _Net) -> None:
    hosts = [f"h{i}.example" for i in range(guarded_mod.MAX_HOST_POOLS + 8)]
    async with HttpIOLayer(resolver=net.resolve) as io:
        for host in hosts:
            assert await io.fetch(f"https://{host}/", relative=False) == "held-body"
            guarded = io._get_client()._transport
            assert isinstance(guarded, GuardedTransport)
            assert len(guarded._pools) <= guarded_mod.MAX_HOST_POOLS
        assert list(guarded._pools) == hosts[-guarded_mod.MAX_HOST_POOLS :]
    # The 8 oldest pools were closed on eviction, each exactly once.
    assert [pool.closed for pool in net.pools[:8]] == [1] * 8


@pytest.mark.asyncio
async def test_an_evicted_idle_pool_is_closed(net: _Net) -> None:
    client, transport = _client(net, max_hosts=2)
    async with client:
        for host in ("a.example", "b.example", "c.example"):
            assert await _get(client, host) == b"held-body"
        assert list(transport._pools) == ["b.example", "c.example"]
        (a_pool,) = net.pool_for("a.example")
        assert a_pool.closed == 1
        assert [pool.closed for pool in net.pool_for("c.example")] == [0]


@pytest.mark.asyncio
async def test_the_least_recently_used_host_is_the_one_evicted(net: _Net) -> None:
    client, transport = _client(net, max_hosts=2)
    async with client:
        for host in ("a.example", "b.example", "a.example", "c.example"):
            await _get(client, host)
        assert list(transport._pools) == ["a.example", "c.example"]
        assert net.pool_for("b.example")[0].closed == 1
        assert net.pool_for("a.example")[0].closed == 0
        assert len(net.pool_for("a.example")) == 1  # reused, not rebuilt


@pytest.mark.asyncio
async def test_eviction_never_interrupts_a_request_in_flight(net: _Net) -> None:
    client, transport = _client(net, max_hosts=2)
    async with client:
        in_flight = await _open(client, "a.example")
        await _get(client, "b.example")
        await _get(client, "c.example")  # evicts a.example's pool from the map...
        assert "a.example" not in transport._pools
        (a_pool,) = net.pool_for("a.example")
        assert a_pool.closed == 0  # ...but never closes it under the open request
        assert await in_flight.aread() == b"held-body"  # the request completes intact
        assert a_pool.closed == 1  # and the pool closes once that request is done


@pytest.mark.asyncio
async def test_overlapping_requests_keep_an_evicted_pool_open_until_the_last_ends(
    net: _Net,
) -> None:
    client, _transport = _client(net, max_hosts=1)
    async with client:
        first = await _open(client, "a.example")
        second = await _open(client, "a.example")
        await _get(client, "b.example")
        (a_pool,) = net.pool_for("a.example")
        await first.aclose()
        await first.aclose()  # a second close of the same response releases nothing more
        assert a_pool.closed == 0
        assert await second.aread() == b"held-body"
        assert a_pool.closed == 1


@pytest.mark.asyncio
async def test_a_completed_request_leaves_its_pool_evictable(net: _Net) -> None:
    client, _transport = _client(net, max_hosts=1)
    async with client:
        await _get(client, "a.example")
        await _get(client, "b.example")
        assert net.pool_for("a.example")[0].closed == 1


@pytest.mark.asyncio
async def test_a_failed_connection_leaves_its_pool_evictable(net: _Net) -> None:
    client, _transport = _client(net, max_hosts=1)
    async with client:
        net.refuse = True
        with pytest.raises(httpx.ConnectError):
            await _get(client, "a.example")
        net.refuse = False
        await _get(client, "b.example")
        assert net.pool_for("a.example")[0].closed == 1


@pytest.mark.asyncio
async def test_a_re_requested_host_after_eviction_gets_a_fresh_pool(net: _Net) -> None:
    # INVARIANT: Host/SNI isolation survives eviction — a closed pool is never reused.
    client, _transport = _client(net, max_hosts=1)
    async with client:
        await _get(client, "a.example")
        await _get(client, "b.example")
        await _get(client, "a.example")
        first, second = net.pool_for("a.example")
        assert first is not second
        assert first.closed == 1 and second.closed == 0
        assert second.hosts == ["a.example"]


@pytest.mark.asyncio
async def test_transport_shutdown_closes_retained_and_evicted_busy_pools(net: _Net) -> None:
    client, transport = _client(net, max_hosts=1)
    in_flight = await _open(client, "a.example")
    await _get(client, "b.example")
    await transport.aclose()
    assert [pool.closed for pool in net.pools] == [1, 1]
    assert len(transport._pools) == 0
    await in_flight.aclose()  # a late release after shutdown never closes a pool twice
    assert [pool.closed for pool in net.pools] == [1, 1]
    await client.aclose()


@pytest.mark.asyncio
async def test_adapter_shutdown_closes_every_pool(net: _Net) -> None:
    io = HttpIOLayer(guard=SourceGuard(), resolver=net.resolve)
    for host in ("a.example", "b.example"):
        await io.fetch(f"https://{host}/", relative=False)
    await io.aclose()
    assert [pool.closed for pool in net.pools] == [1, 1]


def test_the_bound_must_keep_at_least_one_pool() -> None:
    with pytest.raises(ValueError, match="max_hosts"):
        GuardedTransport(SourceGuard(), max_hosts=0)


@pytest.mark.asyncio
async def test_a_lease_released_twice_frees_its_pool_only_once(net: _Net) -> None:
    # INVARIANT: a double release must not let a pool another request still uses be closed.
    pools = HostPools(net.transport, limit=1)
    first = await pools.acquire("a.example")
    second = await pools.acquire("a.example")
    await pools.acquire("b.example")  # evicts a.example while both leases are held
    await first.release()
    await first.release()
    assert net.pools[0].closed == 0
    await second.release()
    assert net.pools[0].closed == 1
    await pools.aclose()
