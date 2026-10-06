from __future__ import annotations

import os
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from tortoise import Tortoise

from .config import DEFAULT_DATABASE_URL, PoolSize, normalize_database_url

__all__ = [
    "DEFAULT_CONNECTION",
    "READINESS_CONNECTION",
    "TORTOISE_CONFIG",
    "PoolSize",
    "build_server_tortoise_config",
    "build_tortoise_config",
    "close_db",
    "init_db",
]

DEFAULT_CONNECTION = "default"
"""Tortoise alias of the request connection: the one every scoreboard transaction opens on.

INVARIANT (OME-1488): every `in_transaction()` names it. With a second connection configured
(`READINESS_CONNECTION` below) Tortoise refuses to choose one for an unnamed transaction, which
took down every leaderboard read and submission in the web app on 2026-10-05.
"""

READINESS_CONNECTION = "readiness"
"""Tortoise alias of the connection reserved for `/readyz` (OME-1452).

INVARIANT: no model app uses it, so request traffic can never hold it — the probe never queues
behind a saturated request pool, and a load spike cannot mark every replica unready at once.
"""

_READINESS_POOL = PoolSize(minsize=1, maxsize=1)
# WHY min 1: the connection stays open between probes (it is reserved, not borrowed), so a probe
# does not pay a fresh connect each period. asyncpg re-establishes it on acquire if it dropped.

_POOLED_SCHEMES = frozenset({"postgres", "postgresql", "asyncpg", "psycopg"})

DEFAULT_CONFIGURED_DATABASE_URL = normalize_database_url(
    os.getenv("SCOREBOARD_DATABASE_URL", DEFAULT_DATABASE_URL)
)

TORTOISE_CONFIG: dict[str, Any] = {
    "connections": {DEFAULT_CONNECTION: DEFAULT_CONFIGURED_DATABASE_URL},
    "apps": {
        "models": {
            "models": ["scoreboard.scores.models"],
            "migrations": "scoreboard.scores.migrations",
            "default_connection": DEFAULT_CONNECTION,
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}


def build_tortoise_config(database_url: str) -> dict[str, Any]:
    config = deepcopy(TORTOISE_CONFIG)
    config["connections"][DEFAULT_CONNECTION] = database_url
    return config


def _with_pool(database_url: str, pool: PoolSize) -> str:
    # WHY only pooled schemes: the SQLite client turns every extra URL parameter into a PRAGMA.
    # WHY `minsize`/`maxsize`: the names Tortoise's PostgreSQL client pops (its defaults 1 / 5).
    # AIDEV-NOTE: an asyncpg-native `min_size`/`max_size` already in the URL would still win —
    # Tortoise spreads URL extras over these — so do not put those in SCOREBOARD_DATABASE_URL.
    parts = urlsplit(database_url)
    if parts.scheme not in _POOLED_SCHEMES:
        return database_url
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(minsize=str(pool.minsize), maxsize=str(pool.maxsize))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_server_tortoise_config(database_url: str, pool: PoolSize) -> dict[str, Any]:
    """The web app's config: an explicitly sized request pool plus the readiness connection.

    The CLIs and the migration CLI keep `build_tortoise_config` / `TORTOISE_CONFIG` — one
    connection, no probe.
    """
    config = build_tortoise_config(_with_pool(database_url, pool))
    config["connections"][READINESS_CONNECTION] = _with_pool(database_url, _READINESS_POOL)
    return config


async def init_db(database_url: str, *, pool: PoolSize | None = None) -> None:
    """Initialise Tortoise; with `pool`, as the web app (sized pool + readiness connection)."""
    config = (
        build_tortoise_config(database_url)
        if pool is None
        else build_server_tortoise_config(database_url, pool)
    )
    # ASGI lifespan can initialize Tortoise in a different task than request handlers.
    # The global fallback keeps that initialized context visible across those tasks.
    await Tortoise.init(config=config, _enable_global_fallback=True)


async def close_db() -> None:
    await Tortoise.close_connections()
