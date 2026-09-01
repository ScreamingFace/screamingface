"""Tortoise wiring: one connection, one app label, one migrations package.

`TORTOISE_CONFIG` is read by two callers that must never disagree — this service's `_lifespan`
and the `tortoise migrate` CLI, which resolves it through `[tool.tortoise]` in `pyproject.toml`.
That is why the module-level value reads the environment the same way `Settings` does: a
migration applied against one database while the service talks to another is the failure this
single source removes.

The service does **not** apply migrations. See `Settings.database_url` for why, and
`README.md` for the command.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from tortoise import Tortoise

from .config import DEFAULT_DATABASE_URL, ENV_PREFIX, normalize_database_url

MODELS_MODULE = "report_intake.reports.models"
MIGRATIONS_MODULE = "report_intake.reports.migrations"

DEFAULT_CONFIGURED_DATABASE_URL = normalize_database_url(
    os.getenv(f"{ENV_PREFIX}DATABASE_URL", DEFAULT_DATABASE_URL)
)

TORTOISE_CONFIG: dict[str, Any] = {
    "connections": {"default": DEFAULT_CONFIGURED_DATABASE_URL},
    "apps": {
        "models": {
            "models": [MODELS_MODULE],
            "migrations": MIGRATIONS_MODULE,
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}
"""``use_tz``/``timezone`` are not cosmetic here: every timestamp this service compares is a
deadline (`next_attempt_at`, `lease_expires_at`) or a window edge (the idempotency TTL, the
retention cut-off). A naive datetime read back from sqlite would compare against an aware `now`
by raising `TypeError` inside a retry sweep."""


def build_tortoise_config(database_url: str) -> dict[str, Any]:
    config = deepcopy(TORTOISE_CONFIG)
    config["connections"]["default"] = database_url
    return config


async def init_db(database_url: str) -> None:
    # ASGI lifespan can initialize Tortoise in a different task than request handlers. The global
    # fallback keeps that initialized context visible across those tasks.
    await Tortoise.init(config=build_tortoise_config(database_url), _enable_global_fallback=True)


async def close_db() -> None:
    await Tortoise.close_connections()
