"""CC-39: the real stop signal drains the waiting chat requests before the server shuts down.

FEATURE: POST /v1/chat/completions (prd/chat-completion.md CC-S37).

The server runs in a subprocess through `cli._run_server`, the seam of both start paths, and
gets a real SIGTERM. A direct call of a hook cannot fail for the reason that this test guards:
uvicorn calls the shutdown hook of the App only after each open request has ended. Without the
drain at the signal, each request below waits for its time limit (120 s) and the test fails at
its own limit.
"""

from __future__ import annotations

import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

_UNIT = Path(__file__).parent.parent / "unit"
# The same text as `SCHEDULED_MARK` of tests/unit/_chat_drain_server.py (that module is on the
# path of the server process only).
_SCHEDULED_MARK = "CHAT-RUN-SCHEDULED"
_LISTENING = re.compile(r"Uvicorn running on http://127\.0\.0\.1:(\d+)")
_HEADERS = {"X-User-Email": "caller@example.com"}
_BODY = {"model": "prov/a", "messages": [{"role": "user", "content": "Capital of France?"}]}
_START_LIMIT_S = 60.0
_ANSWER_LIMIT_S = 20.0


class _Server:
    """One Engine server process with a reader of its output lines."""

    def __init__(self) -> None:
        # WHY port 0: the server binds a free port itself, so no other process can take a port
        # between a probe and the bind. The port is read from the start line of uvicorn.
        code = (
            "from screamingface_engine import cli; "
            "cli._run_server('_chat_drain_server:create', factory=True, host='127.0.0.1', port=0)"
        )
        paths = [str(_UNIT), os.environ.get("PYTHONPATH", "")]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(path for path in paths if path)}
        self.proc = subprocess.Popen(
            [sys.executable, "-c", code],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.port = 0
        self._lines: queue.Queue[str] = queue.Queue()
        self.output: list[str] = []
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.output.append(line)
            self._lines.put(line)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1/chat/completions"

    def _next_line(self, deadline: float) -> str | None:
        try:
            return self._lines.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            return None

    def wait_listening(self) -> None:
        deadline = time.monotonic() + _START_LIMIT_S
        while (line := self._next_line(deadline)) is not None:
            if found := _LISTENING.search(line):
                self.port = int(found.group(1))
                return
        pytest.fail(f"the server did not start:\n{''.join(self.output)}")

    def wait_scheduled(self, runs: int) -> None:
        deadline = time.monotonic() + _ANSWER_LIMIT_S
        seen = 0
        while seen < runs:
            line = self._next_line(deadline)
            if line is None:
                pytest.fail(f"{seen} of {runs} runs were scheduled:\n{''.join(self.output)}")
            seen += _SCHEDULED_MARK in line

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(10)
        self._reader.join(10)
        if self.proc.stdout is not None:
            self.proc.stdout.close()


@pytest.fixture
def server() -> Iterator[_Server]:
    started = _Server()
    try:
        started.wait_listening()
        yield started
    finally:
        started.stop()


def _plain(url: str) -> httpx.Response:
    return httpx.post(url, json=_BODY, headers=_HEADERS, timeout=_ANSWER_LIMIT_S * 2)


def _streamed(url: str) -> tuple[int, str]:
    body = {**_BODY, "stream": True}
    with httpx.stream(
        "POST", url, json=body, headers=_HEADERS, timeout=_ANSWER_LIMIT_S * 2
    ) as resp:
        return resp.status_code, "".join(resp.iter_text())


def test_stop_signal_drains_waiting_chat_requests_before_server_shutdown(server: _Server) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        plain = pool.submit(_plain, server.url)
        streamed = pool.submit(_streamed, server.url)
        try:
            server.wait_scheduled(runs=2)

            server.proc.send_signal(signal.SIGTERM)

            resp = plain.result(_ANSWER_LIMIT_S)
            status, text = streamed.result(_ANSWER_LIMIT_S)
            exit_status = server.proc.wait(_ANSWER_LIMIT_S)
        finally:
            # WHY: after a failure, the pool exit must not wait for the time limit of a client.
            server.stop()

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "server_restarting"
    assert resp.headers["x-should-retry"] == "true"
    assert resp.headers["retry-after"] == "5"
    assert status == 200
    assert '"code":"server_restarting"' in text.replace(" ", "")
    assert "[DONE]" not in text
    # The server then ends by its normal shutdown. uvicorn raises the signal again after it, so
    # the exit status is the signal, or 0 on a platform where the signal has no default action.
    assert exit_status in (0, -signal.SIGTERM)
