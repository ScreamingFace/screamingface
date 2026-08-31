"""OME-1026 remediation F5/F6 — live-task capacity and background error retention.

FEATURE: bounded background discovery. The manager's capacity is what keeps a
remotely-triggerable refresh from becoming an unbounded allocation, and its error
channel is what keeps a programming bug in a background refresh from vanishing.

STORY: as an operator I can rotate a credential as fast as I like without the
process accumulating live upstream work, and as an engineer a bug in a background
refresh cannot pass my test suite silently.

INVARIANT (F5): capacity counts EVERY live task. A superseded task is cancelled but
keeps running until it observes the cancellation — and provider code is free to
absorb a cancellation. Counting only joinable tasks let repeated rotation start an
unbounded number of live tasks while the gauge read zero.

INVARIANT (F6): an unexpected exception in a background refresh is RETAINED until
something observes it. Logging alone means a test that reached the real internet —
the no-egress tripwire raises ``AssertionError`` — could still pass green.
"""

from __future__ import annotations

import asyncio

import pytest

from aigateway.core.background_error_sink import (
    reset_unexpected,
    take_unexpected,
)
from aigateway.core.background_refresh import (
    BackgroundRefreshManager,
)
from aigateway.core.parameter_discovery import DiscoveryError


class _Resistant:
    """Provider work that ABSORBS cancellation, as real cleanup code may.

    # WHY the suite needs this shape: a cooperative task becomes ``done()`` on the
    # very next loop pass, so a capacity bug is invisible with cooperative doubles.
    # Absorbing the cancel is what holds the task live long enough to be counted.
    """

    def __init__(self, absorb: int = 1) -> None:
        self.absorb = absorb
        self.cancels = 0
        self.release = asyncio.Event()
        self.entered = asyncio.Event()

    async def run(self) -> str:
        self.entered.set()
        while True:
            try:
                await self.release.wait()
                return "finished"
            except asyncio.CancelledError:
                self.cancels += 1
                if self.cancels > self.absorb:
                    raise


@pytest.fixture(autouse=True)
def _drain_sink():
    """This file OWNS the sink: it deliberately overflows it, so it clears both channels.

    # WHY ``reset_unexpected`` and not ``take_unexpected`` (OME-1026 F6):
    # ``take_unexpected`` drains the retained objects and deliberately LEAVES the
    # dropped count, because erasing that count is what let an overflow pass green.
    # A file whose subject is the overflow must therefore say so explicitly.
    """
    reset_unexpected()
    yield
    reset_unexpected()


# ── F5: capacity counts superseded work ───────────────────────────────────────


@pytest.mark.asyncio
async def test_repeated_supersede_never_exceeds_the_live_task_bound() -> None:
    """The reported schedule: rotate a credential repeatedly against a stuck provider."""
    mgr = BackgroundRefreshManager[str](max_inflight=1)
    workers: list[_Resistant] = []

    def _start() -> asyncio.Task | None:
        worker = _Resistant(absorb=99)
        workers.append(worker)
        return mgr.start_or_join("one-identity", worker.run)

    try:
        first = _start()
        assert first is not None
        await workers[0].entered.wait()

        for _ in range(6):
            mgr.cancel("one-identity")
            await asyncio.sleep(0)
            _start()
            # INVARIANT: the bound is on LIVE tasks, so a cancellation-resistant
            # predecessor must block the replacement rather than doubling the work.
            assert mgr.inflight <= 1, f"live tasks exceeded the bound: {mgr.inflight}"

        live = [worker for worker in workers if worker.entered.is_set()]
        assert len(live) == 1, "only the first task should ever have started"
    finally:
        for worker in workers:
            worker.absorb = 0
            worker.release.set()
        await mgr.aclose()


@pytest.mark.asyncio
async def test_the_gauge_does_not_read_zero_while_superseded_work_is_alive() -> None:
    """Observability: a cancelled-but-unwinding task is still occupying the process."""
    mgr = BackgroundRefreshManager[str](max_inflight=2)
    worker = _Resistant(absorb=99)
    try:
        assert mgr.start_or_join("k", worker.run) is not None
        await worker.entered.wait()
        assert mgr.inflight == 1

        mgr.cancel("k")
        await asyncio.sleep(0)

        assert mgr.inflight == 1, "superseded but still running — the gauge must say so"
    finally:
        worker.absorb = 0
        worker.release.set()
        await mgr.aclose()


