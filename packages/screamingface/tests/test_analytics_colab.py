"""Browser adapter consent and race contracts, without a notebook dependency."""

import sys
import threading
import time
import types
from uuid import uuid4

import pytest

from screamingface import analytics
from screamingface._analytics import colab, prompt, wiring
from screamingface._analytics.ports import Consent


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.005)


@pytest.fixture
def browser(monkeypatch, tmp_path):
    adapter = colab.ColabBridge()
    monkeypatch.setitem(sys.modules, "google.colab", types.ModuleType("google.colab"))
    monkeypatch.setattr(colab, "_instance", adapter)
    monkeypatch.setattr(analytics, "_process_disabled", False)
    monkeypatch.setattr(analytics, "_session_only", False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv("SCREAMINGFACE_ANALYTICS_CONFIG", str(tmp_path / "never-created.json"))
    monkeypatch.setattr(wiring, "_coordinator", None)
    monkeypatch.setattr(prompt, "_shown", False)
    yield adapter
    adapter.stop(persist=False)


def accepted(identifier=None):
    return {
        "choice": "accepted",
        "consent_version": "1",
        "id_scope": "browser",
        "persistent_id": identifier or str(uuid4()),
    }


def test_initialization_is_nonblocking_and_read_only_until_accepted(browser, monkeypatch):
    release, entered = threading.Event(), threading.Event()
    commands = []

    def exchange(command, event):
        commands.append(command)
        entered.set()
        assert release.wait(2)
        return {"choice": "unknown", "consent_version": "1"}

    monkeypatch.setattr(colab, "exchange", exchange)
    prompt.offer()
    assert entered.wait(1)
    assert analytics.status()["enabled"] is False
    core = wiring.coordinator()
    assert core.begin("evaluation", "recipe", "sync", "colab", "byok") is None
    prompt.offer()
    assert commands == ["state"]
    release.set()
    wait_until(lambda: not browser.pending)
    assert browser.read() == Consent()


def test_accept_delivery_and_persistent_decline(browser, monkeypatch, tmp_path):
    state = accepted()
    requests = []

    def exchange(command, event):
        requests.append((command, event))
        if command == "events":
            return {"status": "upstream_accepted"}
        if command == "decline":
            return {"choice": "declined", "consent_version": "1"}
        return state

    monkeypatch.setattr(colab, "exchange", exchange)
    analytics.enable()
    wait_until(lambda: not browser.pending)
    assert analytics.status()["scope"] == "browser"
    assert not (tmp_path / "never-created.json").exists()
    core = wiring.coordinator()
    operation = core.begin("evaluation", "recipe", "sync", "colab", "byok")
    assert operation is not None
    core.finish(operation, "succeeded")
    wait_until(lambda: len([x for x in requests if x[0] == "events"]) == 2)
    events = [e for command, e in requests if command == "events"]
    assert events[0]["id_scope"] == "browser"
    assert events[0]["persistent_id"] == state["persistent_id"]
    assert events[1]["outcome"] == "succeeded"
    analytics.disable()
    assert not analytics.status()["enabled"]
    wait_until(lambda: not browser.pending)
    assert requests[-1][0] == "decline"
    core.finish(operation, "succeeded")
    assert len([x for x in requests if x[0] == "events"]) == 2


def test_late_accept_cannot_reenable_after_disable(browser, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def exchange(command, event):
        entered.set()
        assert release.wait(2)
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    analytics.enable()
    assert entered.wait(1)
    analytics.disable(process_only=True)
    release.set()
    time.sleep(0.03)
    assert not analytics.status()["enabled"]
    assert browser.read().choice == "declined"


def test_dnt_prevents_even_bridge_controls(browser, monkeypatch):
    calls = []
    monkeypatch.setattr(colab, "exchange", lambda *args: calls.append(args))
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    prompt.offer()
    analytics.enable()
    analytics.disable()
    wait_until(lambda: not browser.pending)
    assert calls == []


def test_reset_changes_id_and_session_without_joining(browser, monkeypatch):
    identifiers = [str(uuid4()), str(uuid4())]
    monkeypatch.setattr(
        colab,
        "exchange",
        lambda command, event: accepted(identifiers[1 if command == "reset" else 0]),
    )
    analytics.enable()
    wait_until(lambda: not browser.pending)
    core = wiring.coordinator()
    first = core.begin("evaluation", "recipe", "sync", "colab", "byok")
    analytics.reset_identifier()
    wait_until(lambda: not browser.pending)
    second = core.begin("evaluation", "recipe", "sync", "colab", "byok")
    assert first is not None and second is not None
    assert first.fields["persistent_id"] != second.fields["persistent_id"]
    assert first.fields["session_id"] != second.fields["session_id"]


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"choice": "accepted"},
        {"choice": "accepted", "consent_version": "old"},
        {
            "choice": "accepted",
            "consent_version": "1",
            "id_scope": "browser",
            "persistent_id": "bad",
        },
    ],
)
def test_bad_browser_response_fails_closed(browser, monkeypatch, reply):
    monkeypatch.setattr(colab, "exchange", lambda *args: reply)
    analytics.enable()
    wait_until(lambda: not browser.pending)
    assert not analytics.status()["enabled"]


def test_browser_unavailable_never_falls_back_to_runtime_http(browser, monkeypatch):
    def unavailable(*args):
        raise TimeoutError()

    monkeypatch.setattr(colab, "exchange", unavailable)
    analytics.enable()
    wait_until(lambda: not browser.pending)
    assert not analytics.status()["enabled"]
    assert wiring.coordinator().sink is browser


def test_no_session_only_bypass_of_browser_consent(browser):
    with pytest.raises(ValueError, match="browser consent"):
        analytics.enable(persist=False)


def test_rejected_browser_delivery_disables_future_operations(browser, monkeypatch):
    replies = []

    def exchange(command, event):
        replies.append(command)
        return {"unavailable": True} if command == "events" else accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    analytics.enable()
    wait_until(lambda: not browser.pending)
    core = wiring.coordinator()
    core.begin("evaluation", "recipe", "sync", "colab", "byok")
    wait_until(lambda: browser.read().choice == "unknown")
    assert core.begin("evaluation", "recipe", "sync", "colab", "byok") is None
    assert replies.count("events") == 1


def test_exchange_uses_colab_timeout_and_serialized_payload(browser, monkeypatch):
    calls = []
    output = types.SimpleNamespace(
        eval_js=lambda script, timeout_sec: (
            calls.append((script, timeout_sec)) or {"choice": "unknown"}
        )
    )
    monkeypatch.setattr(sys.modules["google.colab"], "output", output, raising=False)
    assert colab.exchange("state") == {"choice": "unknown"}
    assert calls[0][1] == 2
    assert 'const command = "state", batch = null' in calls[0][0]
    assert "parent_origin=" in calls[0][0]
    assert "/v1/events" not in calls[0][0]
