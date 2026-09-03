"""Read every submission on a benchmark, for staff reviewing a private challenge.

FEATURE: OME-894 — a private board hides participants' submissions from each other. Staff still
have to review the challenge, and the owner decision was deliberately NOT to build an admin API:
there is then nothing to secure, guess, or accidentally expose, and for a challenge reviewed by a
handful of people a script is cheaper than a protected surface.

WHY this is the only way in, not merely a convenience: the API fails closed when
``auth_mode`` is ``disabled``, which is the shipped chart default. This module reads the database
and never consults ``auth_mode``, so it works regardless of how the deployment is configured.

INVARIANT: read-only. It issues no writes, so it cannot be the thing that corrupts a challenge
someone is in the middle of.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from .config import Settings
from .db import close_db, init_db
from .scores.models import Benchmark
from .scores.schemas import ScoreSchema
from .scores.store import ScoreStore


async def collect_submissions(benchmark_id: str) -> list[ScoreSchema]:
    """Every submission for ``benchmark_id``, oldest first, unscoped by any identity.

    Raises ``LookupError`` for an unregistered benchmark rather than returning nothing: "no
    submissions yet" and "you typed the id wrong" must not look identical to someone reviewing a
    challenge.
    """
    if not await Benchmark.exists(id=benchmark_id):
        raise LookupError(f"unknown benchmark_id: {benchmark_id!r}")
    return await ScoreStore().list_all_for_benchmark(benchmark_id)


def format_jsonl(rows: Sequence[ScoreSchema]) -> str:
    """One JSON object per line, with the submitter's FULL address.

    INVARIANT: dumped in PYTHON mode, then serialised here. The public API publishes only the
    local part of an address (OME-834) through a `when_used="json"` serializer, so
    `model_dump_json()` would silently trim the domain — exactly the field this export exists to
    provide. Staff need it to know which verified identity produced a score, and to reach the
    person.
    """
    lines = []
    for row in rows:
        payload: dict[str, Any] = row.model_dump(mode="python")
        lines.append(json.dumps(payload, default=str, sort_keys=True))
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export every submission on a benchmark, including private boards.",
    )
    parser.add_argument(
        "--benchmark",
        required=True,
        help="Benchmark id to export, e.g. healthbench-worst30.",
    )
    return parser


async def _run(benchmark_id: str) -> str:
    settings = Settings()
    await init_db(settings.database_url)
    try:
        return format_jsonl(await collect_submissions(benchmark_id))
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        output = asyncio.run(_run(args.benchmark))
    except LookupError as exc:
        parser.error(str(exc))
    else:
        if output:
            print(output)


if __name__ == "__main__":
    main()
