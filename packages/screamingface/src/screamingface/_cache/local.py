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
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NoReturn

from screamingface.cache import CachePullError, PullResult

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
}


def gateway_database(data_dir: Path) -> Path:
    from screamingface._runtime.config import GATEWAY_DATABASE_NAME

    return data_dir / GATEWAY_DATABASE_NAME


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

    @property
    def identity(self) -> tuple[str, int, int] | tuple[str]:
        """The database file itself, not its path: a pull resumes only into the file it was
        loading. A file deleted and recreated, moved into place, or reached through a retargeted
        symlink is another file, and the pull into it starts over."""
        try:
            stat = self._database.stat()
        except OSError:
            return (str(self._database),)
        return str(self._database.resolve()), stat.st_dev, stat.st_ino

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
        from aigateway.core.request_cache.sqlite_loader import PageRejected, check_database

        # WHY here: a missing, foreign or unmigrated database is refused before the sign-in,
        # the counted first page and the download — and even when the filter matches no rows.
        try:
            check_database(self._database)
        except PageRejected as rejected:
            self._refuse(rejected.reason, self._empty, str(rejected))
        except sqlite3.Error as exc:
            raise self._unwritable(exc, self._empty) from exc
        self._revisions = _local_revisions()

    def check(self, remote: Mapping[str, str], result: PullResult) -> None:
        from aigateway.core.request_cache.sqlite_loader import PageRejected, check_revisions

        if self._revisions is None:
            raise RuntimeError("prepare() must run before check()")
        try:
            check_revisions(remote, self._revisions)
        except PageRejected as rejected:
            self._refuse(rejected.reason, result, str(rejected))

    def load(self, rows: Sequence[Mapping[str, Any]], result: PullResult) -> tuple[int, int]:
        """Load one batch of rows; return how many were new to the local cache, and how many
        were skipped as rows a local lookup could not serve."""
        from aigateway.core.request_cache.sqlite_loader import PageRejected, load_page

        try:
            loaded = load_page(rows, self._database)
            return loaded.inserted, loaded.skipped
        except PageRejected as rejected:
            self._refuse(rejected.reason, result, str(rejected))
        except sqlite3.Error as exc:
            raise self._unwritable(exc, result) from exc

    def holds(self, key_hash: str) -> bool:
        """Whether the database still has `key_hash`; one that cannot be read holds nothing.

        WHY "nothing" on failure: a resumed pull then starts over, and loading is idempotent, so
        doubt costs a re-read rather than skipped pages.
        """
        from aigateway.core.request_cache.sqlite_loader import PageRejected, holds

        try:
            return holds(self._database, key_hash)
        except (PageRejected, sqlite3.Error):
            return False

    def _unwritable(self, exc: sqlite3.Error, result: PullResult) -> CachePullError:
        # WHY retryable: a locked or full database fails the batch, not the pull. The cursor
        # only ever advances past a whole page, and loading is idempotent, so calling again
        # reloads this page and continues.
        return CachePullError(
            f"The local gateway database could not be written: {exc}",
            code="local_load_failed",
            hint="Call pull_from_remote() again to continue from the last loaded page.",
            result=result,
        )

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


__all__ = ["LocalGateway", "gateway_database", "missing_runtime_modules"]
