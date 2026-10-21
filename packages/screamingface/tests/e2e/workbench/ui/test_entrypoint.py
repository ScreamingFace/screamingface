"""The documented ways to start the UI really serve it (unit 4 plan, Task 6).

``python -m workbench.ui`` can only resolve with ``tests/e2e`` on ``PYTHONPATH``: the package
is imported before ``__main__`` runs, so ``__main__`` cannot fix the path itself. The ``just
workbench-ui`` recipe sets it, and these tests boot both commands for real, fetch the page with
the printed token, and stop the server again.
"""

from __future__ import annotations

import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from workbench.ui import __main__ as entry

_BOOT_TIMEOUT_S = 120.0  # `uv run` may sync the env on first use
_URL_PREFIX = "http://127.0.0.1:"
# Never hand a provider key to a server a test starts; it would only be shown as "available".
_SCRUB = ("OPENROUTER_API_KEY", "SCREAMINGFACE_TEST_PAID", "PYTHONPATH")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _port_is_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _env(**extra: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _SCRUB} | extra


def _lines(proc: subprocess.Popen[str], sink: queue.Queue[str | None]) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        sink.put(line.rstrip("\n"))
    sink.put(None)


@contextmanager
def _serving(
    argv: list[str], env: dict[str, str], port: int, *, cwd: Path = entry.PACKAGE_DIR
) -> Iterator[str]:
    """Start ``argv`` in ``cwd``, yield the tokenised URL it prints, then stop its whole group."""
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    sink: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_lines, args=(proc, sink), daemon=True).start()
    seen: list[str] = []
    try:
        deadline = time.monotonic() + _BOOT_TIMEOUT_S
        url = None
        while url is None:
            line = sink.get(timeout=max(0.1, deadline - time.monotonic()))
            assert line is not None, "exited before printing a URL:\n" + "\n".join(seen)
            seen.append(line)
            if line.startswith(f"{_URL_PREFIX}{port}/?token="):
                url = line
        yield url
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGINT)  # Ctrl-C, as a developer stops it
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


def _get_page(url: str) -> httpx.Response:
    deadline = time.monotonic() + 20
    while True:  # the URL is printed just before uvicorn binds
        try:
            return httpx.get(url, timeout=5)
        except httpx.ConnectError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def _assert_serves_the_index(url: str) -> None:
    response = _get_page(url)
    assert response.status_code == 200
    assert "Evidence bundles" in response.text
    token = url.split("?token=", 1)[1]
    assert f'value="{token}"' in response.text  # launching works from this page


def test_python_m_workbench_ui_serves_with_tests_e2e_on_pythonpath(tmp_path: Path) -> None:
    port = _free_port()
    out = str(tmp_path / "wb")
    argv = [sys.executable, "-m", "workbench.ui", "--out", out, "--port", str(port), "--no-open"]
    with _serving(argv, _env(PYTHONPATH="tests/e2e"), port) as url:
        _assert_serves_the_index(url)
    assert _port_is_free(port)


def test_without_tests_e2e_on_pythonpath_the_module_is_not_found(tmp_path: Path) -> None:
    # WHY the recipe sets PYTHONPATH: no sys.path trick inside the package can help here.
    done = subprocess.run(
        [sys.executable, "-m", "workbench.ui", "--help"],
        cwd=entry.PACKAGE_DIR,
        env=_env(),
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0
    assert "No module named 'workbench'" in done.stderr


@pytest.mark.skipif(shutil.which("just") is None, reason="`just` not on PATH")
@pytest.mark.parametrize(
    ("prefix", "cwd"),
    [((), entry.PACKAGE_DIR), (("screamingface",), entry.PACKAGE_DIR.parents[1])],
    ids=["from-the-package", "from-the-repo-root"],
)
def test_just_workbench_ui_serves_the_page(
    tmp_path: Path, prefix: tuple[str, ...], cwd: Path
) -> None:
    port = _free_port()
    out = tmp_path / "wb"
    argv = ["just", *prefix, "workbench-ui", str(out), "--port", str(port), "--no-open"]
    with _serving(argv, _env(), port, cwd=cwd) as url:
        _assert_serves_the_index(url)
    assert _port_is_free(port)
    assert out.is_dir()  # `out` reached --out
