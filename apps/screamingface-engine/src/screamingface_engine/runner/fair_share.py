"""Work-conserving fair-share admission for a process's concurrent runs (OME-908).

Local mode runs every admitted run on one event loop, and each run's URL4 expression can
hold many downstream fetches in flight at once. With no cross-run policy those runs race
for the gateway's small per-provider FIFO queue, and one benchmark-sized run — a cold
DRACO grading phase is ~20k judge calls against one provider — starves every other run:
the gateway queue serves whoever arrives first, and the big run always has something
arriving.

This module is the engine-side half of the fix the OME-908 spec recommends for local
mode: ONE shared capacity, admitted per fetch, split near-evenly across the runs that
currently have demand — while a solo run still gets the whole capacity (the scheduler is
work-conserving, not a fixed partition). The deployed mode uses the cheaper static form
of the same policy: a per-run in-flight budget written onto the Job as
``URL4_CLOUD_IO_CONCURRENCY`` and enforced by URL4's own ``BoundedIOLayer`` (see
``runner.main.build_executor`` — the two paths meet there).

Scheduling discipline: on every admission opportunity (a new waiter, or a released
permit) the next grant goes to the waiting run with the FEWEST permits already in
flight, ties broken by earliest arrival. While two runs both have demand, neither can
out-hold the other by more than one permit; a run with no demand imposes no claim, so
capacity flows to whoever wants it. That is max-min fairness with equal weights, and it
is the property the invariant tests pin.

Concurrency-model notes (the discipline this module owes its correctness to):

- The gate is cooperative-event-loop only: every method that touches shared state is
  synchronous (no ``await`` between check and act), so each is an atomic critical
  section on the single-threaded loop — the same invariant ``url4.dag.executor._run``
  documents for its memo table. A waiter is woken by ``Future.set_result``, which
  schedules the resumption; nothing here ever blocks.
- Every permit release — success, error, or cancellation — happens in a ``finally``.
- A waiter cancelled while queued removes itself; a waiter granted in the instant its
  task was cancelled releases the permit it can no longer use, so a permit can never
  leak. Cancellation of a run unwinds its fetches through the same paths, so a finished
  or stopped run leaves no bookkeeping behind.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

from url4.io.layer import (
    FetchRequest,
    FetchResult,
    IOLayer,
    SupportsDefaultRoute,
    SupportsFetchEx,
    SupportsHoldings,
    SupportsProcessorRoutes,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunShare:
    """One run's current claim on the gate, for metrics and the invariant tests."""

    run: str
    in_flight: int
    waiting: int


@dataclass(frozen=True, slots=True)
class GateSnapshot:
    """The gate's whole state at one instant."""

    capacity: int
    in_flight: int
    granted_total: int
    runs: tuple[RunShare, ...]


