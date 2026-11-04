"""The effective-row listing on PostgreSQL (OME-1138 close-out, L7a).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2 — `GET
# /v1/oauth/connections` flags the row the default chat resolve serves, from one marker listing
# and one Connection listing over every status. The marker's UUID reference and the store's
# status filtering are read through PostgreSQL's types here; SQLite cannot show that.
# WHY bound: fixtures and helpers are bound from the S2'c module; run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

from aigateway.core.oauth.store import OAuthConnectionStore

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
KEY = "sk-ant-api03-postgres-effective-key-1357"


def _plain_row(client: TestClient, account_id: str, label: str, *, active: bool = True) -> str:
    async def create() -> UUID:
        store = OAuthConnectionStore()
        row = await store.create_pending(
            account_id=account_id, provider=PROVIDER, label=label, connection_id=uuid4()
        )
        if active:
            row = await store.complete(row, label=label, identity=None)
        return row.id

    return str(backing._call(client, create))


def _flags(client: TestClient) -> dict[str, bool]:
    response = client.get("/v1/oauth/connections", params={"provider": PROVIDER})
    assert response.status_code == 200, response.text
    return {row["id"]: row["effective"] for row in response.json()["connections"]}


def test_a_migrated_pair_flags_its_reference_on_postgres(pg_client: TestClient) -> None:
    account_id = backing._account_id(pg_client)
    effective = backing._seed(
        pg_client,
        account_id,
        backing._fresh_name(),
        auth_type="api_key",
        blob=backing._api_key_blob(KEY),
    )
    other = _plain_row(pg_client, account_id, "work")

    assert _flags(pg_client) == {str(effective): True, other: False}


def test_an_unmarked_pair_flags_its_single_active_row_on_postgres(pg_client: TestClient) -> None:
    account_id = backing._account_id(pg_client)
    backing._call(pg_client, backing._reset_pair, backing._app(pg_client), account_id)
    active = _plain_row(pg_client, account_id, "work")
    waiting = _plain_row(pg_client, account_id, "waiting", active=False)

    assert _flags(pg_client) == {active: True, waiting: False}
