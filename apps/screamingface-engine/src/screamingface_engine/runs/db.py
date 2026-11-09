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
from typing import Any

from tortoise import Tortoise
from tortoise.migrations.api import migrate as run_migrations

APP_LABEL = "runs"
CONNECTION = "runs"
# WHY in-memory for the CLI's default: authoring a migration needs no database, and a default
# file path would leave a stray database wherever the command happened to run.
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


async def migrate(database_url: str) -> None:
    """Apply every pending migration (spec R9), then close the connections it opened."""
    try:
        await run_migrations(config=build_tortoise_config(database_url))
    finally:
        await Tortoise.close_connections()


async def init_db(database_url: str) -> None:
    await Tortoise.init(config=build_tortoise_config(database_url), _enable_global_fallback=True)


async def close_db() -> None:
    await Tortoise.close_connections()
