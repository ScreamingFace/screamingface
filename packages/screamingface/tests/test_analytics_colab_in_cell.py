"""Colab browser round trips finish while the triggering cell is still running.

STORY: as a Colab user, `sf.analytics.status()` reports the consent my browser actually has.
WHY: Colab only answers a background `eval_js` call while the cell that started it executes;
after the cell ends the call returns `None` once its timeout passes (reproduced 2026-11-19).
These fakes answer only while a "cell running" flag is set, and the tests clear that flag as
soon as the triggering call returns, exactly as a finished cell would.
"""

import asyncio
import builtins
import socket
import sys
import threading
import time
import types
from typing import Any, cast

import pytest
from test_analytics_colab import (
    accepted,
    browser,  # noqa: F401  (fixture, requested by name)
)

import screamingface as sf
from screamingface import analytics
from screamingface._analytics import colab, prompt, tracking


class CellBoundBrowser:
    """A browser that only answers while the triggering cell is still executing."""

    def __init__(self, *, events_delay: float = 0.0, silent: bool = False) -> None:
        self.running = threading.Event()
        self.running.set()
        self.events_delay = events_delay
        self.silent = silent
        self.calls: list[str] = []
        self.delivered: list[str] = []

    def exchange(self, command, event=None, **kwargs):
        self.calls.append(command)
        if self.silent:
            time.sleep(kwargs.get("timeout_sec", colab.BRIDGE_TIMEOUT))
            raise TimeoutError("no browser reply")
        if command == "events":
            time.sleep(self.events_delay)
        if not self.running.is_set():
            # INVARIANT: a lost reply after the cell ended is a timeout (D3).
            return {"choice": "unknown", "unavailable": True, "reason": "timeout"}
        if command == "events":
            assert event is not None
            self.delivered.append(event["event"])
            return {"status": "upstream_accepted", "count": 1}
        return accepted()


@pytest.fixture
def cell(request, monkeypatch):
    request.getfixturevalue("browser")
    fake = CellBoundBrowser()
    connections = []

    def forbidden_connect(*args, **kwargs):
        connections.append(True)
        raise AssertionError("These tests must never use real network connections")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    monkeypatch.setattr(colab, "exchange", fake.exchange)
    yield fake
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


def fake_colab_output(monkeypatch, reply):
    module = types.ModuleType("google.colab.output")
    setattr(module, "eval_js", lambda script, ignore_result=False, timeout_sec=None: reply)
    monkeypatch.setitem(sys.modules, "google.colab.output", module)
    monkeypatch.setattr(sys.modules["google.colab"], "output", module, raising=False)


# --- D3: a lost reply is a timeout, a malformed one stays invalid ---------------------------


@pytest.mark.usefixtures("browser")
def test_lost_browser_reply_is_a_timeout_marker(monkeypatch):
    fake_colab_output(monkeypatch, None)
    reply = colab.exchange("state", timeout_sec=0.1)
    assert reply == {"choice": "unknown", "unavailable": True, "reason": "timeout"}


@pytest.mark.usefixtures("browser")
def test_lost_browser_reply_is_reported_as_setup_timeout(monkeypatch):
    fake_colab_output(monkeypatch, None)
    prompt.before_evaluation()
    state = analytics.status()
    assert state["last_error"] == "setup_timeout"
    assert state["last_error_stage"] == "state"
    assert not state["enabled"]


@pytest.mark.usefixtures("browser")
def test_malformed_browser_reply_is_still_invalid(monkeypatch):
    fake_colab_output(monkeypatch, "not a reply")
    prompt.before_evaluation()
    assert analytics.status()["last_error"] == "setup_invalid_response"


# --- D1: setup started at a sync entry point settles inside that cell ----------------------


@pytest.mark.usefixtures("browser")
def test_offer_and_settle_finishes_setup_while_the_cell_runs(cell):
    prompt.offer_and_settle()
    cell.running.clear()
    state = analytics.status()
    assert state["choice"] == "accepted" and state["enabled"]
    assert state["last_error"] is None
    assert not state["pending"]


@pytest.mark.usefixtures("browser")
def test_offer_and_settle_is_bounded_when_the_browser_never_answers(cell):
    cell.silent = True
    start = time.monotonic()
    prompt.offer_and_settle()
    assert time.monotonic() - start < colab.BRIDGE_TIMEOUT + 0.75
    assert not analytics.status()["enabled"]


