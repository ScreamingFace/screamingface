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
from tortoise.contrib.test import tortoise_test_context

from scoreboard.config import Settings
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


@pytest_asyncio.fixture
async def tortoise_db(request: pytest.FixtureRequest) -> AsyncGenerator[None, None]:
    database_url = "sqlite://:memory:"
    if os.getenv("SCOREBOARD_TEST_DATABASE_URL"):
        database_url = request.getfixturevalue("postgres_schema_database_url")

    async with tortoise_test_context(
        modules=["scoreboard.scores.models"],
        db_url=database_url,
        app_label="models",
    ):
        yield


@pytest_asyncio.fixture
async def partial_unique_indexes(tortoise_db: None) -> None:
    """The two E14 partial unique indexes, which `generate_schemas` cannot create."""
    from tortoise import Tortoise

    from scoreboard.scores.models.partial_indexes import create_partial_unique_indexes

    await create_partial_unique_indexes(Tortoise.get_connection("default"))
