"""`python -m aigateway.purge_profile_history` — the Stage E history purge's command line (E5b).

# FEATURE: OME-1138 Stage E history cleanup, spec C5 — report (`--dry-run`) or delete (`--apply`)
# the retired Profile storage: every Profile index row and every provider-credential blob no
# Connection row addresses, one transaction per account; `--account <id>` or `--all` (which also
# sweeps the rows of deleted accounts and the legacy global index row). The JSON report goes to
# stdout; an optional `--journal PATH` receives one JSON line per account plus a summary line.
# INVARIANT (C5): the tool installs the encryption-at-rest provider like `migrate_profiles`, never
# mints a master key, and is never a Helm hook. A skipped account (or a kept legacy row) exits 4.
# INVARIANT (C6): after `--apply` no build older than E4b may run in that environment; the owner
# backs the database up first. Every run against live data is an owner action.
# INVARIANT (C7): on SQLite the gateway is stopped while this runs; it has no row locks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from types import SimpleNamespace
from typing import TextIO
from uuid import UUID

from .config import Settings
from .core.credential_blob.store import ORMStore
from .core.loader import load_plugins
from .core.provider_access.history_purge import PurgeContext, PurgeMode, PurgeReport, run_purge
from .core.registry import ProviderRegistry
from .core.secrets.factory import build_secret_store, set_active_secret_store
from .db import close_db, init_db
from .migrate_profiles import NoMasterKey, refuse_without_a_key
from .provider_composition import compose_providers

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SKIPPED = 4


def _account_id(text: str) -> str:
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("an account id is a UUID") from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m aigateway.purge_profile_history",
        description=(
            "Delete the retired Profile storage: index rows and provider-credential blobs no "
            "Connection addresses. Reports carry account ids and counts only."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_const",
        const="dry-run",
        dest="mode",
        help="report what would go; write nothing",
    )
    mode.add_argument(
        "--apply",
        action="store_const",
        const="apply",
        dest="mode",
        help="delete it, one transaction per account",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--account", metavar="ACCOUNT_ID", type=_account_id, help="one account")
    scope.add_argument(
        "--all",
        action="store_true",
        help="every account, then deleted accounts' rows and the legacy global index row",
    )
    parser.add_argument(
        "--journal",
        metavar="PATH",
        help="append one JSON line per account plus one summary line",
    )
    return parser.parse_args(argv)


async def run(
    settings: Settings, *, mode: PurgeMode, account: str | None, journal: TextIO | None
) -> PurgeReport:
    await init_db(settings.database_url.get_secret_value())
    try:
        await refuse_without_a_key(settings)
        # INVARIANT: the secret store is installed BEFORE the first index read.
        set_active_secret_store(
            await build_secret_store(settings.secret_provider, settings.secret_key)
        )
        registry = ProviderRegistry()
        load_plugins(registry)
        # WHY the configured endpoints too: they are providers; without them every endpoint
        # Connection is unresolvable and its account would be skipped.
        compose_providers(registry, config_path=settings.remote_endpoints_config)
        app = SimpleNamespace(state=SimpleNamespace(credential_store=ORMStore()))
        ctx = PurgeContext.build(app, registry)
        account_ids = None if account is None else (account,)
        return await run_purge(ctx, mode=mode, account_ids=account_ids, journal=journal)
    finally:
        set_active_secret_store(None)
        await close_db()


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
    return EXIT_SKIPPED if report.refused() else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
