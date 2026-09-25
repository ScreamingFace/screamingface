"""Permanently delete named scores from a public board.

FEATURE: OME-1385, for OME-1384 — the dev `draco-3pass` board holds scores that publish a cached
run's spend (`0.000000`) as a priced cost. They cannot be corrected in place: a faithful rerun
dedups to the stored row, and a replay never refills an amount that is present. The owner decided
to delete them and rerun uncached. There is no delete route and no SQL access; an operator module
run inside the pod is how `retire_benchmark` removed benchmarks (OME-986).

INVARIANT: this is an irreversible DELETE. Nothing is written without `--yes`, and nothing is
written unless the selection matches EXACTLY the count the operator passed as `--expect`. The
count is their statement of what they reviewed; a filter that matches more is the mistake that
matters.

INVARIANT: the backup is taken BEFORE anything is deleted, and the delete is bound to it. The dry
run writes the backup to STDOUT (a file inside the pod is lost with the pod) and its SHA-256 to
stderr. `--yes` requires that digest as `--expect-sha256`, recomputes the selected rows' JSONL
inside the deleting transaction, and refuses unless the two match. So the rows can only be deleted
once a backup of exactly those rows is already on the operator's disk, and a row that changed
since the review is not deleted unseen. The confirmed run writes nothing to stdout.

WHY (review round 1, 2026-09-26): the first version deleted, committed, and only then wrote the
backup. A dropped `kubectl exec`, a full disk or a failed write in that window lost the rows and
the backup together, and the runbook's second `> backup.jsonl` truncated the reviewed file before
the command even started. This mirrors `purge_private_benchmark`, which is gated the same way.

The backup is the `export_private_submissions` JSONL, one format for "every field of a score". It
is evidence, not a restore file: it carries no `content_hash` or idempotency keys, and recreating
a score means resubmitting it.

AIDEV-NOTE: private boards are refused. They have their own export-verified purge
(`purge_private_benchmark`, OME-1027), and this must not become a way around it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import re
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tortoise import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from .config import Settings
from .db import close_db, init_db
from .export_private_submissions import format_jsonl_bytes
from .scores.models import Score
from .scores.schemas import ScoreSchema
from .scores.store import ScoreStore, _score_to_schema

_SHA256 = re.compile(r"[0-9a-f]{64}")


class DeletionRefused(RuntimeError):
    """The selection did not satisfy every precondition, so nothing was deleted."""


@dataclass(frozen=True)
class Deletion:
    """What a call selected, and whether it deleted it."""

    benchmark_id: str
    rows: tuple[ScoreSchema, ...]
    deleted: bool

    def backup(self) -> bytes:
        return format_jsonl_bytes(self.rows)

    def sha256(self) -> str:
        """The digest `--expect-sha256` must repeat: of exactly the bytes `backup()` returns."""
        return hashlib.sha256(self.backup()).hexdigest()

    def describe(self) -> str:
        count = len(self.rows)
        noun = f"score{'s' if count != 1 else ''}"
        if self.deleted:
            return f"deleted {count} {noun} from {self.benchmark_id!r}"
        return (
            f"would delete {count} {noun} from {self.benchmark_id!r}. Backup sha256 "
            f"{self.sha256()}. Keep the backup, then re-run with --yes --expect-sha256 "
            f"{self.sha256()}."
        )


def _validated_digest(expected_sha256: str | None, *, confirmed: bool) -> str | None:
    if expected_sha256 is None:
        if confirmed:
            raise ValueError(
                "confirming needs expected_sha256 (--expect-sha256): the digest the dry run "
                "printed for the backup you kept"
            )
        return None
    digest = expected_sha256.strip().lower()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError("expected_sha256 must be exactly 64 hexadecimal characters")
    return digest


def _validate_selection(
    score_ids: Sequence[uuid.UUID] | None,
    submitted_before: datetime | None,
    expected: int,
) -> None:
    if (score_ids is None) == (submitted_before is None):
        raise ValueError("select with exactly one of score ids or a submitted-before cutoff")
    if submitted_before is not None and submitted_before.utcoffset() is None:
        # WHY refuse rather than assume UTC: a naive cutoff is a different instant on every host,
        # and the rows either side of it are the ones being destroyed.
        raise ValueError("the submitted-before cutoff must carry a timezone")
    if expected < 1:
        raise ValueError("expected must be at least 1: deleting nothing is never the intent")


async def _revalidate_visibility_for_delete(
    connection: BaseDBAsyncClient, benchmark_id: str
) -> None:
    """Lock the named board and prove it is public, inside the deleting transaction.

    Mirrors `purge_private_benchmark._revalidate_visibility_for_purge`, the opposite check, and
    shares its locking query rather than building a second one.
    """
    benchmark = (
        await ScoreStore().visibility_query(benchmark_id, connection=connection, lock=True).first()
    )
    if benchmark is None:
        raise LookupError(f"unknown benchmark_id: {benchmark_id!r}")
    if benchmark.visibility == "private":
        raise DeletionRefused(
            f"refusing to delete from {benchmark_id!r}: it is a private board. Use "
            "scoreboard.purge_private_benchmark, which verifies an export first."
        )


async def _delete_rows(connection: BaseDBAsyncClient, score_ids: list[uuid.UUID]) -> int:
    """Delete by exact id and return how many of those SCORES are gone.

    Split out so the rollback path is testable.

    WHY not the count `delete()` returns: it is not a score count. On SQLite it came back as 4 for
    2 scores, because it includes the idempotency keys removed by `ON DELETE CASCADE`
    (models/idempotency_key.py), and that is backend-specific. Counting what is left of the
    selection means the same thing on every backend.
    """
    await Score.filter(id__in=score_ids).using_db(connection).delete()
    remaining = await Score.filter(id__in=score_ids).using_db(connection).count()
    return len(score_ids) - remaining


async def delete_scores(
    benchmark_id: str,
    *,
    score_ids: Sequence[uuid.UUID] | None = None,
    submitted_before: datetime | None = None,
    expected: int,
    confirmed: bool = False,
    expected_sha256: str | None = None,
) -> Deletion:
    """Select scores on one public board, and delete them only when ``confirmed``.

    Raises ``LookupError`` for an unregistered benchmark: "nothing matched" and "you typed the id
    wrong" must not look identical to someone cleaning up a live board.

    Raises ``DeletionRefused`` for a private board, or when the selection does not match
    ``expected``. Every row survives a refusal.

    INVARIANT: selection, count check and delete share ONE transaction. A row landing between the
    read and the write cannot be deleted unseen, and a delete that removes fewer rows than were
    selected rolls back rather than leaving half of it done.

    INVARIANT (OME-894): the public-board check is taken INSIDE that transaction, with the
    benchmark row locked, and before anything else. Read before it, a board flipped private in
    between would have its rows deleted without the export proof `purge_private_benchmark`
    demands. `tests/unit/guards/test_visibility_exit_guard.py` enforces this for every exit.
    """
    _validate_selection(score_ids, submitted_before, expected)
    reviewed = _validated_digest(expected_sha256, confirmed=confirmed)

    async with in_transaction() as connection:
        await _revalidate_visibility_for_delete(connection, benchmark_id)

        query = Score.filter(benchmark_id=benchmark_id).using_db(connection)
        if score_ids is not None:
            query = query.filter(id__in=list(score_ids))
        else:
            query = query.filter(submitted_at__lt=submitted_before)
        selected = await query.order_by("submitted_at", "id")

        if len(selected) != expected:
            raise DeletionRefused(
                f"refusing to delete from {benchmark_id!r}: the selection matched "
                f"{len(selected)} scores, not the {expected} expected. Nothing was deleted."
            )
        selection = Deletion(benchmark_id, tuple(_score_to_schema(m) for m in selected), False)
        if not confirmed:
            return selection
        # INVARIANT: bound to the reviewed backup, inside the transaction that deletes.
        assert reviewed is not None
        if not hmac.compare_digest(selection.sha256(), reviewed):
            raise DeletionRefused(
                f"refusing to delete from {benchmark_id!r}: the selection changed since the "
                "reviewed backup (its sha256 no longer matches). Nothing was deleted; run the "
                "dry run again and review the new backup."
            )

        deleted = await _delete_rows(connection, [model.id for model in selected])
        if deleted != expected:
            # Raising inside the transaction is what rolls back the rows that did go.
            raise DeletionRefused(
                f"refusing to report a delete from {benchmark_id!r}: deleted {deleted} of "
                f"{expected}. The scores changed while this ran; nothing was kept deleted."
            )
    return Deletion(benchmark_id, selection.rows, deleted=True)


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 timestamp: {value!r}") from exc
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} has no timezone; add one, e.g. {value}T00:00:00Z"
        )
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Permanently delete named scores from a public board. The backup JSONL goes to "
            "stdout; redirect it to a file."
        ),
    )
    parser.add_argument("--benchmark", required=True, help="Benchmark id to delete from.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--id",
        dest="score_ids",
        action="append",
        type=uuid.UUID,
        help="A score id to delete. Repeat for each score.",
    )
    selector.add_argument(
        "--submitted-before",
        type=_aware_datetime,
        help="Delete every score on the board submitted before this ISO 8601 instant.",
    )
    parser.add_argument(
        "--expect",
        type=int,
        required=True,
        help="How many scores the selection must match. Anything else deletes nothing.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without it, write the backup and change nothing.",
    )
    parser.add_argument(
        "--expect-sha256",
        help=(
            "Required with --yes: the backup digest the dry run printed. The delete is refused "
            "unless the selection still hashes to it."
        ),
    )
    return parser


async def _run(args: argparse.Namespace) -> Deletion:
    # Database lifecycle only; the decision lives in delete_scores so there is ONE copy of it.
    settings = Settings()
    await init_db(settings.database_url)
    try:
        return await delete_scores(
            args.benchmark,
            score_ids=args.score_ids,
            submitted_before=args.submitted_before,
            expected=args.expect,
            confirmed=args.yes,
            expected_sha256=args.expect_sha256,
        )
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        outcome = asyncio.run(_run(args))
    except (LookupError, ValueError, DeletionRefused) as exc:
        parser.error(str(exc))
    # INVARIANT: only the dry run writes stdout, and it is the backup and nothing else. The
    # confirmed run has already been bound to a backup on the operator's disk; writing here
    # would only invite a second `> backup.jsonl` that truncates the reviewed one.
    if not outcome.deleted:
        sys.stdout.write(outcome.backup().decode())
        sys.stdout.flush()
    print(outcome.describe(), file=sys.stderr)


if __name__ == "__main__":
    main()
