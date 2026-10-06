"""The DB pool is sized explicitly, and readiness never waits on it (OME-1452).

`/readyz` (OME-944) caps its `SELECT 1` at 2 s. On the request pool, a burst that holds every
pooled connection makes the probe queue past that cap, and the pod goes unready under load — on
every replica at once. The probe therefore runs on a reserved connection the request traffic can
never hold, and the request pool's size is a setting rather than a library default (Tortoise
1.1.8 silently picks min 1 / max 5 for PostgreSQL).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from pydantic import ValidationError
from tortoise import connections

from scoreboard.config import Settings
from scoreboard.db import (
    READINESS_CONNECTION,
    TORTOISE_CONFIG,
    PoolSize,
    build_server_tortoise_config,
    close_db,
    init_db,
)
from scoreboard.routes import health

_PG_URL = "postgres://scoreboard:secret@db.internal:5432/scoreboard?schema=sb"


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


# --- Settings ------------------------------------------------------------------------------------


def test_pool_size_defaults_to_tortoises_effective_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY these numbers: they are what the pool already ran on (Tortoise's PostgreSQL client
    # defaults), so making them explicit changes no capacity. Raising them is a load-data call.
    monkeypatch.delenv("SCOREBOARD_DB_POOL_MINSIZE", raising=False)
    monkeypatch.delenv("SCOREBOARD_DB_POOL_MAXSIZE", raising=False)

    settings = Settings()

    assert (settings.db_pool_minsize, settings.db_pool_maxsize) == (1, 5)


def test_pool_size_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCOREBOARD_DB_POOL_MINSIZE", "2")
    monkeypatch.setenv("SCOREBOARD_DB_POOL_MAXSIZE", "12")

    settings = Settings()

    assert settings.db_pool == PoolSize(minsize=2, maxsize=12)


@pytest.mark.parametrize(
    ("minsize", "maxsize"),
    [(0, 0), (-1, 5), (6, 5)],
    ids=["max-below-one", "negative-min", "min-above-max"],
)
def test_pool_size_rejects_an_unusable_pool(minsize: int, maxsize: int) -> None:
    # INVARIANT: a pool asyncpg would refuse at first query is refused at startup instead.
    with pytest.raises(ValidationError):
        Settings(db_pool_minsize=minsize, db_pool_maxsize=maxsize)


def test_pool_size_accepts_the_boundary_min_equal_to_max() -> None:
    settings = Settings(db_pool_minsize=0, db_pool_maxsize=1)
    assert settings.db_pool == PoolSize(minsize=0, maxsize=1)

    settings = Settings(db_pool_minsize=4, db_pool_maxsize=4)
    assert settings.db_pool == PoolSize(minsize=4, maxsize=4)


# --- Config builder ------------------------------------------------------------------------------


def test_postgres_default_connection_carries_the_explicit_pool_size() -> None:
    config = build_server_tortoise_config(_PG_URL, PoolSize(minsize=2, maxsize=9))

    query = _query(config["connections"]["default"])
    assert query["minsize"] == ["2"]
    assert query["maxsize"] == ["9"]
    # The operator's own parameters survive (the schema is what isolates the PG test lane).
    assert query["schema"] == ["sb"]


def test_readiness_connection_is_the_same_database_with_a_pool_of_one() -> None:
    config = build_server_tortoise_config(_PG_URL, PoolSize(minsize=2, maxsize=9))

    default = urlsplit(config["connections"]["default"])
    readiness = urlsplit(config["connections"][READINESS_CONNECTION])
    assert (readiness.scheme, readiness.netloc, readiness.path) == (
        default.scheme,
        default.netloc,
        default.path,
    )
    query = _query(config["connections"][READINESS_CONNECTION])
    assert (query["minsize"], query["maxsize"], query["schema"]) == (["1"], ["1"], ["sb"])


def test_readiness_connection_backs_no_model_app() -> None:
    # INVARIANT: no ORM query is ever routed to the reserved connection — only the probe uses it.
    config = build_server_tortoise_config(_PG_URL, PoolSize(minsize=1, maxsize=5))

    assert READINESS_CONNECTION != "default"
    assert {app["default_connection"] for app in config["apps"].values()} == {"default"}


def test_sqlite_urls_get_no_pool_parameters() -> None:
    # WHY: the SQLite client turns every extra URL parameter into a PRAGMA; there is no pool.
    url = "sqlite://./scoreboard.sqlite3"

    config = build_server_tortoise_config(url, PoolSize(minsize=2, maxsize=9))

    assert config["connections"]["default"] == url
    assert config["connections"][READINESS_CONNECTION] == url


def test_migration_cli_config_is_unchanged() -> None:
    # The `tortoise` migration CLI reads TORTOISE_CONFIG; the reserved connection is server-only.
    assert set(TORTOISE_CONFIG["connections"]) == {"default"}
    assert set(build_server_tortoise_config(_PG_URL, PoolSize(1, 5))["connections"]) == {
        "default",
        READINESS_CONNECTION,
    }


# --- Saturation (deterministic, SQLite) -----------------------------------------------------------


@pytest_asyncio.fixture
async def server_db(tmp_path: Path) -> AsyncIterator[None]:
    await init_db(f"sqlite://{tmp_path / 'pool.sqlite3'}", pool=PoolSize(minsize=1, maxsize=5))
    try:
        yield
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_readyz_stays_ready_while_the_request_connection_is_held(
    server_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # STORY: as the operator, a load spike that occupies every request connection must not pull
    # the pod out of the Service — readiness asks "can I reach the database", not "am I busy".
    # SQLite's client is a single connection behind a lock; holding it is total saturation.
    monkeypatch.setattr(health, "PROBE_TIMEOUT_S", 0.2)

    async with connections.get("default").acquire_connection():
        response = await health.readyz()

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_probe_on_the_request_connection_would_flap_under_the_same_hold(
    server_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Control for the test above: the same hold DOES time out a probe on `default`, so the green
    # result there comes from the reserved connection, not from a hold that blocks nothing.
    monkeypatch.setattr(health, "PROBE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(health, "READINESS_CONNECTION", "default")

    async with connections.get("default").acquire_connection():
        response = await health.readyz()

    assert response.status_code == 503