class FairShareGate:
    """The shared downstream capacity every local run dispatches through.

    Construct one per process (local mode builds it in ``local.create_local_app``), hand
    it to each run's ``FairShareIOLayer``, and the runs fair-share the ``capacity``
    permits. The gate owns no tasks and no I/O — it only decides which waiting fetch may
    proceed — so teardown is cancelling the queued waiters, which their own fetches'
    ``finally`` blocks turn into permit releases.
    """

    def __init__(self, capacity: int) -> None:
        # WHY validated here and not at the call site: a capacity of 0 can never admit
        # anything, and the failure would be every fetch hanging forever — the exact trap
        # url4's `_validate_concurrency` documents for `run(concurrency=0)`.
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError(f"FairShareGate capacity must be an int, got {capacity!r}")
        if capacity < 1:
            raise ValueError(f"FairShareGate capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._in_flight = 0
        self._granted_total = 0
        self._order_counter = 0
        self._arrival: dict[str, int] = {}
        self._active: dict[str, int] = {}
        self._queues: dict[str, deque[asyncio.Future[None]]] = {}
        self._closed = False

    @property
    def capacity(self) -> int:
        return self._capacity

    def snapshot(self) -> GateSnapshot:
        """The gate's current state. Safe to call at any time (synchronous, lock-free)."""
        runs = tuple(
            RunShare(
                run=run,
                in_flight=self._active.get(run, 0),
                waiting=len(self._queues.get(run, ())),
            )
            for run in self._known_runs()
        )
        return GateSnapshot(
            capacity=self._capacity,
            in_flight=self._in_flight,
            granted_total=self._granted_total,
            runs=runs,
        )

    async def acquire(self, run: str) -> None:
        """Claim one permit for ``run``, waiting until the fair share allows it.

        Raises ``RuntimeError`` if the gate is closed (shutdown). Every exit path —
        granted then cancelled, cancelled while queued, or granted — leaves the gate
        exactly as if this call had never been made.
        """
        if self._closed:
            raise RuntimeError("FairShareGate is closed")
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        queue = self._queues.get(run)
        if queue is None:
            queue = deque()
            self._queues[run] = queue
            self._arrival[run] = self._order_counter
            self._order_counter += 1
        queue.append(fut)
        self._pump()
        granted = False
        try:
            await fut
            granted = True
        finally:
            if not granted:
                self._abandon(run, fut)

    def release(self, run: str) -> None:
        """Return one permit held by ``run`` and hand it to the next fair claimant."""
        held = self._active.get(run)
        if held is None or held < 1:
            # A release with no matching grant is a caller bug (double release); it must
            # not corrupt the counts every other invariant rests on.
            _logger.warning("FairShareGate: release without a held permit for run %r", run)
            return
        self._active[run] = held - 1
        self._in_flight -= 1
        self._maybe_forget(run)
        self._pump()

    async def aclose(self) -> None:
        """Shutdown: refuse new claims and wake every queued waiter with an error.

        The permits already in flight drain naturally as their fetches finish — the gate
        holds nothing they need to give back.
        """
        self._closed = True
        for queue in self._queues.values():
            for fut in queue:
                if not fut.done():
                    fut.set_exception(RuntimeError("FairShareGate closed while waiting"))
        self._queues.clear()
        self._arrival.clear()
        self._active.clear()

    # --- internals: every method below is synchronous by design -----------------------------

    def _pump(self) -> None:
        """Grant free capacity to waiting runs, fewest-in-flight first.

        The selection rule IS the fairness mechanism: while run B has a waiter, run A is
        granted only when A holds no more permits than B (modulo the arrival tie-break),
        so neither run can out-hold the other by more than one permit while both have
        demand. A run with no waiter claims nothing, which is what keeps the gate
        work-conserving.
        """
        while self._in_flight < self._capacity and self._queues:
            run = min(self._queues, key=lambda r: (self._active.get(r, 0), self._arrival[r]))
            queue = self._queues[run]
            fut = queue.popleft()
            if not queue:
                del self._queues[run]
            if fut.done():
                # A cancelled waiter whose task has not unwound far enough to remove
                # itself yet; granting it would raise, so skip it here. Its own
                # `acquire` finally does the removal.
                self._maybe_forget(run)
                continue
            self._active[run] = self._active.get(run, 0) + 1
            self._in_flight += 1
            self._granted_total += 1
            fut.set_result(None)

    def _abandon(self, run: str, fut: asyncio.Future[None]) -> None:
        """A waiter left the queue without a grant (its task was cancelled): drop it.

        WHY no grant-return branch exists here: the one window it would guard — a permit
        granted into a future whose task is then cancelled before resuming — cannot occur
        under asyncio semantics. A done future refuses ``cancel()`` (it returns False), so
        ``Task.cancel()`` cannot deliver a cancellation into an already-granted waiter;
        the task instead resumes, ``acquire`` returns, and the caller's ``finally`` releases
        the permit on its own path. A future failed by :meth:`aclose` was never granted a
        permit, and ``_queues`` is already clear by then, so it also needs no accounting.
        """
        queue = self._queues.get(run)
        if queue is not None:
            try:
                queue.remove(fut)
            except ValueError:  # already popped by _pump's done-future skip path
                pass
            if not queue:
                del self._queues[run]
                self._maybe_forget(run)

    def _known_runs(self) -> tuple[str, ...]:
        keys = self._queues.keys() | self._active.keys()
        return tuple(sorted(keys, key=lambda r: self._arrival.get(r, 0)))

    def _maybe_forget(self, run: str) -> None:
        """Drop a run's bookkeeping once it neither waits nor holds anything.

        This is what makes a finished run's share reversion immediate and complete: the
        last release empties its claim on the very same synchronous step, before the
        next admission decision.
        """
        if run in self._queues:
            return
        if self._active.get(run, 0) > 0:
            return
        self._active.pop(run, None)
        self._arrival.pop(run, None)


class FairShareIOLayer:
    """An :class:`~url4.io.layer.IOLayer` that admits each fetch through a shared gate.

    One instance wraps one run's world io; ``run`` is the run's key in the gate (its
    topic). Capability ports are forwarded exactly as ``url4.dag.node.BoundedIOLayer``
    forwards them — conditionally, so a ``runtime_checkable`` isinstance test reports the
    wrapped layer's capabilities and never more. ``processor_routes`` is forwarded
    unbounded for the same reason BoundedIOLayer leaves it unbounded: declaring routes is
    not I/O.

    Pair with ``url4.dag.run(..., concurrency=None)``: the gate replaces URL4's
    per-run ``BoundedIOLayer``, not stacks under it (the OME-908 spec pins this).
    """

    # Conditionally bound in __init__ (annotation only — no class attribute, so
    # hasattr/isinstance stay false when the inner adapter lacks the port).
    fetch_ex: Any
    fetch_holdings: Any
    processor_routes: Any
    default_route: Any

    def __init__(self, inner: IOLayer, gate: FairShareGate, run: str) -> None:
        self._inner = inner
        self._gate = gate
        self._run = run
        if isinstance(inner, SupportsFetchEx):
            self.fetch_ex = self._gated_fetch_ex
        if isinstance(inner, SupportsHoldings):
            self.fetch_holdings = self._gated_fetch_holdings
        if isinstance(inner, SupportsProcessorRoutes):
            self.processor_routes = inner.processor_routes
        # WHY this one and not `BoundedIOLayer`'s set: url4's own wrapper never forwards
        # it because `run()` builds the ExecutionContext BEFORE wrapping, so the ctx has
        # already resolved the default route off the raw io. THIS wrapper binds earlier —
        # the executor hands it to `run()` as the io itself — so unless the declaration
        # rides through, a fan-out reduce finds no processor route and every grouped
        # expression fails at resolution. Like `processor_routes`, it is a pure
        # declaration: not I/O, never bounded, forwarded unconditionally when present.
        if isinstance(inner, SupportsDefaultRoute):
            self.default_route = inner.default_route

    @property
    def run(self) -> str:
        """The gate key this layer dispatches under (the run's topic)."""
        return self._run

    async def fetch(self, target: str, *, relative: bool) -> str:
        await self._gate.acquire(self._run)
        try:
            return await self._inner.fetch(target, relative=relative)
        finally:
            self._gate.release(self._run)

    async def _gated_fetch_ex(self, request: FetchRequest) -> FetchResult:
        await self._gate.acquire(self._run)
        try:
            return await self._inner.fetch_ex(request)  # type: ignore[attr-defined]
        finally:
            self._gate.release(self._run)

    async def _gated_fetch_holdings(self, identity: str | None, collection: str | None) -> str:
        await self._gate.acquire(self._run)
        try:
            return await self._inner.fetch_holdings(identity, collection)  # type: ignore[attr-defined]
        finally:
            self._gate.release(self._run)


__all__ = ["FairShareGate", "FairShareIOLayer", "GateSnapshot", "RunShare"]
