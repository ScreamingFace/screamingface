"""Export-verified deletion for the exceptional private-board rollback path (OME-1027).

This is intentionally a database-only operator command, not an HTTP endpoint. It removes one
exact private benchmark only after the rows still in the database hash to the operator's saved
JSONL export. The lock, comparison, and deletes share one transaction, so a mismatch or failure
leaves every row intact.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import re
from collections.abc import Sequence

from tortoise import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from .config import Settings
from .db import close_db, init_db
from .export_private_submissions import format_jsonl
from .scores.models import Baseline, Benchmark, Score
from .scores.schemas import ScoreSchema
from .scores.store import ScoreStore

_SHA256 = re.compile(r"[0-9a-f]{64}")


class PurgeRefused(RuntimeError):
    """The requested purge did not satisfy every fail-closed precondition."""


def export_sha256(rows: Sequence[ScoreSchema]) -> str:
    """SHA-256 of the exact bytes emitted by ``export_private_submissions``.

    The exporter uses ``print`` for a non-empty result, which adds one trailing newline. An empty
    export prints nothing and therefore hashes as zero bytes.
    """
    output = format_jsonl(rows)
    payload = f"{output}\n".encode() if output else b""
    return hashlib.sha256(payload).hexdigest()


def _validated_digest(value: str) -> str:
    digest = value.strip().lower()
    if _SHA256.fullmatch(digest) is None:
        raise PurgeRefused("expected export sha256 must be exactly 64 hexadecimal characters")
    return digest


async def _delete_benchmark(connection: BaseDBAsyncClient, benchmark_id: str) -> None:
    """Delete and verify the one locked benchmark; split out for rollback-path testing."""
    deleted = await Benchmark.filter(id=benchmark_id).using_db(connection).delete()
    if deleted != 1:
        raise PurgeRefused(
            f"expected to delete exactly one private benchmark {benchmark_id!r}; deleted {deleted}"
        )
    if await Benchmark.filter(id=benchmark_id).using_db(connection).exists():
        raise PurgeRefused(f"benchmark {benchmark_id!r} still exists after deletion")


async def _revalidate_visibility_for_purge(
    connection: BaseDBAsyncClient,
    benchmark_id: str,
) -> None:
    """Lock the named board and prove it is private immediately before digesting it."""
    benchmark = await (
        Benchmark.filter(id=benchmark_id).using_db(connection).select_for_update().first()
    )
    if benchmark is None:
        raise LookupError(f"unknown benchmark_id: {benchmark_id!r}")
    if benchmark.visibility != "private":
        raise PurgeRefused(f"benchmark {benchmark_id!r} is not private")


async def purge_private_benchmark(
    benchmark_id: str,
    expected_export_sha256: str,
    *,
    confirmed: bool,
) -> str:
    """Verify one private board against its export, and optionally delete it atomically."""
    expected_digest = _validated_digest(expected_export_sha256)

    async with in_transaction() as connection:
        # ScoreStore.submit() takes the same row lock before inserting. Once this lock is held,
        # the digest cannot become stale between comparison and deletion on PostgreSQL.
        await _revalidate_visibility_for_purge(connection, benchmark_id)

        baseline_count = await (
            Baseline.filter(benchmark_id=benchmark_id).using_db(connection).count()
        )
        if baseline_count:
            noun = "baseline" if baseline_count == 1 else "baselines"
            raise PurgeRefused(
                f"benchmark {benchmark_id!r} has {baseline_count} {noun}; nothing was purged"
            )

        rows = await ScoreStore().list_all_for_benchmark(benchmark_id, using_db=connection)
        actual_digest = export_sha256(rows)
        if not hmac.compare_digest(actual_digest, expected_digest):
            raise PurgeRefused(
                f"database sha256 {actual_digest} does not match saved export sha256 "
                f"{expected_digest}; nothing was purged"
            )

        submission_count = len(rows)
        if not confirmed:
            return (
                f"would purge {benchmark_id!r}: {submission_count} submissions match export "
                f"sha256 {actual_digest}; re-run with --yes to delete"
            )

        # Tortoise's delete count includes database-cascaded IdempotencyKey rows on SQLite, so it
        # cannot be compared to the Score count. Verify the exact filtered set is empty instead.
        await Score.filter(benchmark_id=benchmark_id).using_db(connection).delete()
        if await Score.filter(benchmark_id=benchmark_id).using_db(connection).exists():
            raise PurgeRefused(f"submissions remain on benchmark {benchmark_id!r} after deletion")

        await _delete_benchmark(connection, benchmark_id)

    return (
        f"purged {benchmark_id!r}: {submission_count} submissions matched export sha256 "
        f"{actual_digest}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one private benchmark against a saved JSONL export, then optionally purge it."
        ),
    )
    parser.add_argument("--benchmark", required=True, help="Exact private benchmark id to purge.")
    parser.add_argument(
        "--expected-export-sha256",
        required=True,
        help="SHA-256 of the file emitted by export_private_submissions.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Delete after verification. Without this flag the command is a dry run.",
    )
    return parser


async def _run(benchmark_id: str, expected_export_sha256: str, *, confirmed: bool) -> str:
    settings = Settings()
    await init_db(settings.database_url)
    try:
        return await purge_private_benchmark(
            benchmark_id,
            expected_export_sha256,
            confirmed=confirmed,
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
                args.expected_export_sha256,
                confirmed=args.yes,
            )
        )
    except (LookupError, PurgeRefused) as exc:
        parser.error(str(exc))
    else:
        print(outcome)


if __name__ == "__main__":
    main()
