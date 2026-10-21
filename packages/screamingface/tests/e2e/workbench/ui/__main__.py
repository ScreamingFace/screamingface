"""``python -m workbench.ui``: serve the workbench UI on 127.0.0.1 (unit 4 plan, Task 5).

Prints the one URL that can launch runs (it carries a fresh per-launch token) and serves until
Ctrl-C; an active run is cancelled on the way out, since it lives in its own session.

Run from ``packages/screamingface`` with ``tests/e2e`` on ``PYTHONPATH`` (the ``just
workbench-ui`` recipe does both): runs spawn ``pytest tests/e2e/workbench/test_notebooks.py``
relative to the package, and read ``OPENROUTER_API_KEY`` from this process's environment only.
"""

from __future__ import annotations

import argparse
import os
import secrets
import threading
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
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


def notebook_stems() -> list[str]:
    return sorted(p.stem for p in NOTEBOOK_DIR.glob("*.ipynb"))


def main(argv: Sequence[str] | None = None, *, serve: Serve = uvicorn.run) -> None:
    args = _parser().parse_args(argv)
    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    manager = RunManager(root, workdir=PACKAGE_DIR, environ=os.environ)
    app = create_app(
        root=root, manager=manager, token=token, port=args.port, notebooks=notebook_stems()
    )
    url = f"http://{HOST}:{args.port}/?token={token}"
    print(f"e2e workbench UI: bundles under {root}")
    print("Open this URL (it carries the launch token; keep it to yourself):")
    print(url, flush=True)
    if args.open:
        threading.Timer(_OPEN_DELAY_S, webbrowser.open, (url,)).start()
    # WHY a graceful-shutdown timeout: an open event stream never finishes on its own, and the
    # lifespan shutdown that cancels the active run only runs once connections are closed.
    serve(app, host=HOST, port=args.port, log_level="warning", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
