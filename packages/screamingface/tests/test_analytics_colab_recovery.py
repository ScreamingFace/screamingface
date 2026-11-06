"""Recovery after the Colab failures observed in OME-1768."""

import asyncio
import socket
import threading
import time
from typing import Any, cast

import pytest
from test_analytics_colab import accepted
from test_analytics_colab import browser as browser

import screamingface as sf
from screamingface._analytics import colab


class BrowserReplies:
    """Fault injection at the browser boundary, leaving SDK state/workers intact."""

    def __init__(self):
        self.saved = accepted()
        self.calls = []
        self.delivered = []
        self.fail_command = None
        self.fail_event = None
        self.failure = "unavailable"
        self.failed = threading.Event()
        self.failure_processed = False
        self.worker_idle = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()
        self.stall = False

    def exchange(self, command, event: dict | None = None, **kwargs):
        self.calls.append(command)
        if self.stall and command == "state":
            self.entered.set()
            self.release.wait(10)
            self.returned.set()
        elif command == self.fail_command and (
            self.fail_event is None or (event is not None and event["event"] == self.fail_event)
        ):
            self.fail_command = None
            self.failed.set()
            if self.failure == "exception":
                raise TimeoutError("Simulated browser exchange timeout")
            return {"choice": "unknown", "unavailable": True}
        elif command == "events":
            assert event is not None
            self.delivered.append(event.copy())
            return {"status": "upstream_accepted", "count": 1}
        return self.saved.copy()


@pytest.fixture
def replies(browser, monkeypatch):
    selected = BrowserReplies()
    connections = []
    notify = browser._changed.notify_all

    def notified():
        # WHY: observe completion after the real worker applies the response, without
        # requiring it to discard previously accepted consent as today's code does.
        if threading.current_thread().name == "sf-colab-analytics":
            selected.worker_idle = browser._queue.empty()
            if selected.failed.is_set():
                selected.failure_processed = True
        notify()

    def forbidden_connect(*args, **kwargs):
        connections.append(True)
        raise AssertionError("Recovery tests must never use real network connections")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    monkeypatch.setattr(colab, "exchange", selected.exchange)
    monkeypatch.setattr(browser._changed, "notify_all", notified)
    yield selected
    selected.release.set()
    assert connections == []


@pytest.fixture(params=["sync", "async"])
def evaluate(request):
    # WHY: invalid public input reaches analytics but cannot schedule a paid model call.
    async def asynchronous():
        async with sf.AsyncClient() as client:
            with pytest.raises(TypeError):
                await client.evaluate(cast(Any, []))

    def synchronous():
        with sf.Client() as client:
            with pytest.raises(TypeError):
                client.evaluate(cast(Any, []))

    return synchronous if request.param == "sync" else lambda: asyncio.run(asynchronous())


def settled(browser, predicate):
    with browser._changed:
        assert browser._changed.wait_for(predicate, timeout=3), "Browser worker did not settle"


def assert_pair(events):
    assert [event["event"] for event in events] == ["evaluation_started", "evaluation_finished"]
    assert events[0]["operation_id"] == events[1]["operation_id"]
    assert events[0]["event_id"] != events[1]["event_id"]
    assert events[1]["outcome"] == "failed"
    assert events[0]["origin"] == events[1]["origin"] == "colab"


def recover_and_check_pair(evaluate, browser, replies):
    previous = list(replies.delivered)
    evaluate()
    settled(browser, lambda: not browser.pending)
    assert sf.analytics.status()["enabled"], "Healthy browser was not recovered automatically"
    settled(browser, lambda: len(replies.delivered) >= len(previous) + 2)
    # INVARIANT: recovery tracks the new operation, never replays a missed old operation.
    assert replies.delivered[: len(previous)] == previous
    assert_pair(replies.delivered[len(previous) :])
    previous_operations = {event["operation_id"] for event in previous}
    assert replies.delivered[-1]["operation_id"] not in previous_operations


@pytest.mark.parametrize("command", ["state", "id"])
@pytest.mark.parametrize("failure", ["exception", "unavailable"])
def test_later_evaluation_recovers_after_setup_failure(
    evaluate, browser, replies, command, failure
):
    replies.fail_command, replies.failure = command, failure
    evaluate()
    settled(browser, lambda: not browser.pending)
    assert replies.failed.is_set()
    assert not sf.analytics.status()["enabled"]
    assert replies.delivered == []
    recover_and_check_pair(evaluate, browser, replies)


def test_later_evaluation_recovers_after_setup_deadline(evaluate, browser, replies):
    replies.stall = True
    started = time.monotonic()
    evaluate()
    elapsed = time.monotonic() - started
    assert replies.entered.is_set()
    assert 4.5 <= elapsed < 5.75
    assert sf.analytics.status()["choice"] == "unknown"
    assert not browser.pending
    replies.release.set()
    assert replies.returned.wait(1)
    replies.stall = False
    # INVARIANT: the expired reply cannot enable this session; a fresh check is needed.
    assert not sf.analytics.status()["enabled"]
    recover_and_check_pair(evaluate, browser, replies)


@pytest.mark.parametrize("event", ["evaluation_started", "evaluation_finished"])
@pytest.mark.parametrize("failure", ["exception", "unavailable"])
def test_later_evaluation_recovers_after_delivery_failure(
    evaluate, browser, replies, event, failure
):
    recover_and_check_pair(evaluate, browser, replies)
    replies.fail_command, replies.fail_event, replies.failure = "events", event, failure
    evaluate()
    settled(browser, lambda: replies.failure_processed and replies.worker_idle)
    recover_and_check_pair(evaluate, browser, replies)


def test_healthy_repeated_evaluations_keep_delivering(evaluate, browser, replies):
    for _ in range(3):
        recover_and_check_pair(evaluate, browser, replies)
    assert len(replies.delivered) == 6
    assert len({event["operation_id"] for event in replies.delivered}) == 3


@pytest.mark.parametrize("opt_out", ["saved_decline", "do_not_track", "process_disable"])
@pytest.mark.parametrize("stage", ["setup", "delivery"])
def test_recovery_must_respect_opt_out(evaluate, browser, replies, monkeypatch, opt_out, stage):
    fail_before_opt_out(evaluate, browser, replies, stage)
    previous = list(replies.delivered)
    if opt_out == "saved_decline":
        replies.saved = {"choice": "declined", "consent_version": "1"}
    elif opt_out == "do_not_track":
        monkeypatch.setenv("DO_NOT_TRACK", "1")
    else:
        sf.analytics.disable(process_only=True)
    before = len(replies.calls)
    for _ in range(3):
        evaluate()
    settled(browser, lambda: not browser.pending)
    assert not sf.analytics.status()["enabled"]
    assert replies.delivered == previous
    assert "enroll" not in replies.calls[before:]
    assert "accept" not in replies.calls[before:]
    assert "id" not in replies.calls[before:]
    if opt_out != "saved_decline":
        assert replies.calls[before:] == []


def fail_before_opt_out(evaluate, browser, replies, stage):
    if stage == "delivery":
        recover_and_check_pair(evaluate, browser, replies)
    replies.fail_command = "state" if stage == "setup" else "events"
    evaluate()
    settled(browser, lambda: replies.failure_processed and replies.worker_idle)
    assert replies.failed.is_set()
