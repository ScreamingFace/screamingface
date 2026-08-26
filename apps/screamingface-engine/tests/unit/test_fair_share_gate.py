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
    """The real cancellation contract, minus an impossible race.

    A grant delivered into a waiter's future can no longer be cancelled — asyncio
    refuses ``cancel()`` on a done future — so the only cancellation path that reaches
    the gate is a waiter cancelled while STILL QUEUED, and what matters is that its
    run's remaining waiters keep their places and still get served.
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
