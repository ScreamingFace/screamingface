"""Clear client-written rows out of the server-owned idempotency namespaces.

FEATURE: OME-894 — `_scoped_idempotency_key` reserves `sfp-` (private, per-submitter) and `sfu-`
(escaped public) as SERVER-owned storage prefixes. Before that reservation existed, every client
key was stored verbatim, so a caller could occupy either namespace directly.

WHY this exists as well as migration `0009`, which deletes the same rows: the migrate Job is a
`pre-install,pre-upgrade` Helm hook, so it completes BEFORE the new pods roll. Old replicas keep
serving — and keep storing client keys verbatim — until they terminate, and a row written in that
window outlives the migration. `0009` cleans what was already there; this cleans what the window
adds, which is why it runs `post-upgrade`.

The mapping table holds no score data and every row expires within 24 hours, so deleting one costs
a client its idempotency fast path and nothing else — the content hash still dedupes the retry. The
foreign key points FROM this table TO scores, so no submission is ever removed.

INVARIANT: this only ever deletes from `idempotency_keys`, and only rows whose key sits in a
reserved namespace. It is idempotent and safe to re-run.

Usage:
    python -m scoreboard.purge_reserved_idempotency_keys [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence

from scoreboard.config import Settings
from scoreboard.db import close_db, init_db
from scoreboard.scores.models import IdempotencyKey
from scoreboard.scores.store import RESERVED_KEY_PREFIXES

logger = logging.getLogger(__name__)


async def purge_reserved_idempotency_keys(*, dry_run: bool = False) -> dict[str, int]:
    """Delete every mapping whose key occupies a reserved namespace, per prefix.

    Returns the count removed for each prefix, so an operator sees whether the rollout window
    actually produced anything rather than having to trust that it did not.
    """
    removed: dict[str, int] = {}
    for prefix in RESERVED_KEY_PREFIXES:
        matching = IdempotencyKey.filter(key__startswith=prefix)
        removed[prefix] = await matching.count() if dry_run else await matching.delete()
    return removed


def _format(removed: dict[str, int], *, dry_run: bool) -> str:
    verb = "would remove" if dry_run else "removed"
    parts = ", ".join(f"{prefix}{count}" for prefix, count in sorted(removed.items()))
    return f"{verb} {sum(removed.values())} reserved-namespace mappings ({parts})"


async def _run(*, dry_run: bool) -> str:
    settings = Settings()
    await init_db(settings.database_url)
    try:
        return _format(await purge_reserved_idempotency_keys(dry_run=dry_run), dry_run=dry_run)
    finally:
        await close_db()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Clear client-written rows out of the reserved idempotency namespaces."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed and change nothing.",
    )
    args = parser.parse_args(argv)
    print(asyncio.run(_run(dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
