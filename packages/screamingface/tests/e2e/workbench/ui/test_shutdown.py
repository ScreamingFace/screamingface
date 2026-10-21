"""Stopping the UI process stops its active run (a paid ``local`` run must not keep spending).

A run lives in its own session, so neither Ctrl-C in the UI's terminal nor a SIGTERM to the UI
reaches it. These tests boot the real ``python -m workbench.ui`` entry point with a fake run
(a sleeper that leaves a grandchild, tagged with a unique marker), start a run through the HTTP
API with an event stream open (as a browser on the run page would hold it), signal ONLY the UI
process, and require the whole run group gone once the UI has exited.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest

from workbench.ui import __main__ as entry
from workbench.ui.test_entrypoint import _env, _free_port, _get_page, _lines, _port_is_free

_DRIVER = textwrap.dedent(
    """
    import functools, sys
    from workbench.ui import __main__ as entry
    from workbench.ui import runs

    marker, stubborn = sys.argv[1], sys.argv[2] == "stubborn"
    ignore = (
        "import signal; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        if stubborn
        else ""
    )
    script = (
        f"{ignore}import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', '{ignore}import time; time.sleep(120)', "
        f"'{marker}']); print('up', flush=True); time.sleep(120)"
    )

    def spawn(argv, env, cwd):
        return runs._spawn([sys.executable, "-c", script], env, cwd)

    entry.RunManager = functools.partial(
        entry.RunManager, spawn=spawn, interrupt_grace=2.0, terminate_grace=2.0
    )
    entry.main(sys.argv[3:])
    """
)


def _running(marker: str) -> bool:
    found = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    return found.stdout.strip() != ""


def _wait(condition, timeout: float) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def _hold_events(url: str, stop: threading.Event) -> None:
    try:
        with httpx.stream("GET", url, timeout=None) as response:
            for _ in response.iter_lines():
                if stop.is_set():
                    return
    except httpx.HTTPError:
        pass  # the server went away: expected


def _boot(tmp_path: Path, marker: str, stubborn: bool) -> tuple[subprocess.Popen[str], str]:
    """Start the UI with the fake run; return it and its tokenised URL once it serves."""
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER)
    port = _free_port()
    argv = [sys.executable, str(driver), marker, "stubborn" if stubborn else "plain"]
    argv += ["--out", str(tmp_path / "wb"), "--port", str(port), "--no-open"]
    proc = subprocess.Popen(
        argv,
        cwd=entry.PACKAGE_DIR,
        env=_env(PYTHONPATH="tests/e2e"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    sink: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_lines, args=(proc, sink), daemon=True).start()
    while True:
        line = sink.get(timeout=60)
        assert line is not None, "the UI exited before printing its URL"
        if line.startswith(f"http://127.0.0.1:{port}/?token="):
            _get_page(line)
            return proc, line


def _start_run(url: str, stop: threading.Event) -> None:
    """POST a run with the header token and hold its event stream open, like a browser."""
    base, token = url.split("/?token=", 1)
    started = httpx.post(
        f"{base}/runs",
        json={"target": "replay", "notebooks": []},
        headers={"x-workbench-token": token},
        follow_redirects=False,
    )
    assert started.status_code == 303, started.text
    events = f"{base}{started.headers['location'].split('?', 1)[0]}/events"
    threading.Thread(target=_hold_events, args=(events, stop), daemon=True).start()


_INT, _TERM, _HUP = signal.SIGINT, signal.SIGTERM, signal.SIGHUP


@pytest.mark.parametrize(
    ("sigs", "stubborn"),
    [
        ((_TERM,), False),
        ((_TERM,), True),
        ((_INT,), False),
        ((_INT,), True),
        # An impatient double Ctrl-C makes uvicorn force-exit and skip the lifespan shutdown.
        ((_INT, _INT), False),
        # A third one lands while the UI waits for the run's teardown: the run is killed.
        ((_INT, _INT, _INT), True),
        # The terminal was closed (uvicorn does not handle SIGHUP itself).
        ((_HUP,), False),
    ],
    ids=[
        "sigterm",
        "sigterm-stubborn",
        "ctrl-c",
        "ctrl-c-stubborn",
        "ctrl-c-twice",
        "ctrl-c-thrice-stubborn",
        "sighup",
    ],  # fmt: skip
)
def test_stopping_the_ui_stops_the_active_run(
    tmp_path: Path, sigs: tuple[signal.Signals, ...], stubborn: bool
) -> None:
    marker = f"wb-shutdown-{uuid.uuid4().hex}"
    proc, url = _boot(tmp_path, marker, stubborn)
    stop = threading.Event()
    try:
        _start_run(url, stop)
        assert _wait(lambda: _running(marker), 20), "the fake run never started"
        for sig in sigs:  # the UI process only, as a terminal or supervisor would
            os.kill(proc.pid, sig)
            time.sleep(0.5)
        assert proc.wait(timeout=60) == 128 + sigs[0]
        assert _wait(lambda: not _running(marker), 10), "the run outlived the UI"
        assert _port_is_free(int(url.split(":")[2].split("/")[0]))
    finally:
        stop.set()
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        subprocess.run(["pkill", "-9", "-f", marker], check=False)
