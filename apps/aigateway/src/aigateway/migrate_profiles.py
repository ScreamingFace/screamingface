"""`python -m aigateway.migrate_profiles` — the Stage B backfill's command line (OME-1208, S4).

# FEATURE: Stage B "Classification before authority" — classify every `(account, provider)` pair
# (`--dry-run`), publish the dispositions one transaction per account (`--apply`), or rehearse the
# R1 rollback (`--rollback`); `--account <id>` or `--all`; the JSON report goes to stdout and an
# optional `--journal PATH` receives one JSON line per pair plus a summary line.
# INVARIANT (card): the tool is application-owned and secret-aware — it installs the encryption-at-
# rest provider from `AIGATEWAY_SECRET_KEY` (or the persisted local master key) BEFORE any blob read
# and decrypts only in process; it is never the Helm pre-upgrade job. It never mints a master key: a
# database with no key and no env key is refused, because a dry run writes nothing — not even a key.
# AIDEV-NOTE: any run against live data, dry or applied, is a separately authorized owner action.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from .config import Settings
from .core.credential_blob.store import ORMStore
from .core.loader import load_plugins
from .core.provider_access.backfill_apply import (
    BackfillReport,
    Mode,
    all_account_ids,
    run_backfill,
)
from .core.provider_access.backfill_classify import BackfillContext
from .core.registry import ProviderRegistry
from .core.secrets.factory import build_secret_store, set_active_secret_store
from .core.secrets.models import SecretMasterKey
from .db import close_db, init_db

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RETRY = 3


class NoMasterKey(RuntimeError):
    """The local secret provider has no key to decrypt with — and this tool never mints one."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m aigateway.migrate_profiles",
        description=(
            "Classify (account, provider) pairs and move provider-access authority toward "
            "Connections. Reports carry opaque identifiers only."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_const",
        const="dry-run",
        dest="mode",
        help="classify and report; write nothing",
    )
    mode.add_argument(
        "--apply",
        action="store_const",
        const="apply",
        dest="mode",
        help="publish each disposition, one transaction per account",
    )
    mode.add_argument(
        "--rollback",
        action="store_const",
        const="rollback",
        dest="mode",
        help="R1: return every migrated pair to legacy authority, keeping every blob",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--account", metavar="ACCOUNT_ID", help="one account (UUID)")
    scope.add_argument("--all", action="store_true", help="every account")
    parser.add_argument(
        "--journal",
        metavar="PATH",
        help="append one JSON line per pair record plus one summary line",
    )
    return parser.parse_args(argv)


async def run(
    settings: Settings, *, mode: Mode, account: str | None, journal: TextIO | None
) -> BackfillReport:
    await init_db(settings.database_url.get_secret_value())
    try:
        await _refuse_without_a_key(settings)
        # INVARIANT: the secret store is installed BEFORE any credential read.
        set_active_secret_store(
            await build_secret_store(settings.secret_provider, settings.secret_key)
        )
        registry = ProviderRegistry()
        load_plugins(registry)
        credential_store = ORMStore()
        ctx = BackfillContext.from_stores(credential_store, registry)
        account_ids = (account,) if account is not None else await all_account_ids()
        return await run_backfill(ctx, mode=mode, account_ids=account_ids, journal=journal)
    finally:
        set_active_secret_store(None)
        await close_db()


async def _refuse_without_a_key(settings: Settings) -> None:
    if settings.secret_provider.lower() != "local" or settings.secret_key is not None:
        return
    if not await SecretMasterKey.all().exists():
        raise NoMasterKey(
            "no AIGATEWAY_SECRET_KEY and no persisted master key: nothing could be decrypted, "
            "and this tool never generates a key"
        )


def main(argv: Sequence[str] | None = None, *, out: TextIO = sys.stdout) -> int:
    args = parse_args(argv)
    settings = Settings()
    try:
        if args.journal is None:
            report = asyncio.run(run(settings, mode=args.mode, account=args.account, journal=None))
        else:
            with open(args.journal, "a", encoding="utf-8") as journal:
                report = asyncio.run(
                    run(settings, mode=args.mode, account=args.account, journal=journal)
                )
    except NoMasterKey as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    out.write(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    return EXIT_RETRY if report.counts()["conflicts"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
