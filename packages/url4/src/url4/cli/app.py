"""Command-line entry point for the url4 node server (``url4`` console script).

``url4 serve`` stands up the engine as an HTTP node (assembly in :mod:`url4.cli._serve`);
``url4 eval`` evaluates one expression network-free. This module is kept free of any
web framework at import time so ``url4 --version`` and ``url4 eval`` work on the base
install — uvicorn (the ``url4[server]`` extra) is imported only when serving, and the
serve assembly (:mod:`url4.cli._serve`) is imported lazily inside :func:`_run_serve`.

# STORY: as an operator, I run `url4 serve` to expose the url4 engine over HTTP with my
# own [commands] backends (my gateway script is just another command), and
# `url4 eval '<expr>'` to sanity-check an expression with no backend.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from url4 import __version__
from url4.cli._config import SERVE_DEFAULTS
from url4.core.errors import Url4Error

# INVARIANT: only genuine loopback addresses belong here — a host in this set skips
# the exposure warnings. "" is NOT loopback: it binds 0.0.0.0 AND :: (every
# interface). ServeConfig.validate() rejects it before we get here; this set must not
# re-admit it.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

_SERVE_FIELDS = (
    "host",
    "port",
    "default_route",
    "eval_path",
    "concurrency",
    "max_inflight",
    "timeout",
)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch. Returns the process exit code (0/1/2)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "eval":
        return _run_eval(args)
    return _run_serve(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="url4", description="Run or query a url4 node.")
    parser.add_argument("--version", action="version", version=f"url4 {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_serve_parser(sub)
    _add_eval_parser(sub)
    return parser


def _add_serve_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("serve", help="run the node as an HTTP server (foreground)")
    parser.add_argument("--host", help=f"bind address (default {SERVE_DEFAULTS.host})")
    parser.add_argument("--port", type=int, help=f"bind port (default {SERVE_DEFAULTS.port})")
    parser.add_argument(
        "--default-route",
        dest="default_route",
        help="reduce route (default: first declared [commands] route); must be a declared command",
    )
    parser.add_argument(
        "--eval-path",
        dest="eval_path",
        help=f"eval endpoint path (default {SERVE_DEFAULTS.eval_path})",
    )
    parser.add_argument(
        "--concurrency", type=int, help=f"run-wide I/O cap (default {SERVE_DEFAULTS.concurrency})"
    )
    parser.add_argument(
        "--max-inflight",
        dest="max_inflight",
        type=int,
        help=f"max concurrent evals (default {SERVE_DEFAULTS.max_inflight})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help=f"per-request timeout seconds (default {SERVE_DEFAULTS.timeout:g})",
    )
    parser.add_argument("--config", help="url4.toml path (default ./url4.toml if present)")


def _add_eval_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("eval", help="evaluate one expression network-free (no backend)")
    parser.add_argument("expression", nargs="?", help="url4 expression; omit to read from stdin")


# --- eval ------------------------------------------------------------------------


def _run_eval(args: argparse.Namespace) -> int:
    expression = (args.expression if args.expression is not None else sys.stdin.read()).strip()
    if not expression:
        print("url4 eval: no expression (pass an argument or pipe one on stdin)", file=sys.stderr)
        return 2
    from url4 import StaticIOLayer, evaluate_sync

    try:
        result = evaluate_sync(expression, StaticIOLayer())
    except Url4Error as exc:
        print(f"url4 eval: {exc}", file=sys.stderr)
        return 1
    print(result.text)
    return 0


# --- serve -----------------------------------------------------------------------


def _run_serve(args: argparse.Namespace) -> int:
    from url4.cli import _serve  # lazy: keeps httpx/subprocess assembly off the base import path

    try:
        config = _serve.resolve(_overrides(args), os.environ, _config_path(args))
        config.validate()
    except _serve.ConfigError as exc:
        print(f"url4 serve: {exc}", file=sys.stderr)
        return 2
    _warn_exposure(config)
    node = _serve.build_node(config)
    app = _serve.build_asgi_app(node, config)
    print(
        f"url4 serve: listening on http://{config.host}:{config.port} "
        f"(eval {config.eval_path}?q=…)",
        file=sys.stderr,
    )
    return _serve_forever(app, config.host, config.port)


def _overrides(args: argparse.Namespace) -> dict[str, object]:
    return {name: getattr(args, name) for name in _SERVE_FIELDS}


def _config_path(args: argparse.Namespace) -> Path | None:
    # URL4_CONFIG picks the file the other settings come from, so it is read here,
    # before resolve(); it is not a ServeConfig field. An empty value is unset, as in _pick.
    explicit = args.config or os.environ.get("URL4_CONFIG")
    if explicit:
        return Path(explicit)
    default = Path("url4.toml")
    return default if default.is_file() else None


def _warn_exposure(config) -> None:
    if config.host in _LOOPBACK:
        return
    print(
        f"url4 serve: WARNING binding non-loopback host {config.host!r} — the eval endpoint "
        "evaluates arbitrary url4 and fetches arbitrary URLs.",
        file=sys.stderr,
    )
    if config.commands:
        print(
            "url4 serve: WARNING command routes are enabled and now remotely reachable — "
            f"they run local subprocesses: {sorted(config.commands)}",
            file=sys.stderr,
        )


def _serve_forever(app, host: str, port: int) -> int:
    # WHY: importlib (not a static `import uvicorn`) so the optional extra stays
    # truly optional — the type checker doesn't demand it and the missing-extra
    # branch is exercisable in an env without it (mirrors Url4Node.serve).
    try:
        uvicorn = importlib.import_module("uvicorn")
    except ModuleNotFoundError:
        print(
            "url4 serve: uvicorn is required — install with: pip install 'url4[server]'",
            file=sys.stderr,
        )
        return 2
    uvicorn.run(app, host=host, port=port)  # pragma: no cover - needs the extra + a real bind
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