@pytest.mark.usefixtures("browser")
def test_offer_and_settle_respects_do_not_track(cell, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    start = time.monotonic()
    prompt.offer_and_settle()
    assert time.monotonic() - start < 0.5
    assert cell.calls == []


@pytest.mark.usefixtures("browser")
def test_offer_alone_still_returns_before_setup(cell):
    # INVARIANT: plain offer() stays non-blocking; the async path calls it on the event loop.
    cell.silent = True
    start = time.monotonic()
    prompt.offer()
    assert time.monotonic() - start < 0.5


@pytest.mark.parametrize("entry", ["default", "client"])
def test_connect_panel_settles_setup(monkeypatch, entry):
    import screamingface as sf
    from screamingface import _default_client

    calls = []
    monkeypatch.setattr(prompt, "offer_and_settle", lambda: calls.append("settle"))
    monkeypatch.setattr(prompt, "offer", lambda: calls.append("offer"))
    monkeypatch.setattr(
        "screamingface._ui.connections.ConnectionPanel", lambda client: types.SimpleNamespace()
    )
    if entry == "default":
        monkeypatch.setattr(_default_client, "default_client", lambda: object())
        sf.connect()
    else:
        with sf.Client() as client:
            client.connect()
    assert calls == ["settle"]


# --- D2: the terminal event is acknowledged before a tracked call returns ------------------


@pytest.mark.usefixtures("browser")
def test_finished_event_is_acknowledged_before_the_call_returns(cell, evaluate):
    cell.events_delay = 0.3
    evaluate()
    cell.running.clear()
    assert cell.delivered == ["evaluation_started", "evaluation_finished"]
    state = analytics.status()
    assert state["choice"] == "accepted" and state["enabled"]
    assert state["last_error"] is None


class _Owner:
    _engine_url = "https://fusion.screamingface.ai"


@pytest.mark.usefixtures("browser")
def test_cancelled_operation_does_not_wait_for_its_event(cell):
    prompt.offer_and_settle()
    cell.events_delay = 3.0

    @tracking.tracked("evaluation")
    def interrupted(owner, candidates):
        raise KeyboardInterrupt

    start = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        interrupted(_Owner(), "url4://candidate")
    assert time.monotonic() - start < 2.0


@pytest.mark.usefixtures("browser")
def test_flush_is_bounded_when_delivery_never_answers(cell):
    prompt.offer_and_settle()
    cell.events_delay = 30.0

    @tracking.tracked("evaluation")
    def finished(owner, candidates):
        return types.SimpleNamespace(ok=True)

    start = time.monotonic()
    finished(_Owner(), "url4://candidate")
    assert time.monotonic() - start < colab.BRIDGE_TIMEOUT + 1.5


@pytest.mark.usefixtures("browser")
def test_async_finished_event_is_acknowledged_before_the_call_returns(cell):
    prompt.offer_and_settle()
    cell.events_delay = 0.3

    @tracking.tracked("evaluation")
    async def finished(owner, candidates):
        return types.SimpleNamespace(ok=True)

    asyncio.run(finished(_Owner(), "url4://candidate"))
    cell.running.clear()
    assert cell.delivered[-1] == "evaluation_finished"
    assert analytics.status()["enabled"]


# --- D1 at import: settle after the importing cell's code, outside the import lock ---------
# WHY: waiting inside `screamingface/__init__.py` deadlocks on the package import lock (the
# worker imports `screamingface` modules), observed in Colab on 2026-11-19. A one-shot IPython
# `post_run_cell` callback runs after the cell's code while Colab still treats it as running.


class FakeEvents:
    def __init__(self) -> None:
        self.callbacks: list = []

    def register(self, name, callback):
        assert name == "post_run_cell"
        self.callbacks.append(callback)

    def unregister(self, name, callback):
        assert name == "post_run_cell"
        self.callbacks.remove(callback)

    def trigger(self):
        for callback in self.callbacks[:]:
            callback(None)


@pytest.fixture
def shell(monkeypatch):
    fake = types.SimpleNamespace(events=FakeEvents())
    monkeypatch.setattr(builtins, "get_ipython", lambda: fake, raising=False)
    return fake


@pytest.mark.usefixtures("browser")
def test_import_offer_settles_after_the_importing_cell_in_colab(cell, shell, monkeypatch):
    settled = []
    monkeypatch.setattr(prompt, "offer_and_settle", lambda: settled.append(True))
    start = time.monotonic()
    prompt.offer_at_import()
    assert time.monotonic() - start < 0.5
    assert len(shell.events.callbacks) == 1
    shell.events.trigger()
    assert settled == [True]
    assert shell.events.callbacks == []
    shell.events.trigger()
    assert settled == [True]


@pytest.mark.usefixtures("browser")
def test_import_offer_then_cell_end_ends_accepted(cell, shell):
    prompt.offer_at_import()
    shell.events.trigger()
    cell.running.clear()
    state = analytics.status()
    assert state["choice"] == "accepted" and state["last_error"] is None


def test_import_offer_outside_colab_registers_nothing(shell, monkeypatch):
    monkeypatch.setattr(prompt, "origin", lambda: "python")
    monkeypatch.setattr(prompt, "offer", lambda: None)
    prompt.offer_at_import()
    assert shell.events.callbacks == []


@pytest.mark.usefixtures("browser")
def test_import_offer_without_an_ipython_shell_is_harmless(monkeypatch):
    monkeypatch.setattr(builtins, "get_ipython", lambda: None, raising=False)
    monkeypatch.setattr(prompt, "offer", lambda: None)
    prompt.offer_at_import()
