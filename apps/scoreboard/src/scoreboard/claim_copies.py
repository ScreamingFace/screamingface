"""Claim the frozen copy of each stored Score in the AI Gateway (OME-1947, contracts.md K9).

Run it by hand in a scoreboard pod: `python -m scoreboard.claim_copies [--dry-run]`. It does the
work of the claim pass at start one time. It is safe to run it again: a claim is idempotent.

Output (stdout): one JSON line for each Score that names a copy (`score_id`, `frozen_copy_id`,
`result`), then one summary line with the number of Scores and the count of each result.
Exit status: 0 = each copy is kept (or a dry run); 1 = the gateway did not answer, or a different
error stopped the command (it then writes a Python traceback, for example for a database error);
2 = no gateway URL; 3 = one or more copies have a different result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from scoreboard.config import Settings
from scoreboard.core.copy_claims import (
    CopyClaims,
    GatewayUnavailable,
    ScoreClaim,
    count_results,
    not_kept,
    run_claim_pass,
)
from scoreboard.db import close_db, init_db
from scoreboard.gateway_copy_claims import build_copy_claims
from scoreboard.scores.store import ScoreStore

EXIT_KEPT = 0
EXIT_UNAVAILABLE = 1
EXIT_NO_GATEWAY = 2
EXIT_NOT_KEPT = 3


def _print_results(results: Sequence[ScoreClaim]) -> None:
    for claim in results:
        print(json.dumps(claim.as_dict()))
    print(json.dumps({"scores": len(results), "results": count_results(results)}))


async def _claim_rows(claims: CopyClaims, rows: list[tuple[str, str]], *, dry_run: bool) -> int:
    if dry_run:
        _print_results([ScoreClaim(score_id, copy_id, None) for score_id, copy_id in rows])
        return EXIT_KEPT
    try:
        results = await run_claim_pass(claims, rows)
    except GatewayUnavailable as stopped:
        _print_results(stopped.results)
        print(
            "the gateway did not answer: the command stopped. Run it again later.",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE
    _print_results(results)
    return EXIT_NOT_KEPT if not_kept(results) else EXIT_KEPT


async def _run(args: argparse.Namespace, settings: Settings, claims: CopyClaims) -> int:
    # WHY the client close is outermost: it must run also when init_db fails.
    try:
        await init_db(settings.database_url)
        try:
            rows = await ScoreStore().scores_that_name_a_copy()
            return await _claim_rows(claims, rows, dry_run=args.dry_run)
        finally:
            await close_db()
    finally:
        await claims.aclose()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send a claim to the AI Gateway for the frozen copy of each stored Score. "
            "Exit status: 0 each copy is kept, 1 the gateway did not answer, 2 no gateway URL, "
            "3 one or more copies are not kept."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List each Score that names a frozen copy. Send no claim.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    claims = build_copy_claims(settings)
    if claims is None:
        print(
            "SCOREBOARD_GATEWAY_URL is empty: the command cannot send a claim. "
            "Set it and try again.",
            file=sys.stderr,
        )
        return EXIT_NO_GATEWAY
    return asyncio.run(_run(args, settings, claims))


if __name__ == "__main__":
    raise SystemExit(main())
