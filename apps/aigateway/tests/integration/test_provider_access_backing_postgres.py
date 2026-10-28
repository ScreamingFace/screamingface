"""PostgreSQL coexistence and race tests for the Connection-backed authority (OME-1208, S2'c).

# FEATURE: Stage B Target — on PostgreSQL (READ COMMITTED) the pair marker's compare-and-set is a
# ROW-LOCK fence: two authority writers on one migrated pair never both commit; the loser's whole
# transaction rolls back and it answers 409. SQLite's single writer cannot show this.
# INVARIANT (D14): one write owner per owned pair — the native routes and the legacy op 8 both
# advance the SAME marker row first, so whoever holds that row lock decides, and the other
# re-evaluates its `WHERE generation = <stale>` to zero rows.
# WHY each test resets the pair: the lane's fixtures are bound from
# `test_lifecycle_postgres_races.py` (one container per module, migrated to head by the tortoise
# CLI — a broken 0012 fails at fixture time), so the admin account is shared by every test; each
# test resets the (account, anthropic) pair and seeds a uniquely named blob. Run with
# `AIGW_TEST_PG=1`; the module skips otherwise.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import test_lifecycle_postgres_races as lane
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.auth_types import AuthType
from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.provider_access.pair_authority import PairAuthorityConflict, PairAuthorityStore
from aigateway.plugins.anthropic_provider.auth import credential_service_for

pytestmark = pytest.mark.needs_postgres

# WHY bound, not imported by name: pytest registers a fixture found in the module namespace, and
# an assignment is a use — no `noqa`, no fixture module of our own, no rewrite of the prior suite.
postgres_database_url = lane.postgres_database_url
pg_client = lane.pg_client

PROVIDER = "anthropic"
KEY = "sk-ant-api03-postgres-migrated-key-9753"


# --- helpers ------------------------------------------------------------------------------------


def _app(client: TestClient) -> FastAPI:
    app = client.app
    if not isinstance(app, FastAPI):
        raise AssertionError("TestClient is not running the expected FastAPI app")
    return app


def _call(
    client: TestClient, fn: Callable[..., Coroutine[Any, Any, Any]], *a: Any, **kw: Any
) -> Any:
    portal = client.portal
    if portal is None:
        raise AssertionError("TestClient portal is not active")
    return portal.call(partial(fn, *a, **kw))


def _account_id(client: TestClient) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _fresh_name() -> str:
    return f"pair-{uuid4().hex[:8]}"


def _oauth_blob(token: str) -> str:
    return json.dumps(
        {
            "access_token": token,
            "refresh_token": "rt",
            "token_type": "Bearer",
            "expires_at_ms": int(time.time() * 1000) + 3_600_000,
        }
    )


def _api_key_blob(key: str) -> str:
    return json.dumps({"auth_type": "api_key", "api_key": key})


def _token_factory(token: str) -> Any:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": f"refresh-{token}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0)
    )


async def _reset_pair(app: FastAPI, account_id: str) -> None:
    """The shared admin account starts every test with NO authority for the anthropic pair."""
    await ProviderCredentialSlot.filter(account_id=account_id, provider=PROVIDER).delete()
    await OAuthConnection.filter(account_id=account_id, provider=PROVIDER).delete()


async def _seed_migrated_pair(
    app: FastAPI, account_id: str, *, name: str, auth_type: AuthType, blob: str
) -> UUID:
    """A migrated pair: the name-address blob + the effective Connection at that blob."""
    await app.state.credential_store.write(
        credential_service_for(credential_name_for(account_id, name)), "default", blob
    )
    store = OAuthConnectionStore()
    connection = await store.create_pending(
        account_id=account_id,
        provider=PROVIDER,
        label=name,
        connection_id=uuid4(),
        credential_provider=PROVIDER,
        credential_locator=credential_locator_for(PROVIDER, account_id, name),
    )
    connection = await store.complete(connection, label=name, identity=None)
    if auth_type == "api_key":
        connection = await store.set_auth_type(connection, auth_type) or connection
    markers = PairAuthorityStore()
    pair = await markers.read(account_id, PROVIDER)
    await markers.advance(
        account_id,
        PROVIDER,
        expected_generation=pair.generation,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )
    return connection.id


def _marker(client: TestClient, account_id: str) -> Any:
    return _call(client, PairAuthorityStore().read, account_id, PROVIDER)


def _connection(client: TestClient, account_id: str, connection_id: UUID | str) -> Any:
    return _call(client, OAuthConnectionStore().get, account_id, connection_id)


def _profile_blob(client: TestClient, account_id: str, name: str) -> str | None:
    service = credential_service_for(credential_name_for(account_id, name))
    return _call(client, _app(client).state.credential_store.read, service, "default")


def _seed(
    client: TestClient, account_id: str, name: str, *, auth_type: AuthType, blob: str
) -> UUID:
    _call(client, _reset_pair, _app(client), account_id)
    return _call(
        client,
        _seed_migrated_pair,
        _app(client),
        account_id,
        name=name,
        auth_type=auth_type,
        blob=blob,
    )


class _MarkerHold:
    """Hold the marker ROW LOCK after the advance `holds` names; record the other writer's attempt.

    The held writer performed its `UPDATE … WHERE generation = g` (the row is locked until its
    transaction ends) and now waits inside that transaction; the other writer signals `attempted`
    and blocks on the same row until `release`, then re-evaluates its predicate to zero rows.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, holds: Callable[[int, dict], bool]):
        self.held = threading.Event()
        self.attempted = threading.Event()
        self.release = threading.Event()
        real = PairAuthorityStore.advance
        calls = {"n": 0}
        hold = self

        async def advance(store: Any, account_id: str, provider: str, **kwargs: Any) -> Any:
            index = calls["n"]
            calls["n"] += 1
            if holds(index, kwargs):
                result = await real(store, account_id, provider, **kwargs)
                hold.held.set()
                if not await asyncio.to_thread(hold.release.wait, 20):
                    raise TimeoutError("marker hold was not released")
                return result
            hold.attempted.set()
            return await real(store, account_id, provider, **kwargs)

        monkeypatch.setattr(PairAuthorityStore, "advance", advance)


