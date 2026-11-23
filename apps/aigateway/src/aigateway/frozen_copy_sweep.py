"""The operator command of the frozen copy sweep (OME-1947, contracts K6).

Run it as `python -m aigateway.frozen_copy_sweep`. It has three modes:
- no argument: a dry run at the database time. It changes nothing.
- `--cutoff <ISO time with zone>`: a dry run at that time. A future time is allowed.
- `--run [--max-entries N]`: one full pass, the same code as a periodic run.

Exit status: 0 done; 2 bad arguments; 1 a failure during the run (changes before the failure stay).
The dry-run JSON holds account names, so it goes to the operator terminal only.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from collections.abc import Sequence
from datetime import datetime

from .config import Settings
from .core.frozen_copy.sweep import build_frozen_copy_sweep
from .db import close_db, init_db


def _aware_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO time: {value!r}") from None
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "the time needs a zone, for example 2026-12-01T00:00:00+00:00"
        )
    return parsed


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aigateway.frozen_copy_sweep",
        description="Dry-run or run the frozen copy retention sweep.",
    )
    parser.add_argument(
        "--cutoff",
        type=_aware_time,
        help="dry run at this ISO time with a zone (a future time is allowed)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="run one full sweep pass now, as the periodic trigger does",
    )
    parser.add_argument(
        "--max-entries",
        type=_positive_int,
        dest="max_entries",
        help="most entries this pass deletes (only with --run)",
    )
    return parser


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.run and args.cutoff is not None:
        parser.error("--run cannot be used with --cutoff")
    if args.max_entries is not None and not args.run:
        parser.error("--max-entries needs --run")
    return args


async def _amain(args: argparse.Namespace, settings: Settings) -> None:
    await init_db(settings.database_url.get_secret_value())
    try:
        sweep = build_frozen_copy_sweep(settings)
        if args.run:
            report = await sweep.run_pass(trigger="command", max_entries=args.max_entries)
            print(json.dumps(dataclasses.asdict(report)))
        else:
            print(json.dumps(await sweep.dry_run(args.cutoff)))
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = Settings()
        asyncio.run(_amain(args, settings))
    except Exception as exc:
        # WHY only the type: an exception message can carry a secret or an account name.
        print(f"frozen copy sweep failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
