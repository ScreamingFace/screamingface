"""Optional Colab setup failures cannot replace product execution."""

import asyncio
import threading

import pytest
from test_analytics_colab import accepted
from test_analytics_colab import browser as browser

from screamingface._analytics import colab, prompt
from screamingface._analytics.tracking import tracked


@pytest.fixture
def pending_setup(browser, monkeypatch):
    entered, release, finished = (threading.Event() for _ in range(3))
    calls = []
    dispatch = browser._dispatch

    def exchange(command, *args, **kwargs):
        calls.append(command)
        entered.set()
        release.wait(3)
        return accepted()

    def complete(*args):
        try:
            return dispatch(*args)
        finally:
            finished.set()

    monkeypatch.setattr(colab, "exchange", exchange)
    monkeypatch.setattr(browser, "_dispatch", complete)
    prompt.offer()
    assert entered.wait(1)
    try:
        yield browser, release, finished, calls
    finally:
        release.set()
        assert finished.wait(1)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("error", [RuntimeError, AttributeError])
def test_wait_error_preserves_evaluation_and_rejects_late_reply(
    pending_setup, monkeypatch, caplog, asynchronous, error
):
    adapter, release, finished, calls = pending_setup

    def broken():
        raise error("private browser details")

    @tracked("evaluation")
    def evaluate():
        return "product result"

    @tracked("evaluation")
    async def evaluate_async():
        return "product result"

    monkeypatch.setattr(adapter, "wait_for_setup", broken)
    with caplog.at_level("DEBUG", logger=prompt.__name__):
        result = asyncio.run(evaluate_async()) if asynchronous else evaluate()
    assert result == "product result"
    assert not adapter.pending
    assert adapter.read().choice == "unknown"
    release.set()
    assert finished.wait(1)
    assert adapter.read().choice == "unknown"
    assert calls == ["state"]
    assert [r.getMessage() for r in caplog.records if r.name == prompt.__name__] == [
        "Analytics setup skipped"
    ]


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_sync_wait_preserves_interruptions(pending_setup, monkeypatch, error):
    adapter, *_ = pending_setup

    def interrupted():
        raise error()

    monkeypatch.setattr(adapter, "wait_for_setup", interrupted)
    with pytest.raises(error):
        prompt.before_evaluation()


@pytest.mark.asyncio
async def test_async_wait_preserves_cancellation(pending_setup, monkeypatch):
    adapter, *_ = pending_setup

    def cancelled():
        raise asyncio.CancelledError()

    monkeypatch.setattr(adapter, "wait_for_setup", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await prompt.before_evaluation_async()


@pytest.mark.asyncio
async def test_async_wait_executor_failure_invalidates_pending_setup(pending_setup, monkeypatch):
    adapter, release, finished, calls = pending_setup

    async def unavailable(*args):
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(asyncio, "to_thread", unavailable)
    await prompt.before_evaluation_async()
    assert not adapter.pending
    release.set()
    assert finished.wait(1)
    assert adapter.read().choice == "unknown"
    assert calls == ["state"]
