"""The uvicorn log surfaces that `access_log=False` does not close (OME-1049).

FEATURE: local runtime log hygiene — `runtime.log` is the process's whole stdout/stderr sink.
"""

from __future__ import annotations

import asyncio
import logging
import logging.config
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from screamingface._runtime import runtime_logging, server
from screamingface._runtime.config import RuntimeConfig

TICKET = "cap-ticket-0123456789abcdef"
WS_ACCEPT = '%s - "WebSocket %s" [accepted]'


@pytest.fixture
def uvicorn_error() -> Iterator[logging.Logger]:
    logger = logging.getLogger("uvicorn.error")
    saved = (list(logger.filters), list(logger.handlers), logger.level, logger.propagate)
    try:
        yield logger
    finally:
        logger.filters[:], logger.handlers[:] = saved[0], saved[1]
        logger.setLevel(saved[2])
        logger.propagate = saved[3]


def _stub_uvicorn(monkeypatch: pytest.MonkeyPatch, configs: list[dict[str, object]]) -> None:
    # WHY a stub: the SDK test job installs no runtime extra, so uvicorn is absent here —
    # the same reason `_recording_uvicorn` exists in test_runtime_cli.py.
    class Config:
        def __init__(self, app: object, **options: object) -> None:
            configs.append(options)

    module = types.ModuleType("uvicorn")
    module.Config = Config  # type: ignore[attr-defined]
    module.run = lambda app, **options: configs.append(options)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", module)


def _build_embedded_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    class Recorder:
        def __init__(self, config: object, *, name: str) -> None:
            self.config, self.name = config, name

    _stub_uvicorn(monkeypatch, [])
    monkeypatch.setattr(server, "_embedded_server_type", lambda: Recorder)
    server._server(object(), 9105, "AI Gateway")
    server._server(object(), 9106, "Engine")


def test_a_websocket_ticket_never_reaches_the_runtime_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uvicorn_error: logging.Logger
) -> None:
    # INVARIANT (OME-1049): the Engine's WS URL is `/ws?ticket=<token>` and uvicorn.error
    # logs the full path-with-query on every handshake. The ticket is a CREDENTIAL that
    # authorises a run, so it must never be written to runtime.log.
    path = tmp_path / "runtime.log"
    _build_embedded_servers(monkeypatch)

    with runtime_logging.capture_runtime_log(path, foreground=False):
        # WHY bound inside the capture: that is how uvicorn's handler resolves to the
        # RuntimeLog in production — its StreamHandler captures sys.stderr at dictConfig time.
        uvicorn_error.addHandler(logging.StreamHandler(sys.stderr))
        uvicorn_error.setLevel(logging.INFO)
        uvicorn_error.info(WS_ACCEPT, "127.0.0.1:50000", f"/ws?ticket={TICKET}")
        uvicorn_error.info('%s - "WebSocket %s" %d', "127.0.0.1:50000", f"/ws?ticket={TICKET}", 403)

    written = path.read_text()
    assert TICKET not in written
    assert "ticket=" not in written
    # The line is rewritten, not suppressed: the handshake stays debuggable.
    assert '"WebSocket /ws" [accepted]' in written
    assert '"WebSocket /ws" 403' in written


def test_the_redaction_survives_a_later_dict_config(
    monkeypatch: pytest.MonkeyPatch, uvicorn_error: logging.Logger
) -> None:
    # WHY: every uvicorn Config re-runs dictConfig over the `uvicorn.error` logger, so a
    # protection that a later Config silently removed would protect only the first server.
    _build_embedded_servers(monkeypatch)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "loggers": {"uvicorn.error": {"level": "INFO"}},
        }
    )
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    uvicorn_error.addHandler(handler)

    uvicorn_error.info(WS_ACCEPT, "127.0.0.1:50000", f"/ws?ticket={TICKET}")

    assert [record.getMessage() for record in records] == [
        '127.0.0.1:50000 - "WebSocket /ws" [accepted]'
    ]


def test_the_redaction_is_installed_once_however_many_servers_are_built(
    monkeypatch: pytest.MonkeyPatch, uvicorn_error: logging.Logger
) -> None:
    _build_embedded_servers(monkeypatch)
    _build_embedded_servers(monkeypatch)

    redactors = [f for f in uvicorn_error.filters if isinstance(f, server._QueryStringRedactor)]
    assert len(redactors) == 1


@pytest.mark.parametrize(
    ("message", "args", "expected"),
    [
        # Non-path arguments are untouched, even when they carry a "?".
        ("Started server process [%d]", (42,), "Started server process [42]"),
        ("%s says %s", ("who?", "what?"), "who? says what?"),
        # A path without a query string is untouched.
        (WS_ACCEPT, ("127.0.0.1:1", "/ws"), '127.0.0.1:1 - "WebSocket /ws" [accepted]'),
        # A record with no arguments at all.
        ("Application startup complete.", (), "Application startup complete."),
    ],
)
def test_the_redaction_leaves_every_other_record_unchanged(
    message: str, args: tuple[object, ...], expected: str
) -> None:
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, message, args, None)

    assert server._QueryStringRedactor().filter(record) is True
    assert record.getMessage() == expected


def test_the_scoreboard_server_is_configured_without_an_access_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT (OME-1049): the scoreboard runs in its own interpreter, but its stdout is
    # relayed into the same runtime.log by `_relay_scoreboard_output` — so it takes the same
    # access_log=False posture as `test_every_embedded_server_is_configured_without_an_access_log`.
    configs: list[dict[str, object]] = []
    _stub_uvicorn(monkeypatch, configs)

    async def _seed(**_: object) -> None:
        return None

    stubs = {
        "scoreboard.config": {"Settings": lambda **settings: settings},
        "scoreboard.main": {"create_app": lambda settings: object()},
        "scoreboard.seed": {"_run": _seed, "load_benchmarks_json": lambda raw: []},
        "screamingface_engine.benchmarks.builtins": {"BUILTIN_BENCHMARKS": ()},
    }
    for name, attributes in stubs.items():
        module = types.ModuleType(name)
        for attribute, value in attributes.items():
            setattr(module, attribute, value)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(server, "scoreboard_assets", lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(server, "scoreboard_seed_json", lambda benchmarks: "[]")
    for variable in ("SCOREBOARD_PORTAL_DIR", "SCOREBOARD_PORTAL_ARTIFACTS_DIR"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SCOREBOARD_DATABASE_URL", "unset")
    monkeypatch.setattr(asyncio, "run", lambda coroutine: coroutine.close())

    server.run_scoreboard(RuntimeConfig(data_dir=tmp_path))

    assert len(configs) == 1
    assert configs[0].get("access_log") is False
    assert configs[0]["host"] == "127.0.0.1"
