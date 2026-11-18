"""The server seam of the CLI: `_run_server` starts uvicorn with the chat drain on the stop signal.

FEATURE: POST /v1/chat/completions (prd/chat-completion.md CC-S37). These tests replace
`uvicorn.Server.run`, so no server starts. The proof with a real process and the real stop signal
is CC-39 (tests/integration/test_chat_drain_signal.py).
"""

from __future__ import annotations

import signal
import weakref
from typing import Any

import pytest
import uvicorn

from screamingface_engine import cli
from screamingface_engine.rest import chat_drain
from screamingface_engine.rest.chat_drain import ChatDrain

_APP = "screamingface_engine.local:create_local_app"


@pytest.fixture(autouse=True)
def _own_drains(monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: `handle_exit` requests EACH live drain of the process. An App of another test module
    can be alive on the same worker, and its drain must stay as it is."""
    monkeypatch.setattr(chat_drain, "_DRAINS", weakref.WeakSet[ChatDrain]())


def _built_server(
    monkeypatch: pytest.MonkeyPatch, *, started: bool = True, interrupted: bool = False
) -> uvicorn.Server:
    """The server that `_run_server` builds; its `run` is replaced, so nothing is served."""
    built: list[uvicorn.Server] = []

    def _run(self: uvicorn.Server, sockets: Any = None) -> None:
        self.started = started
        built.append(self)
        if interrupted:
            raise KeyboardInterrupt

    monkeypatch.setattr(uvicorn.Server, "run", _run)
    try:
        cli._run_server(_APP, factory=True, host="127.0.0.1", port=9111)
    finally:
        assert len(built) == 1
    return built[0]


def test_the_server_gets_the_arguments_and_keeps_the_uvicorn_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _built_server(monkeypatch).config

    assert config.app == _APP
    assert config.factory is True
    assert config.host == "127.0.0.1"
    assert config.port == 9111
    # INVARIANT (OME-890): the WS ping defaults of uvicorn are load-bearing (see `cli._serve`).
    # The seam builds the config itself, so it must not change them.
    assert config.ws_ping_interval == 20.0
    assert config.ws_ping_timeout == 20.0
    # INVARIANT: no time limit on the graceful shutdown; the chat drain ends the open requests.
    assert config.timeout_graceful_shutdown is None


def test_the_stop_signal_requests_each_live_drain_then_the_normal_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-S37: the first stop signal sets the drain, and uvicorn then shuts down as usual."""
    first, second = ChatDrain(), ChatDrain()
    server = _built_server(monkeypatch)
    assert not first.requested
    assert not server.should_exit

    server.handle_exit(signal.SIGTERM, None)

    assert first.requested
    assert second.requested
    assert server.should_exit is True
    assert server.force_exit is False


def test_a_second_interrupt_still_forces_the_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The subclass keeps uvicorn's own rule: a second SIGINT forces the exit."""
    drain = ChatDrain()
    server = _built_server(monkeypatch)

    server.handle_exit(signal.SIGINT, None)
    server.handle_exit(signal.SIGINT, None)

    assert drain.requested
    assert server.force_exit is True


def test_an_error_of_the_drain_does_not_stop_the_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """The handler of uvicorn runs also when the drain raises; the error is not hidden."""

    def _broken() -> int:
        raise RuntimeError("the loop is closed")

    # The seam imports the function when it builds the server, so replace it first.
    monkeypatch.setattr(chat_drain, "request_all_drains", _broken)
    server = _built_server(monkeypatch)

    with pytest.raises(RuntimeError):
        server.handle_exit(signal.SIGTERM, None)

    assert server.should_exit is True


def test_a_server_that_did_not_start_exits_with_the_uvicorn_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same exit code as `uvicorn.run`, so a failed start is not a clean exit."""
    with pytest.raises(SystemExit) as exit_info:
        _built_server(monkeypatch, started=False)

    assert exit_info.value.code == 3


def test_a_keyboard_interrupt_from_the_server_is_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _built_server(monkeypatch, interrupted=True)

    assert server.started is True