# --- the marker itself on PostgreSQL ----------------------------------------------------------


def test_pair_marker_compare_and_set_is_fenced_on_postgres(pg_client: TestClient) -> None:
    account_id = _account_id(pg_client)
    _call(pg_client, _reset_pair, _app(pg_client), account_id)
    markers = PairAuthorityStore()

    first = _call(
        pg_client,
        markers.advance,
        account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note="two candidates",
    )
    assert first.generation == 1
    # INVARIANT: a second creator loses on the unique pair; the aborted transaction rolls back.
    with pytest.raises(PairAuthorityConflict):
        _call(
            pg_client,
            markers.advance,
            account_id,
            PROVIDER,
            expected_generation=0,
            migration_state="quarantined",
        )
    with pytest.raises(PairAuthorityConflict):
        _call(
            pg_client,
            markers.advance,
            account_id,
            PROVIDER,
            expected_generation=5,
            migration_state="none",
        )
    second = _call(
        pg_client,
        markers.advance,
        account_id,
        PROVIDER,
        expected_generation=1,
        migration_state="none",
    )
    assert second.generation == 2
    read = _marker(pg_client, account_id)
    assert (read.generation, read.migration_state, read.migration_note) == (2, "none", None)


def test_a_migrated_pair_reads_through_its_locator_on_postgres(pg_client: TestClient) -> None:
    account_id = _account_id(pg_client)
    name = _fresh_name()
    effective = _seed(pg_client, account_id, name, auth_type="oauth", blob=_oauth_blob("tok"))

    row = _connection(pg_client, account_id, effective)
    # WHY: JSONB comes back as a mapping — the shape `credential_name_from_locator` parses.
    assert isinstance(row.credential_locator, dict)
    assert row.credential_locator["service"].endswith(f":{account_id}:{name}")
    token = pg_client.get(f"/v1/oauth/connections/{effective}/token")
    assert token.status_code == 200, token.text
    assert token.json()["access_token"] == "tok"


# --- two authority writers on one pair ----------------------------------------------------------


# WHY no facade-callback marker race: the Profile-facade OAuth callback retired at OME-1209
# Stage E3b; a native callback holding the marker against a racing key write is pinned by
# `test_native_repair_postgres.py`
# (`test_a_repair_holding_the_marker_makes_a_racing_key_takeover_lose_on_postgres`).
