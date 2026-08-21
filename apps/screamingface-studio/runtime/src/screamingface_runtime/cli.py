"""Console entry point for the local desktop runtime."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from screamingface_runtime.runtime import RuntimeConfig, run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screamingface-runtime",
        description="Run the local AI Gateway, Scoreboard, and ScreamingFace Engine.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "SCREAMINGFACE_RUNTIME_DATA_DIR",
                Path.home() / ".screamingface-studio",
            )
        ),
        help="Writable directory for the SQLite database and persistent runtime data.",
    )
    parser.add_argument(
        "--scoreboard-child", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--scoreboard-port", type=int, default=9106, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--runner-config",
        type=Path,
        default=None,
        help="URL4 runner configuration. Defaults to the copy embedded in this runtime.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.scoreboard_child:
            from screamingface._runtime.server import run_scoreboard

            run_scoreboard(
                RuntimeConfig(
                    data_dir=args.data_dir, scoreboard_port=args.scoreboard_port
                )
            )
            return
        asyncio.run(
            run(
                RuntimeConfig(
                    data_dir=args.data_dir,
                    runner_config=args.runner_config,
                )
            )
        )
    except Exception as exc:
        print(f"SCREAMINGFACE_RUNTIME_ERROR {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
