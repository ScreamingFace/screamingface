"""Regressions for the url4 audit (2026-10-09, report §4.E: E1 and E7).

E1: a command subprocess that outlives the request timeout must be killed, reaped,
and have its pipes closed, not left running (or holding an fd) after the 504.
E7: a built-in TimeoutError raised by a handler is not a request timeout.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import time
from pathlib import Path

import httpx
import pytest

from url4.cli._serve import ServeConfig, build_asgi_app, build_node
from url4.peer.server import Url4Node

pytestmark = pytest.mark.asyncio


def _driver(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node")


def _open_fds() -> int:
    # WHY /dev/fd: it lists this process's open descriptors, so a pipe left open
    # shows up as growth. The test does not call gc, so no GC pass hides a leak.
    return len(os.listdir("/dev/fd"))


def _argv_writing_pid(pid_file: Path, tail: str) -> tuple[str, ...]:
    # WHY exec: the shell replaces itself, so $$ is the pid of the long-running child.
    return ("sh", "-c", f"echo $$ > {shlex.quote(str(pid_file))}; exec {tail}")


def _kill_leftover(pid: int) -> None:
    # Cleanup only: a failing RED run must not leave `sleep 30` or `yes` running.
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@pytest.mark.parametrize("tail", ["sleep 30", "yes"], ids=["sleep", "yes"])
async def test_timed_out_command_is_killed_and_reaped(tmp_path: Path, tail: str) -> None:
    pid_file = tmp_path / "pid"
    config = ServeConfig(commands={"/hang": _argv_writing_pid(pid_file, tail)}, timeout=0.3)
    app = build_asgi_app(build_node(config), config)
    fds_before = _open_fds()
    async with _driver(app) as http:
        response = await http.get("/v1", params={"q": "(r=/hang(x)!'go')!'$r'"})
    pid = int(pid_file.read_text())
    try:
        assert response.status_code == 504
        # A killed-but-unreaped child is a zombie and still answers signal 0,
        # so this asserts both the kill and the reap.
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert _open_fds() <= fds_before
    finally:
        _kill_leftover(pid)


async def _gone_soon(pid: int) -> bool:
    # A grandchild is reparented to init when its parent dies; init reaps it on its own
    # schedule, so poll briefly instead of asserting at one instant.
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.01)
    return False


async def test_timed_out_command_kills_descendants_holding_stdout(tmp_path: Path) -> None:
    # A background descendant inherits stdout: killing only the child leaves the pipe
    # open (the drain would wait for it) and lets it act after the 504.
    gpid_file = tmp_path / "gpid"
    tail = f"sleep 30 & echo $! > {shlex.quote(str(gpid_file))}; exec yes"
    config = ServeConfig(commands={"/hang": ("sh", "-c", tail)}, timeout=0.3)
    app = build_asgi_app(build_node(config), config)
    fds_before = _open_fds()
    started = time.monotonic()
    async with _driver(app) as http:
        response = await http.get("/v1", params={"q": "(r=/hang(x)!'go')!'$r'"})
    elapsed = time.monotonic() - started
    gpid = int(gpid_file.read_text())
    try:
        assert response.status_code == 504
        assert elapsed < 2.0
        assert await _gone_soon(gpid)
        assert _open_fds() <= fds_before
    finally:
        _kill_leftover(gpid)


async def test_handler_timeout_error_is_not_a_request_timeout() -> None:
    node = Url4Node("t", eval_path="/v1")

    @node.endpoint("/boom")
    async def boom(_request) -> str:
        raise TimeoutError()

    app = build_asgi_app(node, ServeConfig(timeout=5.0))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://node") as http:
        response = await http.get("/v1", params={"q": "(r=/boom(x)!'go')!'$r'"})
    # The body is not asserted: it depends on the JSON 500 handler landing separately.
    assert response.status_code == 500
