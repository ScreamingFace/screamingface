"""Turning Runs on in an App (OME-1785, E5 P1 spec D2, R4, R9, R11).

FEATURE: first-class Runs. `install_runs` opens the registry at startup and runs its one writer:
- local mode: a SQLite file beside the artifacts dir, migrated at start;
- hosted: `URL4_CLOUD_DATABASE_URL`, migrated by the chart's Job before the App starts. With no
  URL the App runs with Runs off, as before this feature; a SQLite URL refuses to start.

Either way the App declares the outcome stream, because its own terminal writers publish to it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI
from tortoise.connection import get_connection
from tortoise.migrations.executor import MigrationExecutor

from screamingface_engine.candidate_outcomes import CandidateOutcomeStream
from screamingface_engine.config import Settings
from screamingface_engine.runs import db
from screamingface_engine.runs.consumer import DEFAULT_RETRY_S, OutcomeWriter
from screamingface_engine.runs.store import TortoiseRunStore

logger = logging.getLogger(__name__)

LOCAL_DATABASE_NAME = "engine.sqlite3"
LOCAL_DATA_DIR = ".screamingface-engine"
MIGRATE_COMMAND = "python -m tortoise -c screamingface_engine.runs.db.TORTOISE_CONFIG migrate"


class RunsConfigError(RuntimeError):
    """The App was given a database it must not run Runs on. Startup fails."""


class SchemaBehindError(RuntimeError):
    """The database's schema is older than this Engine's code. Startup fails."""


class DatabaseUnreachableError(RuntimeError):
    """The Run registry's database did not answer. Startup fails (spec R9, §9 2026-11-05)."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def local_database_url(settings: Settings, *, home: Path | None = None) -> str:
    """The local Engine database: the configured URL, or `~/.screamingface-engine/engine.sqlite3`.

    The file is the Engine's, not only the Run registry's; `runs` is the Tortoise app inside it.
    WHY the home folder when no URL is given: the default artifacts dir is a temp path on purpose,
    which the OS may clear and another user's Engine may own, so 30 days of Runs cannot live
    beside it. A runtime that owns a data dir passes the URL itself, as the Client does.
    """
    if settings.database_url:
        return settings.database_url
    base = home if home is not None else Path.home()
    return f"sqlite://{base / LOCAL_DATA_DIR / LOCAL_DATABASE_NAME}"


def ensure_sqlite_dir(url: str) -> None:
    """Create a SQLite database's folder. Any other URL names no folder on this machine."""
    if url.startswith("sqlite://"):
        Path(url.removeprefix("sqlite://")).parent.mkdir(parents=True, exist_ok=True)


async def open_run_store(
    url: str,
    settings: Settings,
    *,
    survives_restart: bool,
    migrate_first: bool,
    clock: Callable[[], datetime] = _utc_now,
) -> TortoiseRunStore:
    """Open the registry, after migrating it when ``migrate_first`` (local mode only)."""
    if migrate_first:
        await db.migrate(url)
    context = await db.open_context(url)
    try:
        with db.using(context):
            await _require_a_reachable_database(url)
            await _refuse_an_older_schema(url)
    except BaseException:
        # WHY: an open SQLite connection's thread keeps the process alive, so a refused start
        # would hang instead of exiting.
        await context.close_connections()
        raise
    return TortoiseRunStore(
        clock=clock,
        pending_grace=timedelta(seconds=settings.run_pending_grace_s),
        lost_after=timedelta(seconds=settings.run_lost_after_s),
        outcomes_survive_restart=survives_restart,
        started_at=clock(),
        context=context,
    )


async def _require_a_reachable_database(url: str) -> None:
    # WHY before the schema check: Tortoise reads an unreachable database's migration history as
    # empty, so without this probe a down database would be reported as an unmigrated one.
    try:
        await get_connection(db.CONNECTION).execute_query("SELECT 1")
    except Exception as exc:
        raise DatabaseUnreachableError(
            f"the Run registry's database at {redacted_url(url)} did not answer "
            f"({type(exc).__name__}); check URL4_CLOUD_DATABASE_URL and that the database is up"
        ) from exc


def redacted_url(url: str) -> str:
    """``url`` without its password, for an error an operator reads."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
    return urlunsplit(parts._replace(netloc=netloc))


async def _refuse_an_older_schema(url: str) -> None:
    executor = MigrationExecutor(get_connection(db.CONNECTION), db.apps(url))
    if await executor.plan():
        raise SchemaBehindError(
            f"the Run registry's schema is older than this Engine; run `{MIGRATE_COMMAND}` "
            f"(the chart's migrate Job does it before every upgrade)"
        )


class _RunsLifecycle:
    """The startup and shutdown hooks `install_runs` registers."""

    def __init__(
        self,
        app: FastAPI,
        settings: Settings,
        outcomes: CandidateOutcomeStream,
        *,
        url: str,
        local: bool,
        writer_retry_s: float,
    ) -> None:
        self._app = app
        self._settings = settings
        self._outcomes = outcomes
        self._url = url
        self._local = local
        self._writer_retry_s = writer_retry_s

    async def start(self) -> None:
        await self._outcomes.ensure_stream(update=True)
        if not self._url:
            logger.warning(
                "Runs are off: URL4_CLOUD_DATABASE_URL is not set, so /runs answers 404 and no "
                "outcome is written (DEPLOYMENT.md: turn Runs on)"
            )
            return
        if self._local:
            ensure_sqlite_dir(self._url)
        store = await open_run_store(
            self._url,
            self._settings,
            survives_restart=self._outcomes.survives_restart,
            migrate_first=self._local,
        )
        self._app.state.run_registry = store
        writer = OutcomeWriter(self._outcomes, store, retry_s=self._writer_retry_s)
        self._app.state.outcome_writer_task = asyncio.get_running_loop().create_task(writer.run())

    async def stop(self) -> None:
        task = self._app.state.outcome_writer_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        store = self._app.state.run_registry
        if store is not None:
            self._app.state.run_registry = None
            await store.aclose()


def install_runs(
    app: FastAPI,
    settings: Settings,
    outcomes: CandidateOutcomeStream,
    *,
    local: bool,
    writer_retry_s: float = DEFAULT_RETRY_S,
) -> None:
    """Open the registry and start its writer with the App, and close both with it.

    `app.state.run_registry` is the store, or None while Runs are off.
    """
    app.state.run_registry = None
    app.state.outcome_writer_task = None
    url = local_database_url(settings) if local else settings.database_url
    if not local and url.startswith("sqlite"):
        raise RunsConfigError(
            "URL4_CLOUD_DATABASE_URL is a SQLite URL; a hosted Engine needs Postgres, because a "
            "pod's SQLite file is wiped on every restart"
        )
    lifecycle = _RunsLifecycle(
        app, settings, outcomes, url=url, local=local, writer_retry_s=writer_retry_s
    )
    app.router.on_startup.append(lifecycle.start)
    app.router.on_shutdown.append(lifecycle.stop)


__all__ = [
    "LOCAL_DATABASE_NAME",
    "MIGRATE_COMMAND",
    "RunsConfigError",
    "SchemaBehindError",
    "ensure_sqlite_dir",
    "install_runs",
    "local_database_url",
    "open_run_store",
]
