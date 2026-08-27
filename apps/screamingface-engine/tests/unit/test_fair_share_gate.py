"""The fair-share gate contract (OME-908).

Every test is event-driven — a claim parks on an ``asyncio.Event`` until the test lets
it proceed — so scheduling is deterministic and nothing sleeps. The invariants pinned
here are the ones the OME-908 spec lists: near-equal shares under contention, full
capacity for a solo run, no permit leak on any cancellation path, and immediate share
reversion when a run ends.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from screamingface_engine.runner.fair_share import (
    FairShareGate,
    FairShareIOLayer,
    GateSnapshot,
    RunShare,
)


async def _settle(rounds: int = 3) -> None:
    """Let every already-scheduled task step until it parks (grants land within 2)."""
    for _ in range(rounds):
        await asyncio.sleep(0)


class _Claims:
    """One run's outstanding claims: tasks that hold a permit until released."""

    def __init__(self, gate: FairShareGate, run: str) -> None:
        self._gate = gate
        self._run = run
        self._hold = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def claim(self, count: int) -> None:
        for _ in range(count):
            self._tasks.append(asyncio.get_running_loop().create_task(self._one()))

    async def _one(self) -> None:
        await self._gate.acquire(self._run)
        try:
            await self._hold.wait()
        finally:
            self._gate.release(self._run)

    async def finish(self) -> None:
        """Release every claim and await it — the run's normal completion."""
        self._hold.set()
        # A task this test already cancelled and awaited stays cancelled; gathering it
        # again would re-raise its CancelledError instead of confirming the survivors.
        await asyncio.gather(*(task for task in self._tasks if not task.cancelled()))

    async def cancel(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def cancel_one(self) -> asyncio.Task[None]:
        task = self._tasks[-1]
        task.cancel()
        return task


def _share(snapshot: GateSnapshot, run: str) -> RunShare:
    return next(entry for entry in snapshot.runs if entry.run == run)


# --- construction -------------------------------------------------------------------------------


def test_capacity_must_be_a_positive_integer() -> None:
    with pytest.raises(ValueError):
        FairShareGate(0)
    with pytest.raises(TypeError):
        FairShareGate("8")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        FairShareGate(True)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_acquire_after_close_is_refused() -> None:
    gate = FairShareGate(1)
    await gate.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await gate.acquire("run-a")


# --- the fairness invariants --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_solo_run_reaches_the_whole_capacity() -> None:
    gate = FairShareGate(4)
    solo = _Claims(gate, "run-a")
    solo.claim(6)
    await _settle()

    snapshot = gate.snapshot()
    assert snapshot.in_flight == 4  # work-conserving: the run takes all of it
    assert _share(snapshot, "run-a") == RunShare(run="run-a", in_flight=4, waiting=2)
    await solo.finish()
    assert gate.snapshot().runs == ()


@pytest.mark.asyncio
async def test_a_freed_permit_flows_to_the_waiting_run_not_back_to_the_holder() -> None:
    """The core anti-starvation property: while run B waits, run A cannot re-grow."""
    gate = FairShareGate(2)
    holder = _Claims(gate, "run-a")
    holder.claim(2)  # A fills the gate
    newcomer = _Claims(gate, "run-b")
    newcomer.claim(1)  # B queues
    await _settle()
    assert _share(gate.snapshot(), "run-b").waiting == 1

    # A yields exactly one permit (a fetch completing) and immediately wants it back.
    gate.release("run-a")
    holder.claim(1)
    await _settle()

    # The freed permit went to B, not back to A: A is now 1 held + 1 waiting, B holds 1.
    snapshot = gate.snapshot()
    assert _share(snapshot, "run-a") == RunShare(run="run-a", in_flight=1, waiting=1)
    assert _share(snapshot, "run-b") == RunShare(run="run-b", in_flight=1, waiting=0)
    await holder.finish()
    await newcomer.finish()


@pytest.mark.asyncio
async def test_capacity_one_degenerates_to_strict_alternation() -> None:
    gate = FairShareGate(1)
    a = _Claims(gate, "run-a")
    b = _Claims(gate, "run-b")

    a.claim(1)
    b.claim(1)
    await _settle()
    assert _share(gate.snapshot(), "run-a").in_flight == 1
    assert _share(gate.snapshot(), "run-b").waiting == 1

    await a.finish()  # A's permit frees; B — the only waiter — must get it
    await _settle()
    assert _share(gate.snapshot(), "run-b").in_flight == 1

    await b.finish()
    assert gate.snapshot().runs == ()


@pytest.mark.asyncio
async def test_unbroken_demand_from_more_runs_than_capacity_cannot_starve() -> None:
    """N > capacity with CONTINUOUS demand: every run must be served, in rotation.

    The starvation shape this pins: a run whose wait queue never empties keeps the
    oldest tie-break stamp. If ties were broken by a fixed arrival order, a benchmark-
    sized run with an unbroken fetch backlog would win every tie at equal holdings and
    a later run would wait forever. The tie must ROTATE — each grant sends the run to
    the back of the tie line — so service round-robins once the seed backlog drains.
    """
    gate = FairShareGate(1)  # capacity 1: the strictest case — plan invariant 6
    hold = asyncio.Event()  # exactly one holder parks on it at a time (capacity 1)

    class _Chain:
        """One run's unbroken demand: a fetch parks holding, the next is queued."""

        def __init__(self, run: str) -> None:
            self.run = run
            self.acquired = asyncio.Event()
            self.tasks: list[asyncio.Task[None]] = []

        def demand(self) -> None:
            self.tasks.append(asyncio.get_running_loop().create_task(self._one()))

        async def _one(self) -> None:
            await gate.acquire(self.run)
            try:
                self.acquired.set()
                await hold.wait()
            finally:
                gate.release(self.run)

    chains = {run: _Chain(run) for run in ("run-a", "run-b", "run-c")}
    chains["run-a"].demand()
    await _settle(2)  # run-a's first fetch is granted and parks holding
    chains["run-a"].demand()  # run-a keeps a successor queued: the unbroken chain
    chains["run-b"].demand()
    chains["run-c"].demand()
    await _settle()

    served: list[str] = []
    for _ in range(10):
        holder = next(r.run for r in gate.snapshot().runs if r.in_flight == 1)
        served.append(holder)
        chains[holder].demand()  # replenish BEFORE releasing: the chain never breaks
        hold.set()  # the holder's fetch completes and releases its permit
        await asyncio.sleep(0)  # it resumed and released; the next grant is scheduled
        hold.clear()  # clear BEFORE the new holder resumes, so it parks holding
        await _settle(2)

    counts = {run: served.count(run) for run in chains}
    assert set(served) == set(chains)  # nobody starved — the core OME-908 promise
    assert max(counts.values()) - min(counts.values()) <= 1  # service rotates

    for chain in chains.values():
        for task in chain.tasks:
            task.cancel()
    await asyncio.gather(*(t for c in chains.values() for t in c.tasks), return_exceptions=True)
    await _settle()
    assert gate.snapshot().runs == () and gate.snapshot().in_flight == 0


@pytest.mark.asyncio
async def test_a_completed_run_reverts_its_share_immediately() -> None:
    """A finished run leaves no bookkeeping: its permits serve the waiting run at once."""
    gate = FairShareGate(2)
    a = _Claims(gate, "run-a")
    b = _Claims(gate, "run-b")
    a.claim(2)
    b.claim(1)
    await _settle()

    await a.finish()  # both permits released; B's waiter is granted one
    await _settle()

    snapshot = gate.snapshot()
    assert [entry.run for entry in snapshot.runs] == ["run-b"]  # A is fully forgotten
    assert _share(snapshot, "run-b").in_flight == 1
    await b.finish()
    assert gate.snapshot().runs == ()


# --- cancellation: no permit may leak on any path -------------------------------------------------


@pytest.mark.asyncio
async def test_a_waiter_cancelled_while_queued_is_removed_and_its_successor_served() -> None:
    gate = FairShareGate(1)
    a = _Claims(gate, "run-a")
    b = _Claims(gate, "run-b")
    c = _Claims(gate, "run-c")
    a.claim(1)
    b.claim(1)
    c.claim(1)
    await _settle()

    cancelled = b.cancel_one()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    await _settle()
    snapshot = gate.snapshot()
    # run-b is gone from the books entirely: cancelled while queued, it never held a
    # permit, so nothing of it remains for a later grant decision to consider.
    assert "run-b" not in {entry.run for entry in snapshot.runs}

    await a.finish()  # the freed permit must skip dead B and serve C
    await _settle()
    assert _share(gate.snapshot(), "run-c").in_flight == 1
    await c.finish()
    assert gate.snapshot().runs == ()


@pytest.mark.asyncio
async def test_cancelling_one_queued_waiter_leaves_its_runs_other_waiters_intact() -> None:
    """The real cancellation contract, waiter-by-waiter.

    What matters here is a run-scoped property: a waiter cancelled while queued drops
    only ITSELF, and that run's remaining waiters keep their places and still get
    served. (The other cancellation shape — a waiter cancelled after the grant landed
    in its future — is pinned by its own test above, including the permit return.)
    """
    gate = FairShareGate(1)
    holder = _Claims(gate, "run-a")
    holder.claim(1)  # fills the gate
    pair = _Claims(gate, "run-b")
    pair.claim(2)  # both of B's fetches queue behind A
    await _settle()
    assert _share(gate.snapshot(), "run-b").waiting == 2

    cancelled = pair.cancel_one()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    await _settle()
    assert _share(gate.snapshot(), "run-b").waiting == 1  # exactly one waiter dropped

    await holder.finish()
    await _settle()
    # The surviving B waiter was served by the freed permit.
    assert _share(gate.snapshot(), "run-b").in_flight == 1
    await pair.finish()
    assert gate.snapshot().runs == ()


@pytest.mark.asyncio
async def test_a_waiter_cancelled_after_grant_returns_the_permit() -> None:
    """The deterministic grant/cancellation race: the permit must come back.

    ``_pump`` grants into the waiter's future (``set_result`` schedules its resume);
    the waiter's task is then cancelled BEFORE it resumes. A done future refuses
    ``cancel()``, so ``Task.cancel`` sets ``_must_cancel`` and the resume throws
    ``CancelledError`` at ``await fut`` instead of delivering the grant. ``acquire``
    unwinds through ``_abandon``, which must recognize the granted future and return
    the permit — or every such race permanently eats one unit of capacity until all
    local fetches deadlock.
    """
    gate = FairShareGate(1)
    holder = _Claims(gate, "run-a")
    holder.claim(1)
    await _settle()

    waiter = asyncio.get_running_loop().create_task(gate.acquire("run-b"))
    await _settle(2)  # the waiter is parked, queued

    gate.release("run-a")  # grant lands in the waiter's future NOW (synchronous pump)
    assert gate.snapshot().granted_total == 2  # the race was truly entered: it was granted
    waiter.cancel()  # cancellation arrives AFTER set_result, BEFORE the resume

    with pytest.raises(asyncio.CancelledError):
        await waiter
    await _settle()

    # Nothing of the cancelled waiter remains: no permit booked, no bookkeeping.
    snapshot = gate.snapshot()
    assert snapshot.in_flight == 0
    assert "run-b" not in {entry.run for entry in snapshot.runs}

    # The returned permit still admits a later claimant — the deadlock consequence.
    successor = _Claims(gate, "run-c")
    successor.claim(1)
    await _settle()
    assert _share(gate.snapshot(), "run-c").in_flight == 1
    await successor.finish()
    await holder.finish()
    assert gate.snapshot().runs == ()


@pytest.mark.asyncio
async def test_a_whole_cancelled_run_leaves_nothing_behind() -> None:
    gate = FairShareGate(3)
    doomed = _Claims(gate, "run-a")
    doomed.claim(3)  # holds everything
    waiter = _Claims(gate, "run-b")
    waiter.claim(2)  # two queued
    await _settle()

    await doomed.cancel()  # holding tasks cancelled: fetch-style finally must release
    await _settle()

    snapshot = gate.snapshot()
    assert _share(snapshot, "run-b").in_flight == 2  # the freed permits served B
    assert snapshot.in_flight == 2
    await waiter.finish()
    assert gate.snapshot().runs == ()


# --- the IOLayer wrapper -------------------------------------------------------------------------


class _CapabilityInner:
    """An inner layer exposing every capability port, with controllable fetches."""

    def __init__(self) -> None:
        self.fetches: list[str] = []
        self.proceed = asyncio.Event()
        self.fail = False

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        if self.fail:
            raise RuntimeError("inner exploded")
        await self.proceed.wait()
        return f"got:{target}"

    async def fetch_ex(self, request: Any) -> str:
        return await self.fetch(request.target, relative=True)

    async def fetch_holdings(self, identity: str | None, collection: str | None) -> str:
        return await self.fetch(f"holdings:{identity}:{collection}", relative=True)

    def processor_routes(self) -> list[str]:
        return ["/model"]  # not I/O: must be forwarded unbounded

    def default_route(self) -> str:
        return "/model"  # a declaration, not I/O: forwarded so fan-out reduce resolves


@pytest.mark.asyncio
async def test_the_layer_binds_and_releases_one_permit_per_fetch() -> None:
    gate = FairShareGate(2)
    inner = _CapabilityInner()
    layer = FairShareIOLayer(inner, gate, "run-a")

    tasks = [
        asyncio.get_running_loop().create_task(layer.fetch(f"t{i}", relative=True))
        for i in range(3)
    ]
    await _settle()
    snapshot = gate.snapshot()
    assert _share(snapshot, "run-a") == RunShare(run="run-a", in_flight=2, waiting=1)

    inner.proceed.set()
    results = await asyncio.gather(*tasks)
    assert results == ["got:t0", "got:t1", "got:t2"]
    assert gate.snapshot().runs == ()  # every permit returned


@pytest.mark.asyncio
async def test_the_layer_releases_the_permit_when_the_fetch_fails() -> None:
    gate = FairShareGate(1)
    inner = _CapabilityInner()
    inner.fail = True
    layer = FairShareIOLayer(inner, gate, "run-a")

    with pytest.raises(RuntimeError, match="inner exploded"):
        await layer.fetch("boom", relative=True)

    assert gate.snapshot().in_flight == 0


@pytest.mark.asyncio
async def test_the_layer_releases_the_permit_when_the_fetch_is_cancelled() -> None:
    gate = FairShareGate(1)
    inner = _CapabilityInner()
    layer = FairShareIOLayer(inner, gate, "run-a")

    task = asyncio.get_running_loop().create_task(layer.fetch("stuck", relative=True))
    await _settle()
    assert gate.snapshot().in_flight == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _settle()
    assert gate.snapshot().in_flight == 0


def test_the_layer_forwards_exactly_the_inner_capability_ports() -> None:
    full = FairShareIOLayer(_CapabilityInner(), FairShareGate(1), "run-a")
    assert hasattr(full, "fetch_ex")
    assert hasattr(full, "fetch_holdings")
    assert full.processor_routes() == ["/model"]
    assert full.default_route() == "/model"

    class _Bare:
        async def fetch(self, target: str, *, relative: bool) -> str:
            return target

    bare = FairShareIOLayer(_Bare(), FairShareGate(1), "run-a")  # type: ignore[arg-type]
    assert not hasattr(bare, "fetch_ex")
    assert not hasattr(bare, "fetch_holdings")
    assert not hasattr(bare, "processor_routes")


@pytest.mark.asyncio
async def test_the_gate_admits_capacity_fetches_across_two_runs_near_evenly() -> None:
    """The end-state fairness bound: contending runs end within one permit of each other.

    Two runs each demand more than the whole capacity; as permits cycle, the fewest-
    in-flight rule keeps their held counts from diverging while both still have demand.
    """
    gate = FairShareGate(8)
    a = _Claims(gate, "run-a")
    b = _Claims(gate, "run-b")
    a.claim(8)
    b.claim(8)
    await _settle()

    snapshot = gate.snapshot()
    assert snapshot.in_flight == 8
    held_a = _share(snapshot, "run-a").in_flight
    held_b = _share(snapshot, "run-b").in_flight
    # B arrived after A filled the gate, so A holds everything — until A cycles.
    assert held_a == 8 and held_b == 0

    # A's fetches complete and immediately re-demand (a run's real refilling behavior):
    # half of A's claims finish, then B is still queued and A re-claims.
    a._hold.set()  # noqa: SLF001 - test drives the release explicitly
    await asyncio.sleep(0)
    a._hold.clear()  # noqa: SLF001
    a.claim(4)
    await _settle()

    snapshot = gate.snapshot()
    held_a = _share(snapshot, "run-a").in_flight
    held_b = _share(snapshot, "run-b").in_flight
    assert held_b > 0  # B was served the moment capacity freed
    assert held_a <= held_b + 1  # and A cannot out-hold B while B still has demand

    await b.finish()  # B yields FIRST: A's re-claims are queued behind B's held permits
    await a.finish()
    assert gate.snapshot().runs == ()
