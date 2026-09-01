from __future__ import annotations

from collections.abc import AsyncGenerator
from importlib import import_module
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest
import pytest_asyncio

asyncpg = import_module("asyncpg")

POSTGRES_IDEMPOTENCY_TEST = (
    "test_a_private_submission_with_an_idempotency_key_round_trips_on_postgres"
)


def _with_schema(database_url: str, schema: str) -> str:
    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["schema"] = schema
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def _execute_schema_statement(database_url: str, statement: str) -> None:
    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


@pytest_asyncio.fixture(autouse=True)
async def _isolate_postgres_idempotency_regression(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[None, None]:
    if request.node.name != POSTGRES_IDEMPOTENCY_TEST:
        yield
        return

    test_module = request.module
    assert test_module is not None
    database_url = getattr(test_module, "DATABASE_URL", "")
    assert isinstance(database_url, str)
    if not database_url.startswith("postgres"):
        yield
        return

    # INVARIANT: the committed PostgreSQL regression uses unfiltered table assertions and cleanup.
    # Running it in a UUID schema makes those operations local to this test even when the configured
    # database is shared. The fixture stays outside the prior test so the append-only contract
    # holds.
    schema = f"scoreboard_idempotency_{uuid4().hex}"
    quoted_schema = f'"{schema}"'
    await _execute_schema_statement(database_url, f"CREATE SCHEMA {quoted_schema}")

    monkeypatch.setattr(test_module, "DATABASE_URL", _with_schema(database_url, schema))
    try:
        yield
    finally:
        await _execute_schema_statement(
            database_url, f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE"
        )
