"""The local gateway as the destination of a community-cache pull (epic OME-1311).

Everything here is the gateway's own code, imported lazily: the loader that writes pages into the
gateway's SQLite database (`aigateway…sqlite_loader`), and the revisions its cache keys are
computed under. `import screamingface` therefore stays free of `aigateway`, and a pull without the
`screamingface[runtime]` extra is refused with an install hint before any request is made.

WHY the provider plugins are loaded: adapter revisions are registered when a plugin is imported
(today `openrouter_adapter`), and every hosted row is an OpenRouter row. Without them the local
revisions would hold only the core contracts, and a page keyed under another OpenRouter key format
would load ~600k rows that never hit. Loading imports the plugin modules and registers them in a
throwaway registry; it makes no request and reads no setting (spec decision 14).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NoReturn

from screamingface.cache import CachePullError, PullResult

DATABASE_NAME: Final = "aigateway.sqlite3"

_MESSAGES: Final = {
    "not_a_gateway_database": (
        "local_gateway_missing",
        "The local gateway database has no cache table yet",
        'Run "screamingface up" once to create it, then pull again.',
    ),
    "outdated_gateway_database": (
        "local_gateway_outdated",
        "The local gateway database is older than this screamingface",
        'Start "screamingface up" once to migrate it, then pull again.',
    ),
    "revision_mismatch": (
        "revision_mismatch",
        "The hosted cache is keyed under revisions this local gateway does not use",
        "Upgrade screamingface to match the hosted Engine, then pull again.",
    ),
    "malformed_row": (
        "malformed_page",
        "The hosted Engine sent a row this client cannot load",
        None,
    ),
}


def gateway_database(data_dir: Path) -> Path:
    return data_dir / DATABASE_NAME


def missing_runtime_modules() -> tuple[str, ...]:
    """The `screamingface[runtime]` modules this process cannot import (nothing is imported)."""
    from screamingface._runtime import source as runtime_source
    from screamingface._runtime.server import _RUNTIME_ONLY_MODULES, _missing_runtime_modules

    # INVARIANT (OME-1001): in a checkout the live apps/ code must shadow a stale copy.
    runtime_source.activate(runtime_source.resolve_source(os.environ))
    return _missing_runtime_modules(_RUNTIME_ONLY_MODULES)


class LocalGateway:
    """Writes pages into one local gateway database and vouches for its revisions."""

    def __init__(self, database: Path, *, empty: PullResult) -> None:
        self._database = database
        self._empty = empty
        self._revisions: dict[str, str] | None = None

    @property
    def database(self) -> Path:
        return self._database

    def prepare(self) -> None:
        """Refuse a pull that cannot land, before any request; load the local revisions."""
        missing = missing_runtime_modules()
        if missing:
            raise CachePullError(
                f"Pulling the community cache needs the local runtime ({', '.join(missing)} "
                "missing)",
                code="runtime_missing",
                hint='Install "screamingface[runtime]".',
                result=self._empty,
            )
        if not self._database.is_file():
            self._refuse("not_a_gateway_database", self._empty, f"{self._database} not found")
        self._revisions = _local_revisions()

    def check(self, remote: Mapping[str, str], result: PullResult) -> None:
        from aigateway.core.request_cache.sqlite_loader import PageRejected, check_revisions

        if self._revisions is None:
            raise RuntimeError("prepare() must run before check()")
        try:
            check_revisions(remote, self._revisions)
        except PageRejected as rejected:
            self._refuse(rejected.reason, result, str(rejected))

    def load(self, rows: Sequence[Mapping[str, Any]], result: PullResult) -> int:
        """Load one batch of rows; return how many were new to the local cache."""
        from aigateway.core.request_cache.sqlite_loader import PageRejected, load_page

        try:
            return load_page(rows, self._database).inserted
        except PageRejected as rejected:
            self._refuse(rejected.reason, result, str(rejected))

    def _refuse(self, reason: str, result: PullResult, detail: str) -> NoReturn:
        code, message, hint = _MESSAGES.get(
            reason, ("local_load_refused", "The load was refused", None)
        )
        raise CachePullError(f"{message}: {detail}", code=code, hint=hint, result=result)


def _local_revisions() -> dict[str, str]:
    from aigateway.core.loader import load_plugins
    from aigateway.core.registry import ProviderRegistry
    from aigateway.core.request_cache.revisions import active_cache_revisions

    load_plugins(ProviderRegistry())
    return active_cache_revisions()


__all__ = ["DATABASE_NAME", "LocalGateway", "gateway_database", "missing_runtime_modules"]
