"""Safe local failure evidence and recovery from malformed browser responses."""

import queue
import threading
import types

import pytest
from test_analytics_colab import accepted
from test_analytics_colab import browser as browser
from test_analytics_colab_recovery import evaluate as evaluate
from test_analytics_colab_recovery import settled

from screamingface import analytics
from screamingface._analytics import colab, prompt
from screamingface._analytics.ports import Consent


@pytest.mark.parametrize(
    "failure,reason",
    [
        (TimeoutError("secret timeout details"), "timeout"),
        (RuntimeError("secret browser details"), "unavailable"),
        ({"unavailable": True}, "unavailable"),
        ({"unavailable": True, "reason": "timeout"}, "timeout"),
        ({"unavailable": True, "reason": "secret details"}, "unavailable"),
        (None, "invalid_response"),
        ([], "invalid_response"),
        ("secret reply", "invalid_response"),
    ],
)
def test_safe_failure_details_clear_after_recovery(browser, monkeypatch, failure, reason):
    def broken(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(colab, "exchange", broken)
    prompt.before_evaluation()
    state = analytics.status()
    assert state["last_error"] == f"setup_{reason}"
    assert state["last_error_stage"] == "state"
    assert state["setup_attempts"] == 1
    assert not state["enabled"] and not state["pending"]
    monkeypatch.setattr(colab, "exchange", lambda *a, **kw: accepted())
    prompt.before_evaluation()
    state = analytics.status()
    assert state["enabled"]
    assert state["setup_attempts"] == 2
    assert state["last_error"] is None
    assert state["last_error_stage"] is None


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"choice": "accepted", "consent_version": "0"},
        {"choice": "accepted", "consent_version": "1"},
        {**accepted(), "persistent_id": "secret malformed identifier"},
        {**accepted(), "id_scope": "installation"},
    ],
)
def test_invalid_id_is_distinguished_from_transport_failure(browser, monkeypatch, reply):
    monkeypatch.setattr(
        colab, "exchange", lambda step, *a, **kw: accepted() if step == "state" else reply
    )
    prompt.before_evaluation()
    state = analytics.status()
    assert not state["enabled"] and not state["pending"]
    assert state["last_error"] == "setup_invalid_response"
    assert state["last_error_stage"] == "id"


def test_repeated_outage_retries_once_per_evaluation(evaluate, browser, monkeypatch):
    calls = []

    def unavailable(step, *args, **kwargs):
        calls.append(step)
        raise TimeoutError()

    monkeypatch.setattr(colab, "exchange", unavailable)
    for attempt in range(1, 4):
        evaluate()
        assert calls == ["state"] * attempt
        assert analytics.status()["setup_attempts"] == attempt
        assert not browser.pending


def test_failed_enrollment_retries_without_repeating_notice(browser, monkeypatch, capsys):
    calls = []

    def exchange(step, *args, **kwargs):
        calls.append(step)
        if step == "state":
            return {"choice": "unknown", "consent_version": "1"}
        if step == "enroll" and calls.count("enroll") == 1:
            raise TimeoutError()
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.before_evaluation()
    assert analytics.status()["last_error_stage"] == "enroll"
    assert calls == ["state", "enroll"]
    prompt.before_evaluation()
    assert analytics.status()["enabled"]
    assert calls == ["state", "enroll", "state", "enroll", "id"]
    assert capsys.readouterr().out.splitlines() == [prompt.NOTICE]


def test_queue_overflow_is_visible_without_revoking_consent(browser, monkeypatch):
    browser._state = Consent("accepted")
    # WHY: a saturated queue is local backpressure, not evidence of browser opt-out.
    browser._queue = queue.Queue(maxsize=1)
    monkeypatch.setattr(browser, "_worker", types.SimpleNamespace(is_alive=lambda: True))
    browser.emit({"event_id": "first"})
    browser.emit({"event_id": "dropped"})
    state = analytics.status()
    assert state["enabled"]
    assert state["last_error"] == "delivery_queue_full"
    assert state["last_error_stage"] == "queue"
    assert browser._queue.qsize() == 1


