"""Fixtures for the Run registry contract (OME-1785): one store per test, on SQLite or Postgres,
built by the real migrations so the schema under test is the one that ships."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from tortoise.backends.base.executor import EXECUTOR_CACHE

from screamingface_engine.runs import db
from screamingface_engine.runs.records import CandidateStart, ContextRef, RunSpec
from screamingface_engine.runs.store import TortoiseRunStore

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
LOST_AFTER = timedelta(hours=48)
ORPHAN_GRACE = timedelta(seconds=120)
DEADLINE = timedelta(hours=48)
PG_ENABLED = os.environ.get("URL4_CLOUD_TEST_PG") == "1"


@dataclass
class Clock:
    now: datetime = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> datetime:
        self.now += timedelta(**delta)
        return self.now


@dataclass
class Registry:
    store: TortoiseRunStore
    clock: Clock
    url: str
    started_at: datetime = field(default=T0)

    def restarted(
        self, *, survives_restart: bool, orphan_grace: timedelta = ORPHAN_GRACE
    ) -> TortoiseRunStore:
        """The same database, opened by a process that started now."""
        return make_store(self.clock, survives_restart, self.clock(), orphan_grace)


def make_store(
    clock: Clock, survives_restart: bool, started_at: datetime, orphan_grace: timedelta
) -> TortoiseRunStore:
    return TortoiseRunStore(
        clock=clock,
        lost_after=LOST_AFTER,
        outcomes_survive_restart=survives_restart,
        started_at=started_at,
        orphan_grace=orphan_grace,
        default_deadline=DEADLINE,
    )


def spec(*names: str, client_key: str = "key-1") -> RunSpec:
    return RunSpec(
        client_key=client_key,
        benchmark="gsm8k",
        case_count=10,
        candidates=names or ("alpha", "beta"),
        client_version="1.2.3",
    )


def start(name: str, url4: str = "openai/gpt-5?q=Hi") -> CandidateStart:
    return CandidateStart(name=name, url4=url4)


def start_spec(
    *names: str,
    client_key: str = "key-1",
    detach: bool = False,
    deadline: timedelta | None = None,
    owner_email: str | None = "alice@example.org",
    context: ContextRef | None = None,
) -> RunSpec:
    """A P2 Run: every Candidate carries its start (E5 P2 spec D1, D8)."""
    names = names or ("alpha", "beta")
    return RunSpec(
        client_key=client_key,
        benchmark="gsm8k",
        case_count=10,
        candidates=names,
        client_version="1.2.3",
        starts=tuple(start(name) for name in names),
        detach=detach,
        deadline=deadline,
        owner_email=owner_email,
        context=context,
    )


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver=None) as server:
        yield (
            f"postgres://{server.username}:{quote(server.password, safe='')}"
            f"@{server.get_container_host_ip()}:{server.get_exposed_port(5432)}/{server.dbname}"
        )


async def _fresh_postgres(url: str) -> None:
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(url)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()


async def open_registry(
    request: pytest.FixtureRequest, tmp_path: object
) -> AsyncIterator[Registry]:
    if request.param == "postgres":
        url = request.getfixturevalue("postgres_server")
        await _fresh_postgres(url)
    else:
        url = f"sqlite://{tmp_path}/runs.sqlite3"
    # WHY: Tortoise caches each model's INSERT per connection NAME, and both databases use the
    # same one, so a Postgres test after a SQLite one would reuse SQLite's `?` placeholders. Only
    # a test process switches dialects; the App opens one database for its whole life.
    EXECUTOR_CACHE.clear()
    await db.migrate(url)
    await db.init_db(url)
    clock = Clock()
    store = make_store(clock, True, T0, ORPHAN_GRACE)
    try:
        yield Registry(store, clock, url)
    finally:
        await db.close_db()


DATABASES = [
    pytest.param("sqlite", id="sqlite"),
    pytest.param(
        "postgres",
        id="postgres",
        marks=[
            pytest.mark.needs_postgres,
            pytest.mark.skipif(not PG_ENABLED, reason="URL4_CLOUD_TEST_PG=1 not set"),
        ],
    ),
]
