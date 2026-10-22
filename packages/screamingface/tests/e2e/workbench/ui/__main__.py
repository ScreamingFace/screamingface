"""``python -m workbench.ui``: serve the workbench UI on 127.0.0.1 (unit 4 plan, Task 5).

Prints the one URL that can launch runs (it carries a fresh per-launch token) and serves until
Ctrl-C, SIGTERM or SIGHUP. An active run lives in its own session, so no signal to the UI
reaches it: it is cancelled on the way out (``_stopping_runs``), so a paid ``local`` run never
keeps spending after the UI is gone.

Run from ``packages/screamingface`` with ``tests/e2e`` on ``PYTHONPATH`` (the ``just
workbench-ui`` recipe does both): runs spawn ``pytest tests/e2e/workbench/test_notebooks.py``
relative to the package, and read ``OPENROUTER_API_KEY`` from this process's environment only.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import threading
import webbrowser
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any

import uvicorn

from workbench.build_notebooks import NOTEBOOK_DIR
from workbench.ui.app import create_app
from workbench.ui.runs import RunManager

HOST = "127.0.0.1"
DEFAULT_PORT = 9112
# ui/__main__.py -> ui, workbench, e2e, tests, packages/screamingface
PACKAGE_DIR = Path(__file__).resolve().parents[4]
_OPEN_DELAY_S = 1.0  # let uvicorn bind before the browser asks

Serve = Callable[..., Any]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workbench.ui", description="e2e workbench UI: bundle viewer + launcher"
    )
    parser.add_argument(
        "--out", default="./workbench-out", help="bundle root (runs go under runs/)"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="loopback port")
    parser.add_argument(
        "--open", action=argparse.BooleanOptionalAction, default=True, help="open a browser"
    )
    return parser


_EXIT_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@contextmanager
def _stopping_runs(manager: RunManager) -> Iterator[None]:
    """Stop the active run however the server ends, then restore the signal handlers.

    The lifespan hook (``app.create_app``) cancels the run on a normal shutdown. It is skipped
    when uvicorn force-exits (a second Ctrl-C), so the run is cancelled here as well; that is a
    no-op when the lifespan already did it. While the UI waits for that teardown, a further
    signal kills the run's group outright instead of being lost. SIGHUP (terminal closed),
    which uvicorn does not handle, is turned into a graceful SIGTERM while serving.

    WHY these handlers stay installed under uvicorn's: uvicorn restores them after serving and
    then re-raises the signals it caught, which this handler only records (not a second
    Ctrl-C). The process still exits with 128 + the signal number. Main thread only.
    """
    received: list[int] = []
    stopping = threading.Event()

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        received.append(signum)
        if stopping.is_set():
            manager.kill_active()
        elif signum == signal.SIGHUP:
            signal.raise_signal(signal.SIGTERM)  # uvicorn's handler while serving

    previous = {sig: signal.signal(sig, on_signal) for sig in _EXIT_SIGNALS}
    try:
        yield
    finally:
        stopping.set()
        try:
            manager.shutdown()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    if received:
        raise SystemExit(128 + received[0])


def notebook_stems() -> list[str]:
    return sorted(p.stem for p in NOTEBOOK_DIR.glob("*.ipynb"))


def expected_failure_stems(directory: Path) -> frozenset[str]:
    """The notebooks that declare ``workbench.expect`` (spec §3.7): they fail on purpose.

    Only the label of the run form depends on this, so an unreadable notebook is simply not
    labelled; the verdict reads the declaration itself.
    """
    stems: set[str] = set()
    for path in directory.glob("*.ipynb"):
        try:
            meta: Any = json.loads(path.read_text(encoding="utf-8")).get("metadata", {})
            workbench: Any = meta.get("workbench", {})
            declared = isinstance(workbench, dict) and "expect" in workbench
        except (OSError, ValueError, AttributeError):
            declared = False
        if declared:
            stems.add(path.stem)
    return frozenset(stems)


def main(argv: Sequence[str] | None = None, *, serve: Serve = uvicorn.run) -> None:
    args = _parser().parse_args(argv)
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    stems = notebook_stems()
    manager = RunManager(root, workdir=PACKAGE_DIR, environ=os.environ, notebooks=stems)
    app = create_app(
        root=root,
        manager=manager,
        token=token,
        port=args.port,
        notebooks=stems,
        expected_failures=expected_failure_stems(NOTEBOOK_DIR),
    )
    url = f"http://{HOST}:{args.port}/?token={token}"
    print(f"e2e workbench UI: bundles under {root}")
    print("Open this URL (it carries the launch token; keep it to yourself):")
    print(url, flush=True)
    if args.open:
        threading.Timer(_OPEN_DELAY_S, webbrowser.open, (url,)).start()
    # WHY a graceful-shutdown timeout: an open event stream never finishes on its own, and the
    # lifespan shutdown that cancels the active run only runs once connections are closed.
    with _stopping_runs(manager):
        serve(app, host=HOST, port=args.port, log_level="warning", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
