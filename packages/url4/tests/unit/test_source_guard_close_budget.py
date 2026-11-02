"""Pool closes are bounded, time-limited, and their failures are never lost (PR #1555 review 3).

No network and no sleeps: every pool is a fake transport whose close is held on an event, fails
on demand, or never ends; deadlines are already-expired values or a replaced guard clock.

FEATURE: url4 source fetch destination guard (OME-1544) — bounded per-host pools (OME-1719).
STORY: as an operator of a long-lived node, fetching from ever more host names while closes
stall never piles up pools that are closing — at most ``limit`` are retained and ``limit`` more
are closing from idle evictions, plus at most one per request in flight for pools evicted while
busy — and every close failure is reported by the next completed shutdown.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io._guarded_transport import FETCH_STATE, FetchState, GuardedTransport
from url4.io._host_pools import CLOSE_TIMEOUT, HostPools
from url4.io.http import SourceGuard

PUBLIC = "93.184.216.34"


class _Body(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"body"


class _Pool(httpx.AsyncBaseTransport):
    """A pool whose close can be held on ``gate``, fail with ``error``, or never end."""

    def __init__(
        self, *, gate: asyncio.Event | None = None, error: BaseException | None = None
    ) -> None:
        self.gate = gate
        self.error = error
        self.started = asyncio.Event()
        self.closed = 0
        self.aborted = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Body())

    async def aclose(self) -> None:
        self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
        except asyncio.CancelledError:
            self.aborted = True
            raise
        self.closed += 1
        if self.error is not None:
            raise self.error


def _maker(
    *, gate: asyncio.Event | None = None, error: BaseException | None = None
) -> tuple[list[_Pool], HostPools]:
    made: list[_Pool] = []

    def factory() -> httpx.AsyncBaseTransport:
        made.append(_Pool(gate=gate, error=error))
        return made[-1]

    return made, HostPools(factory, limit=1)


def test_the_close_timeout_is_ten_seconds() -> None:
    assert CLOSE_TIMEOUT == 10.0


@pytest.mark.asyncio
async def test_a_cancelled_shutdown_keeps_a_failing_close_s_error_for_the_retry() -> None:
    # Review 3, finding 1: a close that failed after its shutdown was cancelled was logged and
    # forgotten — the retry saw no task and reported a clean shutdown.
    gate, error = asyncio.Event(), OSError("socket close failed")
    failing = _Pool(gate=gate, error=error)
    pools = HostPools(lambda: failing, limit=1)
    await (await pools.acquire("a.example")).release()
    shutdown = asyncio.create_task(pools.aclose())
    await failing.started.wait()
    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    gate.set()
    await asyncio.wait(set(pools._closing))  # the close fails with no shutdown awaiting it
    assert failing.closed == 1
    assert not pools._closing
    with pytest.raises(ExceptionGroup) as caught:
        await pools.aclose()
    assert caught.value.exceptions == (error,)
    await pools.aclose()  # reported once: a completed shutdown consumed it


@pytest.mark.asyncio
async def test_a_request_path_close_failure_is_reported_by_the_next_shutdown() -> None:
    error = OSError("socket close failed")
    made, pools = _maker(error=error)
    await (await pools.acquire("a.example")).release()
    await (await pools.acquire("b.example")).release()  # evicts idle a.example: its close fails
    await asyncio.wait(set(pools._closing))
    with pytest.raises(ExceptionGroup) as caught:
        await pools.aclose()
    assert error in caught.value.exceptions
    assert [pool.closed for pool in made] == [1, 1]


@pytest.mark.asyncio
async def test_kept_close_failures_are_bounded_and_the_rest_counted() -> None:
    made, pools = _maker(error=OSError("socket close failed"))
    for index in range(6):
        await (await pools.acquire(f"h{index}.example")).release()
        if pools._closing:
            await asyncio.wait(set(pools._closing))
    with pytest.raises(ExceptionGroup) as caught:
        await pools.aclose()
    assert len(caught.value.exceptions) == 1  # at most `limit` failures are kept...
    assert "5 more" in caught.value.message  # ...and the others are counted, not lost
    assert [pool.closed for pool in made] == [1] * 6


@pytest.mark.asyncio
async def test_many_hosts_with_stalled_closes_never_exceed_the_close_budget() -> None:
    # Review 3, finding 2: limit=1 and 1,000 unique hosts with held closes left 999 closes (and
    # their transports) pending. Retained + closing pools must stay within 2 * limit.
    gate = asyncio.Event()
    made, pools = _maker(gate=gate)
    refused = 0
    for index in range(1000):
        try:
            lease = await pools.acquire(f"h{index}.example", timeout=0)
        except TimeoutError:
            refused += 1
        else:
            await lease.release()
        assert len(pools) + len(pools._closing) <= 2
        assert sum(1 for pool in made if not pool.closed) <= 2
    assert len(made) == 2  # h0 (closing, held) and h1 (retained): nothing else was ever built
    assert refused == 998
    gate.set()
    await pools.aclose()
    assert [pool.closed for pool in made] == [1, 1]


@pytest.mark.asyncio
async def test_an_evicting_acquire_waits_for_a_free_close_slot() -> None:
    gate = asyncio.Event()
    made, pools = _maker(gate=gate)
    await (await pools.acquire("a.example")).release()
    await (await pools.acquire("b.example")).release()  # a.example's close holds the slot
    await made[0].started.wait()
    waiting = asyncio.create_task(pools.acquire("c.example"))
    done, _ = await asyncio.wait({waiting}, timeout=0)
    assert not done  # no slot: the acquire waits, it does not start a second close
    assert len(made) == 2
    gate.set()
    await (await waiting).release()  # the slot freed: b.example is evicted, c.example served
    assert list(pools) == ["c.example"]
    await pools.aclose()
    assert [pool.closed for pool in made] == [1, 1, 1]


@pytest.mark.asyncio
async def test_an_acquire_that_is_not_evicting_never_waits_for_a_slot() -> None:
    gate = asyncio.Event()
    _made, pools = _maker(gate=gate)
    await (await pools.acquire("a.example")).release()
    await (await pools.acquire("b.example")).release()
    lease = await pools.acquire("b.example", timeout=0)  # retained host: no eviction, no wait
    await lease.release()
    busy = await pools.acquire("b.example")
    lease = await pools.acquire("c.example", timeout=0)  # busy victim: retired, nothing closes
    await lease.release()
    await busy.release()
    gate.set()
    await pools.aclose()


@pytest.mark.asyncio
async def test_a_close_past_its_timeout_is_aborted_and_reported() -> None:
    stalled = _Pool(gate=asyncio.Event())  # a close that never ends on its own
    pools = HostPools(lambda: stalled, limit=1, close_timeout=0)
    await (await pools.acquire("a.example")).release()
    with pytest.raises(ExceptionGroup) as caught:
        await pools.aclose()
    (failure,) = caught.value.exceptions
    assert isinstance(failure, TimeoutError)
    assert "aborted" in str(failure)
    assert stalled.aborted  # the close in progress was cancelled, not left running
    assert stalled.closed == 0


@pytest.mark.asyncio
async def test_a_close_s_own_timeout_error_is_not_relabelled() -> None:
    error = TimeoutError("the peer's close_notify timed out")
    pools = HostPools(lambda: _Pool(error=error), limit=1)
    await (await pools.acquire("a.example")).release()
    with pytest.raises(ExceptionGroup) as caught:
        await pools.aclose()
    assert caught.value.exceptions == (error,)


async def _resolve(host: str, port: int) -> Sequence[str]:
    return [PUBLIC]


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> tuple[asyncio.Event, list[_Pool]]:
    """Guarded-transport pools whose closes are held on one gate; the guard clock reads 100."""
    gate = asyncio.Event()
    made: list[_Pool] = []

    def factory() -> httpx.AsyncBaseTransport:
        made.append(_Pool(gate=gate))
        return made[-1]

    monkeypatch.setattr(guarded_mod, "_inner_transport", factory)
    monkeypatch.setattr(guarded_mod, "_now", lambda: 100.0)
    return gate, made


def _with_deadline(client: httpx.AsyncClient, host: str, deadline: float) -> httpx.Request:
    extensions = {FETCH_STATE: FetchState(deadline=deadline)}
    return client.build_request("GET", f"https://{host}/", extensions=extensions)


@pytest.mark.asyncio
async def test_waiting_for_a_close_slot_past_the_fetch_deadline_is_a_source_timeout(
    held: tuple[asyncio.Event, list[_Pool]],
) -> None:
    gate, made = held
    transport = GuardedTransport(SourceGuard(), resolver=_resolve, max_hosts=1)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        await client.get("https://a.example/")
        await client.get("https://b.example/")  # a.example's held close fills the budget
        task = asyncio.create_task(client.send(_with_deadline(client, "c.example", 150.0)))
        done, _ = await asyncio.wait({task}, timeout=0)
        assert not done  # 50 units of deadline left: it waits for the slot...
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ResolutionError) as caught:
            # ...but past its deadline it is refused at once.
            await client.send(_with_deadline(client, "c.example", 50.0))
        assert caught.value.code == ErrorCode.SOURCE_TIMEOUT
        assert caught.value.permanent is False
        assert len(made) == 2
        gate.set()


@pytest.mark.asyncio
async def test_busy_victims_close_outside_the_budget_bounded_by_requests_in_flight() -> None:
    # Review 4, finding 2 (owner: narrow the invariant, no new waits). A pool evicted while a
    # request holds it closes on that request's release, outside the close budget — so the
    # executable bound is closing <= budget + requests in flight, not 2 * limit.
    gate = asyncio.Event()
    made, pools = _maker(gate=gate)
    held = [await pools.acquire(f"h{index}.example", timeout=0) for index in range(20)]
    assert len(pools) == 1  # retained stays at `limit` while every lease is held...
    assert not pools._closing  # ...and nothing closes under a request in flight
    for lease in held:
        await lease.release()
        assert len(pools._closing) <= 1 + len(held)  # budget (limit=1) + leases held
    assert len(pools) + len(pools._closing) <= 1 + 1 + len(held)  # retained + budget + held
    assert len(pools._closing) == 19  # every busy victim started its close on release
    gate.set()
    await pools.aclose()
    assert [pool.closed for pool in made] == [1] * 20
