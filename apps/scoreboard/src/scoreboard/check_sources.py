"""Operator-only, board-scoped external source availability checks."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx

from .config import Settings
from .db import close_db, init_db
from .scores.models import Baseline, Benchmark
from .scores.source_health import record_check
from .source_probe import PublicSourceTransport, probe_source


async def check_board_sources(benchmark_id: str, client: httpx.AsyncClient) -> dict[str, int]:
    if not await Benchmark.filter(id=benchmark_id).exists():
        raise ValueError("unknown benchmark")
    urls = await Baseline.filter(benchmark_id=benchmark_id).distinct().values("source_url")
    summary = {"checked": 0, "available": 0, "unchecked": 0}
    for url in sorted(row["source_url"] for row in urls if row["source_url"]):
        started_at = datetime.now(UTC)
        available = await probe_source(url, client)
        await record_check(url, available=available, checked_at=started_at)
        summary["checked"] += 1
        summary["available" if available else "unchecked"] += 1
    return summary


async def _run(benchmark_id: str) -> dict[str, int]:
    await init_db(Settings().database_url)
    try:
        async with httpx.AsyncClient(
            transport=PublicSourceTransport(),
            trust_env=False,
            headers={"User-Agent": "ScreamingFace-SourceCheck/1.0"},
        ) as client:
            return await check_board_sources(benchmark_id, client)
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check public source links for one leaderboard.")
    parser.add_argument("--benchmark-id", required=True)
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(_run(args.benchmark_id))
    except ValueError as exc:
        parser.error(str(exc))
    else:
        print(
            f"Checked {summary['checked']}: {summary['available']} available, "
            f"{summary['unchecked']} unchecked"
        )


if __name__ == "__main__":
    main()
