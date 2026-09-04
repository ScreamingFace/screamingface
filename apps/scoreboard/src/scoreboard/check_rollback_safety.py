"""Refuse a rollback that would publish a private board (OME-894).

FEATURE: OME-894 — a private board hides participants' submissions from each other. That privacy
lives in CODE that reads ``Benchmark.visibility``; the database only stores the column. Roll the
code back below the release that introduced the feature and the column survives untouched while
nothing reads it, so every private submission is served to anyone who asks.

WHY a preflight rather than a Helm hook: ``helm rollback`` executes the TARGET revision's hooks
(``execHook(targetRelease, release.HookPreRollback, ...)`` in Helm's ``pkg/action/rollback.go``).
The revision being rolled back TO is a pre-privacy one, and its stored manifest contains no such
hook, so no hook added to this chart can ever run in the dangerous direction. The chart cannot
guard this; an operator step can.

INVARIANT: read-only, and it never mutates ``visibility`` to make itself pass. Flipping a board to
public in order to clear the refusal is the leak, performed deliberately.

AIDEV-NOTE: the fail-closed procedure this points at lives in ``DEPLOYMENT.md`` under "Private
boards and rollback". Keep the two in step — this module is what operators run, that section is
what they do next.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from .config import Settings
from .db import close_db, init_db
from .scores.models import Benchmark, Score

DEPLOYMENT_DOC = 'apps/scoreboard/DEPLOYMENT.md ("Private boards and rollback")'


@dataclass(frozen=True)
class PrivateBoard:
    benchmark_id: str
    display_name: str
    submissions: int


def running_version() -> str:
    """The package version doing the reporting, for diagnostics only.

    INVARIANT (OME-1027): this value is NOT a rollback floor. Both the base image that ignores
    ``Benchmark.visibility`` and the privacy-aware release package scoreboard 0.1.1. Only the
    recorded Helm revision plus the immutable runtime image digest identify a safe target.
    """
    try:
        return version("scoreboard")
    except PackageNotFoundError:  # pragma: no cover - only when run from an unbuilt tree
        return "unknown"


async def private_boards() -> list[PrivateBoard]:
    """Every private benchmark, with how many submissions a rollback would publish."""
    boards = await Benchmark.filter(visibility="private").order_by("id")
    return [
        PrivateBoard(
            benchmark_id=board.id,
            display_name=board.display_name,
            submissions=await Score.filter(benchmark_id=board.id).count(),
        )
        for board in boards
    ]


def format_verdict(boards: Sequence[PrivateBoard], *, running_version: str) -> str:
    if not boards:
        return (
            "SAFE: no benchmark is private, so a rollback cannot publish anything that is not "
            "already public."
        )

    noun = "benchmark" if len(boards) == 1 else "benchmarks"
    lines = [
        f"REFUSED: {len(boards)} private {noun} would be published by a rollback to "
        "privacy-blind code.",
        "",
    ]
    width = max(len(board.benchmark_id) for board in boards)
    for board in boards:
        lines.append(
            f"  {board.benchmark_id.ljust(width)}  {board.submissions} submissions"
            f"  ({board.display_name})"
        )
    lines += [
        "",
        f"Package version: {running_version} (diagnostic only; not a rollback floor).",
        "This code reads `Benchmark.visibility`, but package semver does not identify the release "
        "that introduced that behavior. A rollback leaves `visibility=private` in the database "
        "and may restore code that serves every row unscoped.",
        "",
        "Record and compare the Helm revision and immutable image digest before rollback.",
        "",
        f"Run the fail-closed procedure in {DEPLOYMENT_DOC} first.",
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Refuse a rollback that would publish a private board. Exits non-zero while any "
            "benchmark is private."
        ),
    )


async def _run() -> tuple[str, int]:
    settings = Settings()
    await init_db(settings.database_url)
    try:
        boards = await private_boards()
    finally:
        await close_db()
    return format_verdict(boards, running_version=running_version()), 0 if not boards else 1


def main(argv: Sequence[str] | None = None) -> None:
    _build_parser().parse_args(argv)
    verdict, code = asyncio.run(_run())
    print(verdict)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
