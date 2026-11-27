"""Interrupts during the post-result analytics wait, and bridge bookkeeping it relies on.

FEATURE: Colab analytics status stays accurate (OME-1974).
WHY: in Colab a tracked call waits up to BRIDGE_TIMEOUT after the product call has finished,
so its analytics upload is acknowledged before the cell ends. Review of PR #1952 asked what an
interrupt during that wait does to a finished, paid-for result. Owner decision (2026-11-26):
- sync: Ctrl-C only ends the optional wait; the result or the real error still reaches the user;
- async: CancelledError propagates, because swallowing it breaks `asyncio.timeout()` and
  `TaskGroup`; the real error stays reachable as the CancelledError's `__context__`.
"""

import asyncio
import threading
import time
import types

import pytest
from test_analytics_colab import browser  # noqa: F401  (fixture, requested by name)
from test_analytics_colab_in_cell import (
    _Owner,
    cell,  # noqa: F401  (fixture, requested by name)
)

from screamingface._analytics import colab, prompt, tracking


@pytest.fixture
def colab_cell(request):
    # WHY by name: a test parameter called `cell` would shadow the import above (ruff F811).
    return request.getfixturevalue("cell")


class DomainError(Exception):
    pass


def interrupt_the_wait(monkeypatch) -> None:
    # WHY: Ctrl-C in a notebook raises KeyboardInterrupt in the main thread, which is the
    # thread blocked in `bridge().flush()` during the sync post-result wait.
    def interrupted(timeout: float = colab.BRIDGE_TIMEOUT) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(colab.bridge(), "flush", interrupted)


# --- sync: Ctrl-C during the wait never replaces the product outcome -----------------------


@pytest.mark.usefixtures("browser")
def test_ctrl_c_during_the_wait_still_returns_the_finished_result(colab_cell, monkeypatch):
    prompt.offer_and_settle()
    report = types.SimpleNamespace(ok=True)

    @tracking.tracked("evaluation")
    def finished(owner, candidates):
        return report

    interrupt_the_wait(monkeypatch)
    # INVARIANT: optional analytics never discards a finished evaluation.
    assert finished(_Owner(), "url4://candidate") is report


@pytest.mark.usefixtures("browser")
def test_ctrl_c_during_the_wait_still_raises_the_real_error(colab_cell, monkeypatch):
    prompt.offer_and_settle()

    @tracking.tracked("evaluation")
    def failing(owner, candidates):
        raise DomainError("the real failure")

    interrupt_the_wait(monkeypatch)
    # INVARIANT: optional analytics never replaces the product's own exception.
    with pytest.raises(DomainError):
        failing(_Owner(), "url4://candidate")


# --- async: cancellation during the wait propagates (documented, accepted) -----------------


async def cancel_during_the_wait(call) -> BaseException:
    task = asyncio.ensure_future(call)
    await asyncio.sleep(0.3)  # the product call has returned; the wait is in progress
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as raised:
        await task
    return raised.value


@pytest.mark.usefixtures("browser")
def test_async_cancel_during_the_wait_propagates(colab_cell):
    prompt.offer_and_settle()
    colab_cell.events_delay = 1.5

    @tracking.tracked("evaluation")
    async def finished(owner, candidates):
        return types.SimpleNamespace(ok=True)

    asyncio.run(cancel_during_the_wait(finished(_Owner(), "url4://candidate")))


@pytest.mark.usefixtures("browser")
def test_async_cancel_during_the_wait_keeps_the_real_error_as_context(colab_cell):
    prompt.offer_and_settle()
    colab_cell.events_delay = 1.5

    @tracking.tracked("evaluation")
    async def failing(owner, candidates):
        raise DomainError("the real failure")

    cancelled = asyncio.run(cancel_during_the_wait(failing(_Owner(), "url4://candidate")))
    assert isinstance(cancelled.__context__, DomainError)


# --- review low items: sync success delivery, and clear() releasing flush() ----------------


@pytest.mark.usefixtures("browser")
def test_sync_success_delivers_the_finished_event_before_returning(colab_cell):
    prompt.offer_and_settle()
    colab_cell.events_delay = 0.3

    @tracking.tracked("evaluation")
    def finished(owner, candidates):
        return types.SimpleNamespace(ok=True)

    finished(_Owner(), "url4://candidate")
    colab_cell.running.clear()
    assert colab_cell.delivered[-2:] == ["evaluation_started", "evaluation_finished"]


@pytest.mark.usefixtures("browser")
def test_clear_releases_flush_for_the_events_it_drops(colab_cell, monkeypatch):
    prompt.offer_and_settle()
    in_flight, release = threading.Event(), threading.Event()
    answer = colab_cell.exchange

    def gated(command, event=None, **kwargs):
        if command == "events":
            in_flight.set()
            release.wait(timeout=colab.BRIDGE_TIMEOUT)
        return answer(command, event, **kwargs)

    monkeypatch.setattr(colab, "exchange", gated)
    colab_cell.delivered.clear()
    # WHY real operations: the bridge only sends events whose session and installation IDs
    # match the coordinator, so hand-built events would never reach the worker.
    args = (_Owner(), "url4://candidate")
    assert tracking._begin("evaluation", "sync", args, {}) is not None
    assert in_flight.wait(timeout=2.0)  # the worker holds the first event
    assert tracking._begin("evaluation", "sync", args, {}) is not None  # stays queued
    colab.bridge().clear()
    release.set()

    start = time.monotonic()
    colab.bridge().flush()
    # INVARIANT: a dropped event is no longer outstanding, so flush() ends with the in-flight
    # one instead of waiting the full BRIDGE_TIMEOUT for an event that will never be sent.
    assert time.monotonic() - start < 2.0
    assert colab_cell.delivered == ["evaluation_started"]
