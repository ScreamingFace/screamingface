"""Permanently delete a benchmark that nothing references.

FEATURE: OME-986 — `hle`, `livetruth` and `livetruth-latest` are leftovers from the previous SF
project and still advertised on the public catalogue. Seeding only registers and updates, so
removing them from the chart's seed list stops them being recreated and changes nothing a reader
of the board sees. This is the missing half.

INVARIANT: this is an irreversible DELETE, not a status change. "Retire" is the word the request
used and the name follows it, but nothing here is reversible and no row is kept — read that before
running it. Deletion is opt-in behind `--yes` for the same reason: every other operator module in
this app is additive (`seed`, `import_baselines`) or read-only (`export_private_submissions`), so a
correct-looking command must not destroy anything by default.

INVARIANT: a benchmark that any score or baseline references is REFUSED, and survives. Both
foreign keys are `on_delete=RESTRICT`, so the database would refuse regardless; the value added
here is naming which rows stand in the way instead of surfacing an IntegrityError at an operator.
`Score` and `Baseline` are the only two models that reference `Benchmark` — `IdempotencyKey` links
to `Score` — so counting those two is a complete check.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from tortoise.exceptions import IntegrityError

from .config import Settings
from .db import close_db, init_db
from .scores.models import Baseline, Benchmark, Score


class RetirementRefused(RuntimeError):
    """Something references the benchmark, so it was not deleted."""


@dataclass(frozen=True)
class Blockers:
    """What references a benchmark and therefore stands in the way of deleting it."""

    scores: int
    baselines: int

    def __bool__(self) -> bool:
        return bool(self.scores or self.baselines)

    def describe(self, benchmark_id: str) -> str:
        # WHY both counts in one message: an operator who clears only the blocker they were told
        # about hits the identical refusal again. Say everything in the way the first time.
        parts = []
        if self.scores:
            parts.append(f"{self.scores} score{'s' if self.scores != 1 else ''}")
        if self.baselines:
            parts.append(f"{self.baselines} baseline{'s' if self.baselines != 1 else ''}")
        return (
            f"refusing to retire {benchmark_id!r}: it still holds "
            + " and ".join(parts)
            + ". Retiring it would destroy submitted data."
        )


async def collect_blockers(benchmark_id: str) -> Blockers:
    """Count the rows that reference ``benchmark_id``."""
    return Blockers(
        scores=await Score.filter(benchmark_id=benchmark_id).count(),
        baselines=await Baseline.filter(benchmark_id=benchmark_id).count(),
    )


async def retire_benchmark(
    benchmark_id: str, *, confirmed: bool = False, include_engine_owned: bool = False
) -> str:
    """Delete ``benchmark_id`` when ``confirmed``, or explain why it was not deleted.

    Returns a line describing what happened, for the operator running it.

    Raises ``LookupError`` for an unregistered benchmark rather than returning quietly: "already
    gone" and "you typed it wrong" must not look identical to someone cleaning up a live board.

    Raises ``RetirementRefused`` when anything references it. The benchmark survives.

    INVARIANT: with ``confirmed`` false NOTHING is written. The default outcome of a
    correct-looking call is a report, because this is the one operator module here that destroys.
    """
    if not await Benchmark.exists(id=benchmark_id):
        raise LookupError(f"unknown benchmark_id: {benchmark_id!r}")

    blockers = await collect_blockers(benchmark_id)
    if blockers:
        raise RetirementRefused(blockers.describe(benchmark_id))

    benchmark = await Benchmark.get(id=benchmark_id)
    if benchmark.revision is not None and not include_engine_owned:
        # WHY refuse rather than delete: an Engine-published benchmark is re-seeded from the
        # Engine catalogue on the next deploy, so deleting it here does not achieve what the
        # operator asked for — it comes straight back. Demonstrated in review of PR #726.
        # Silently performing a deletion that undoes itself is worse than refusing.
        #
        # WHY an override rather than an absolute block: if the Engine STOPS publishing a
        # benchmark, seeding will not recreate it — but seeding never deletes either, so the row
        # is stranded and this module is the only way to remove it. A blanket refusal on a
        # non-null revision would make that legitimate case unreachable.
        raise RetirementRefused(
            f"refusing to retire {benchmark_id!r}: it carries Engine revision "
            f"{benchmark.revision!r}, so the next seed will recreate it. If the Engine no "
            "longer publishes it, pass --include-engine-owned."
        )

    if not confirmed:
        return f"would retire {benchmark_id!r}: nothing references it. Re-run with --yes."

    try:
        await Benchmark.filter(id=benchmark_id).delete()
    except IntegrityError as exc:
        # INVARIANT: a score or baseline inserted between the check above and this DELETE must
        # surface as the same readable refusal, not as the traceback this module exists to
        # replace. The RESTRICT foreign key is what raises; re-read the counts so the message
        # names what actually landed (found in review of PR #726).
        raced = await collect_blockers(benchmark_id)
        raise RetirementRefused(
            raced.describe(benchmark_id)
            if raced
            else f"refusing to retire {benchmark_id!r}: something began referencing it "
            "while this ran."
        ) from exc
    return f"retired {benchmark_id!r}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Permanently delete a benchmark that holds no scores and no baselines.",
    )
    parser.add_argument("--benchmark", required=True, help="Benchmark id to delete.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without it, report what would happen and change nothing.",
    )
    parser.add_argument(
        "--include-engine-owned",
        action="store_true",
        help=(
            "Allow retiring a benchmark that carries an Engine revision. Only correct when the "
            "Engine no longer publishes it; otherwise the next seed recreates it."
        ),
    )
    return parser


async def _run(benchmark_id: str, *, confirmed: bool, include_engine_owned: bool) -> str:
    # Database lifecycle only. The decision lives in retire_benchmark so it is testable without
    # standing up a connection, and so there is ONE copy of it.
    settings = Settings()
    await init_db(settings.database_url)
    try:
        return await retire_benchmark(
            benchmark_id, confirmed=confirmed, include_engine_owned=include_engine_owned
        )
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        outcome = asyncio.run(
            _run(
                args.benchmark,
                confirmed=args.yes,
                include_engine_owned=args.include_engine_owned,
            )
        )
    except (LookupError, RetirementRefused) as exc:
        parser.error(str(exc))
    else:
        print(outcome)


if __name__ == "__main__":
    main()