@pytest.mark.asyncio
async def test_shutdown_is_bounded_even_against_cancellation_resistant_work() -> None:
    """A provider that absorbs cancellation must not hang process shutdown forever.

    # OME-1026 adversarial B4 (owner-decided re-pin, and this file was introduced by
    # this same unit): this case used to assert ``inflight == 0`` after ``aclose`` —
    # "shutdown stops accounting for work it gave up on". An independent probe showed
    # what that costs: the task is still RUNNING while the manager reports no live work
    # and has dropped its strong reference, so the gauge lies and asyncio may collect
    # the task mid-flight. Shutdown stays BOUNDED — that half is unchanged and still
    # asserted — but it no longer pretends the work died.
    """
    mgr = BackgroundRefreshManager[str](max_inflight=2, shutdown_timeout_s=0.05)
    worker = _Resistant(absorb=99)
    task = mgr.start_or_join("k", worker.run)
    try:
        assert task is not None
        await worker.entered.wait()

        await mgr.aclose()  # must RETURN, not hang

        assert mgr.inflight == 1, "a task that outlived shutdown is still live work"
        assert task in mgr.pending_tasks(), "and stays strongly referenced until it exits"
    finally:
        # Released in ``finally`` on purpose: a resistant task left unreleased hangs the
        # loop's own teardown, which turns one failed assertion into a stuck session.
        worker.absorb = 0
        worker.release.set()
        if task is not None:
            await asyncio.wait({task}, timeout=1.0)
        # One more pass: the done-callback that frees the slot is scheduled with
        # ``call_soon``, so the task being finished is not yet the manager knowing it.
        await asyncio.sleep(0)

    assert mgr.inflight == 0, "and it is released the moment it finally exits"
    assert mgr.pending_tasks() == ()


# ── F6: unexpected background errors are retained until observed ───────────────


@pytest.mark.asyncio
async def test_an_unawaited_programming_error_is_retained_for_later_observation() -> None:
    """The no-egress tripwire's shape: nobody awaits the task, so logging is not enough."""
    mgr = BackgroundRefreshManager[str](max_inflight=2)
    try:

        async def _boom() -> str:
            raise AssertionError("test attempted real discovery egress to https://example.invalid")

        assert mgr.start_or_join("k", _boom) is not None
        await mgr.drain()

        retained = take_unexpected()
        assert len(retained) == 1, retained
        assert retained[0].type_name == "AssertionError"
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_a_discovery_failure_is_not_retained_as_a_bug() -> None:
    mgr = BackgroundRefreshManager[str](max_inflight=2)
    try:

        async def _degraded() -> str:
            raise DiscoveryError("bad_status", status=503)

        assert mgr.start_or_join("k", _degraded) is not None
        await mgr.drain()

        assert take_unexpected() == (), "an expected upstream failure is not a bug report"
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_an_error_already_surfaced_to_a_caller_is_not_double_reported() -> None:
    """``mark_observed`` is the explicit observation point the retention waits for.

    # WHY this matters: a refresh whose bug was re-raised to an awaiting HTTP caller
    # has already failed loudly. Retaining it too would make the suite's teardown
    # assertion fire for an error a test deliberately asserted.
    """
    mgr = BackgroundRefreshManager[str](max_inflight=2)
    try:

        async def _boom() -> str:
            raise AssertionError("observed by the caller")

        task = mgr.start_or_join("k", _boom)
        assert task is not None
        await mgr.wait_up_to(task, timeout=1)
        exc = task.exception()
        assert isinstance(exc, AssertionError)

        from aigateway.core.background_error_sink import mark_observed

        mark_observed(exc)

        assert take_unexpected() == ()
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_retention_is_itself_bounded() -> None:
    """The sink must not become the unbounded allocation it exists to reveal."""
    # Capacity above the batch size on purpose: this case is about the SINK's bound,
    # and a capacity refusal would silently reduce the number of errors produced.
    mgr = BackgroundRefreshManager[str](max_inflight=128)
    try:

        async def _boom() -> str:
            raise AssertionError("boom")

        for index in range(80):
            assert mgr.start_or_join(f"k{index}", _boom) is not None
        await mgr.drain()

        retained = take_unexpected()
        assert 0 < len(retained) <= 32, len(retained)
    finally:
        await mgr.aclose()