@pytest.mark.parametrize("command", ["setup", "events"])
def test_worker_start_failure_is_visible_and_recoverable(browser, monkeypatch, command):
    def broken(*args, **kwargs):
        raise RuntimeError("secret OS details")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", broken)
        if command == "setup":
            prompt.before_evaluation()
        else:
            browser._state = Consent("accepted")
            browser.emit({"event_id": "dropped"})
    state = analytics.status()
    assert not state["enabled"] and not state["pending"]
    assert state["last_error"] == (
        "setup_worker_unavailable" if command == "setup" else "delivery_worker_unavailable"
    )
    monkeypatch.setattr(colab, "exchange", lambda *a, **kw: accepted())
    prompt.before_evaluation()
    assert analytics.status()["enabled"]


def test_failed_decline_stays_locally_declined(browser, monkeypatch):
    monkeypatch.setattr(colab, "exchange", lambda *a, **kw: {"unavailable": True})
    analytics.disable()
    settled(browser, lambda: not browser.pending)
    state = analytics.status()
    assert state["choice"] == "declined" and not state["enabled"]
    assert state["last_error"] == "decline_unavailable"
    assert state["last_error_stage"] == "decline"


@pytest.mark.parametrize("reply", [{}, {"status": "rejected"}, None, {"choice": "accepted"}])
def test_bad_delivery_acknowledgement_cannot_claim_success(browser, monkeypatch, reply):
    monkeypatch.setattr(
        colab, "exchange", lambda step, *a, **kw: reply if step == "events" else accepted()
    )
    prompt.before_evaluation()
    from screamingface._analytics.wiring import coordinator

    coordinator().begin("evaluation", "recipe", "sync", "colab", "hosted")
    settled(browser, lambda: not analytics.status()["enabled"])
    assert analytics.status()["last_error"] == "delivery_invalid_response"
    assert analytics.status()["last_error_stage"] == "events"


def test_reply_after_control_deadline_does_not_enable(browser, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(colab, "time", types.SimpleNamespace(monotonic=lambda: now[0]))

    def exchange(step, *args, **kwargs):
        now[0] += 2.6
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.before_evaluation()
    assert not analytics.status()["enabled"]
    assert analytics.status()["last_error"] == "setup_timeout"
    assert analytics.status()["last_error_stage"] == "id"


def test_skipped_stale_event_does_not_revoke_current_consent(browser, monkeypatch):
    from screamingface._analytics.wiring import coordinator

    sent = threading.Event()

    def exchange(step, *a, **kw):
        if step == "events":
            sent.set()
            return {"status": "upstream_accepted", "count": 1}
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.before_evaluation()
    core = coordinator()
    operation = core.begin("evaluation", "recipe", "sync", "colab", "hosted")
    assert operation is not None
    # Finish the real dispatch before invalidating only the coordinator session.
    settled(browser, sent.is_set)
    core.clear()
    before = browser.read()
    assert before.choice == "accepted"
    state = browser._dispatch(browser._generation, "events", operation.fields)
    assert state is None, "Skipping a stale event must not erase confirmed browser consent"
    assert browser.read() == before
    assert analytics.status()["last_error"] is None


def test_oversized_event_drop_is_visible_without_disabling_tracking(browser, monkeypatch):
    browser._state = Consent("accepted")
    browser.emit({"event_id": "x" * 4097})
    assert browser._queue.empty()
    assert analytics.status()["enabled"]
    assert analytics.status()["last_error"] == "delivery_event_too_large"


def test_invalid_decline_ack_cannot_claim_persistence(browser, monkeypatch):
    monkeypatch.setattr(colab, "exchange", lambda *a, **kw: accepted())
    analytics.disable()
    settled(browser, lambda: not browser.pending)
    state = analytics.status()
    assert state["choice"] == "declined"
    assert state["last_error"] == "decline_invalid_response"
    assert state["last_error_stage"] == "decline"


def test_slow_healthy_setup_and_delivery_use_five_second_budget(browser, monkeypatch):
    from screamingface._analytics.wiring import coordinator

    now = [0.0]
    calls = []
    monkeypatch.setattr(colab, "time", types.SimpleNamespace(monotonic=lambda: now[0]))

    def exchange(step, *args, timeout_sec, **kwargs):
        calls.append((step, timeout_sec))
        now[0] += 3.0 if step == "events" else 1.5
        return {"status": "upstream_accepted", "count": 1} if step == "events" else accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.before_evaluation()
    assert analytics.status()["enabled"]
    assert calls == [("state", 5.0), ("id", 3.5)]
    coordinator().begin("evaluation", "recipe", "sync", "colab", "hosted")
    settled(browser, lambda: len(calls) == 3)
    assert calls[-1] == ("events", 5.0)
    assert analytics.status()["enabled"]
    assert analytics.status()["last_error"] is None
