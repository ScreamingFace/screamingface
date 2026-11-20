"""The Run registry's Tortoise config, built like `apps/aigateway/src/aigateway/db.py` (OME-1785).

FEATURE: first-class Runs, E5 P1 spec D2 and R9. SQLite locally, Postgres hosted; one config, one
code path. `TORTOISE_CONFIG` is what the `tortoise` CLI reads:

    uv run tortoise -c screamingface_engine.runs.db.TORTOISE_CONFIG makemigrations

AIDEV-NOTE: built-in Tortoise migrations only, never Aerich. A schema change ships with its
migration in the same change (sdlc-python S1), and `test_run_migrations.py` fails when the two
disagree.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import asyncpg.exceptions as asyncpg_errors
from tortoise import Tortoise
from tortoise.context import TortoiseContext, _current_context
from tortoise.exceptions import OperationalError, TransactionManagementError
from tortoise.migrations.executor import MigrationExecutor

APP_LABEL = "runs"
CONNECTION = "runs"
# WHY in-memory for the CLI's default: authoring a migration needs no database, and a default
# file path would leave a stray database wherever the command happened to run.
# The failures that mean the database could not answer, not that the request or the code is wrong:
# a lost or refused connection and a timeout are `OSError`s (Tortoise's `DBConnectionError` is
# one), a locked or failing database is `OperationalError`, a broken transaction the other.
# asyncpg lets three through Tortoise unwrapped when Postgres drops a query's connection in
# flight: a lost connection, a server shutting down or a restart, and a pooled connection found
# closed. A caller may retry these; anything else is a bug.
UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    OperationalError,
    TransactionManagementError,
    asyncpg_errors.PostgresConnectionError,
    asyncpg_errors.OperatorInterventionError,
    asyncpg_errors.InterfaceError,
)
_CLI_DATABASE_URL = os.environ.get("URL4_CLOUD_DATABASE_URL") or "sqlite://:memory:"


def build_tortoise_config(database_url: str) -> dict[str, Any]:
    return {
        "connections": {CONNECTION: database_url},
        "apps": {
            APP_LABEL: {
                "models": ["screamingface_engine.runs.models"],
                "default_connection": CONNECTION,
                "migrations": "screamingface_engine.runs.migrations",
            }
        },
        # INVARIANT: every stored time is aware UTC, the clock `runs.state` compares against.
        "use_tz": True,
        "timezone": "UTC",
    }


TORTOISE_CONFIG = build_tortoise_config(_CLI_DATABASE_URL)


async def open_context(database_url: str) -> TortoiseContext:
    """The Engine's own Tortoise context, connected to its database.

    INVARIANT: never Tortoise's process-wide state. The Client's local runtime serves aigateway
    and the Engine in one process, and aigateway owns that global context; the Engine's queries
    run inside this context instead (`using`).
    """
    context = TortoiseContext()
    with using(context):
        await context.init(config=build_tortoise_config(database_url))
    return context


@contextmanager
def using(context: TortoiseContext) -> Iterator[None]:
    """Run the enclosed queries in ``context``.

    AIDEV-NOTE: sets Tortoise's context variable directly rather than `with context:`, whose one
    token slot is shared by every task that enters it; the writer and the routes enter the same
    context concurrently.
    """
    token = _current_context.set(context)
    try:
        yield
    finally:
        _current_context.reset(token)


async def migrate(database_url: str) -> None:
    """Apply every pending migration (spec R9), in a context of its own that it then closes."""
    context = TortoiseContext()
    with using(context):
        try:
            await context.init(config=build_tortoise_config(database_url))
            executor = MigrationExecutor(context.connections.get(CONNECTION), apps(database_url))
            await executor.migrate()
        finally:
            await context.close_connections()


def apps(database_url: str) -> dict[str, dict[str, Any]]:
    return {APP_LABEL: build_tortoise_config(database_url)["apps"][APP_LABEL]}


async def init_db(database_url: str) -> None:
    await Tortoise.init(config=build_tortoise_config(database_url), _enable_global_fallback=True)


async def close_db() -> None:
    await Tortoise.close_connections()
