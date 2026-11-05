from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from tortoise.context import TortoiseContext

from scoreboard.config import Settings
from scoreboard.db import build_tortoise_config
from scoreboard.main import create_app


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _with_schema(database_url: str, schema: str) -> str:
    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["schema"] = schema
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    settings = Settings(
        database_url=f"sqlite://{tmp_path / 'scoreboard.sqlite3'}",
        cors_origins=[],
    )

    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def postgres_schema_database_url() -> Generator[str, None, None]:
    database_url = os.getenv("SCOREBOARD_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("SCOREBOARD_TEST_DATABASE_URL is not set")
    assert database_url is not None

    schema = f"scoreboard_test_{uuid4().hex}"
    quoted_schema = _quote_identifier(schema)

    async def _create_schema() -> None:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute(f"CREATE SCHEMA {quoted_schema}")
        finally:
            await conn.close()

    async def _drop_schema() -> None:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")
        finally:
            await conn.close()

    asyncio.run(_create_schema())
    try:
        yield _with_schema(database_url, schema)
    finally:
        asyncio.run(_drop_schema())


@pytest.fixture
def tortoise_database_url(request: pytest.FixtureRequest) -> str:
    # WHY: schema setup/teardown uses asyncio.run for synchronous callers. Resolve
    # it before pytest enters the async ORM fixture's event loop (OME-430).
    if os.getenv("SCOREBOARD_TEST_DATABASE_URL"):
        return request.getfixturevalue("postgres_schema_database_url")
    return "sqlite://:memory:"


@pytest_asyncio.fixture
async def tortoise_db(tortoise_database_url: str) -> AsyncGenerator[None, None]:
    # WHY: tortoise_test_context creates a database. We already own an isolated
    # schema in the supplied database; no database-creation permission is needed.
    async with TortoiseContext() as context:
        await context.init(config=build_tortoise_config(tortoise_database_url))
        await context.generate_schemas(safe=False)
        yield
