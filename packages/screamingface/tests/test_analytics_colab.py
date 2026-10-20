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

    def exchange(command, event, **kwargs):
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

    def exchange(command, event, **kwargs):
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

    def exchange(command, event, **kwargs):
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
    monkeypatch.setattr(colab, "exchange", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    prompt.offer()
    analytics.enable()
    analytics.disable()
    wait_until(lambda: not browser.pending)
    assert calls == []


def test_reset_changes_id_and_session_without_joining(browser, monkeypatch):
    identifiers = [str(uuid4()), str(uuid4())]
    current = 0
    commands = []

    def exchange(command, event, **kwargs):
        nonlocal current
        commands.append(command)
        if command == "decline":
            current = 1
            return {"choice": "declined", "consent_version": "1"}
        return accepted(identifiers[current])

    monkeypatch.setattr(colab, "exchange", exchange)
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
    assert commands == ["accept", "id", "decline", "accept", "id"]


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
    monkeypatch.setattr(colab, "exchange", lambda *args, **kwargs: reply)
    analytics.enable()
    wait_until(lambda: not browser.pending)
    assert not analytics.status()["enabled"]


def test_browser_unavailable_never_falls_back_to_runtime_http(browser, monkeypatch):
    def unavailable(*args, **kwargs):
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

    def exchange(command, event, **kwargs):
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


@pytest.mark.parametrize("command", ["state", "accept", "reset"])
@pytest.mark.parametrize("stop", ["disable", "dnt"])
def test_stop_during_consent_never_starts_follow_on_id(browser, monkeypatch, command, stop):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def exchange(step, event, **kwargs):
        calls.append(step)
        if step == "decline":
            return {"choice": "declined", "consent_version": "1"}
        entered.set()
        assert release.wait(2)
        finished.set()
        return {"choice": "accepted", "consent_version": "1"}

    monkeypatch.setattr(colab, "exchange", exchange)
    browser.control(command)
    assert entered.wait(1)
    if stop == "disable":
        analytics.disable(process_only=True)
    else:
        monkeypatch.setenv("DO_NOT_TRACK", "1")
    release.set()
    assert finished.wait(1)
    time.sleep(0.03)
    assert "id" not in calls
    assert not analytics.status()["enabled"]


def test_control_steps_share_one_deadline(browser, monkeypatch):
    now = [100.0]
    calls = []
    monkeypatch.setattr(colab, "time", types.SimpleNamespace(monotonic=lambda: now[0]))

    def exchange(command, event, *, timeout_sec):
        calls.append((command, timeout_sec))
        now[0] += 1.25
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    analytics.enable()
    wait_until(lambda: not browser.pending)
    assert calls == [("accept", 2), ("id", 0.75)]


def test_expired_control_never_requests_id(browser, monkeypatch):
    now = [100.0]
    calls = []
    monkeypatch.setattr(colab, "time", types.SimpleNamespace(monotonic=lambda: now[0]))

    def exchange(command, event, **kwargs):
        calls.append(command)
        now[0] += 2.1
        return accepted()

    monkeypatch.setattr(colab, "exchange", exchange)
    analytics.enable()
    wait_until(lambda: not browser.pending)
    assert calls == ["accept"]
    assert not analytics.status()["enabled"]


def test_notebook_observer_forwards_adapter_deadline(browser, monkeypatch):
    import ast
    import json
    from pathlib import Path

    notebook = json.loads(
        (
            Path(__file__).resolve().parents[3] / "docs/verification/analytics-colab-sdk.ipynb"
        ).read_text()
    )
    cell = next(cell for cell in notebook["cells"] if "def observed(" in "".join(cell["source"]))
    function = next(
        node
        for node in ast.parse("".join(cell["source"])).body
        if isinstance(node, ast.FunctionDef) and node.name == "observed"
    )
    calls = []

    def eval_js(script, *, timeout_sec):
        calls.append((script, timeout_sec))
        return {"status": "upstream_accepted"}

    monkeypatch.setattr(
        sys.modules["google.colab"], "output", types.SimpleNamespace(eval_js=eval_js), raising=False
    )
    monkeypatch.setattr(
        wiring, "coordinator", lambda: types.SimpleNamespace(accepts=lambda e: True)
    )
    namespace = {"original": colab.exchange, "acknowledgements": [], "event_ids": []}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "notebook-observer", "exec"),
        namespace,
    )
    monkeypatch.setattr(colab, "exchange", namespace["observed"])
    for index in range(4):
        browser._dispatch(browser._generation, "events", {"event_id": str(index)})
    assert namespace["event_ids"] == ["0", "1", "2", "3"]
    assert namespace["acknowledgements"] == [{"status": "upstream_accepted"}] * 4
    assert len(calls) == 4
    assert all(0 < timeout <= 2 for _, timeout in calls)


def notebook_opt_out_tail():
    import ast
    import json
    from pathlib import Path

    notebook = json.loads(
        (
            Path(__file__).resolve().parents[3] / "docs/verification/analytics-colab-sdk.ipynb"
        ).read_text()
    )
    cell = next(cell for cell in notebook["cells"] if "def observed(" in "".join(cell["source"]))
    tree = ast.parse("".join(cell["source"]))
    setup = next(node for node in tree.body if isinstance(node, ast.With))
    client = setup.body[0]
    assert isinstance(client, ast.With)
    start = next(
        i
        for i, node in enumerate(client.body)
        if isinstance(node, ast.Expr) and ast.unparse(node) == "sf.analytics.disable()"
    )
    # Execute the actual verification tail, including its deadline and assertions.
    return compile(
        ast.Module(body=client.body[start:], type_ignores=[]), "notebook-opt-out", "exec"
    )


def test_notebook_rejects_unacknowledged_opt_out(browser, monkeypatch):
    import screamingface as sf

    entered, release = threading.Event(), threading.Event()

    def exchange(command, event, **kwargs):
        assert command == "decline"
        entered.set()
        assert release.wait(2)
        return {"choice": "declined", "consent_version": "1"}

    monkeypatch.setattr(colab, "exchange", exchange)
    clock = iter([0, 11])
    fake_time = types.SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda _: None)
    # Without the pending assertion, the remaining verification would falsely pass.
    fake_client = types.SimpleNamespace(
        evaluate=lambda _: None, leaderboards=types.SimpleNamespace(submit=lambda _: None)
    )
    namespace = {
        "sf": sf,
        "time": fake_time,
        "client": fake_client,
        "Candidate": object,
        "acknowledgements": [1, 2, 3, 4],
    }
    try:
        with pytest.raises(AssertionError):
            exec(notebook_opt_out_tail(), namespace)
        assert entered.wait(1)
        assert analytics.status()["pending"] is True
        assert analytics.status()["choice"] == "declined"
    finally:
        release.set()
        wait_until(lambda: not browser.pending)
