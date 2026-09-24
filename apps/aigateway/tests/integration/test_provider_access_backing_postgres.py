"""PostgreSQL coexistence and race tests for the Connection-backed authority (OME-1208, S2'c).

# FEATURE: Stage B Target — on PostgreSQL (READ COMMITTED) the pair marker's compare-and-set is a
# ROW-LOCK fence: two authority writers on one migrated pair never both commit; the loser's whole
# transaction rolls back and it answers 409. SQLite's single writer cannot show this.
# INVARIANT (D14): one write owner per owned pair — the native routes, the legacy op 8 and the
# Profile-facade OAuth callback all advance the SAME marker row first, so whoever holds that row
# lock decides, and the other re-evaluates its `WHERE generation = <stale>` to zero rows.
# AIDEV-NOTE: the lane's fixtures are bound from `test_lifecycle_postgres_races.py` (one container
# per module, migrated to head by the tortoise CLI — a broken 0012 fails at fixture time). Run
# with `AIGW_TEST_PG=1`; the module skips otherwise. The admin account is shared by every test,
# so each test resets the (account, anthropic) pair and seeds a uniquely named document.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import test_lifecycle_postgres_races as lane
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.profile_models import (
    AuthType,
    Profile,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
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
    for document in await app.state.profile_index.list(account_id, provider=PROVIDER):
        await app.state.profile_index.remove(document.id)


async def _seed_migrated_pair(
    app: FastAPI, account_id: str, *, name: str, auth_type: AuthType, blob: str
) -> UUID:
    """What the backfill leaves: document + Profile blob + effective Connection at that blob."""
    await app.state.credential_store.write(
        credential_service_for(credential_name_for(account_id, name)), "default", blob
    )
    await app.state.profile_index.upsert(
        Profile(
            id=profile_id_for(account_id, PROVIDER, name),
            account_id=account_id,
            provider=PROVIDER,
            name=name,
            state=ProfileState.AUTHENTICATED,
            auth_type=auth_type,
        )
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


def _document(client: TestClient, account_id: str, name: str) -> Profile | None:
    return _call(client, _app(client).state.profile_index.get, account_id, PROVIDER, name)


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
    status = pg_client.get(f"/v1/auth/{PROVIDER}/profiles/{name}/status")
    assert status.status_code == 200, status.text
    assert (status.json()["state"], status.json()["auth_type"]) == ("authenticated", "oauth")
    token = pg_client.get(f"/v1/oauth/connections/{effective}/token")
    assert token.status_code == 200, token.text
    assert token.json()["access_token"] == "tok"


# --- two authority writers on one pair ----------------------------------------------------------


def test_native_delete_holding_the_marker_makes_the_legacy_key_route_lose_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = _account_id(pg_client)
    name = _fresh_name()
    effective = _seed(pg_client, account_id, name, auth_type="oauth", blob=_oauth_blob("tok"))
    hold = _MarkerHold(monkeypatch, holds=lambda _i, kw: kw.get("effective_connection_id") is None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(pg_client.delete, f"/v1/oauth/connections/{effective}")
        assert hold.held.wait(20), "the delete never advanced the marker"
        setting = executor.submit(
            pg_client.put, f"/v1/auth/{PROVIDER}/profiles/{name}/api-key", json={"api_key": KEY}
        )
        assert hold.attempted.wait(20), "op 8 never reached its marker advance"
        hold.release.set()
        deleted = deleting.result(timeout=30)
        set_result = setting.result(timeout=30)

    assert deleted.status_code == 204, deleted.text
    assert set_result.status_code == 409, set_result.text
    assert set_result.json()["detail"]["code"] == "connection_conflict"
    pair = _marker(pg_client, account_id)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        None,
        2,
    )
    assert _connection(pg_client, account_id, effective).status == "revoked"
    assert _document(pg_client, account_id, name) is None
    assert _profile_blob(pg_client, account_id, name) is None

    # The retried op 8 starts over: a NEW effective Connection at the Profile address.
    retry = pg_client.put(f"/v1/auth/{PROVIDER}/profiles/{name}/api-key", json={"api_key": KEY})
    assert retry.status_code == 200, retry.text
    pair = _marker(pg_client, account_id)
    assert pair.generation == 3
    assert pair.effective_connection_id is not None and pair.effective_connection_id != effective
    blob = _profile_blob(pg_client, account_id, name)
    assert blob is not None and json.loads(blob)["api_key"] == KEY


def test_legacy_key_route_holding_the_marker_makes_the_native_delete_lose_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = _account_id(pg_client)
    name = _fresh_name()
    effective = _seed(pg_client, account_id, name, auth_type="oauth", blob=_oauth_blob("tok"))
    hold = _MarkerHold(
        monkeypatch, holds=lambda _i, kw: kw.get("effective_connection_id") is not None
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        setting = executor.submit(
            pg_client.put, f"/v1/auth/{PROVIDER}/profiles/{name}/api-key", json={"api_key": KEY}
        )
        assert hold.held.wait(20), "op 8 never advanced the marker"
        deleting = executor.submit(pg_client.delete, f"/v1/oauth/connections/{effective}")
        assert hold.attempted.wait(20), "the delete never reached its marker advance"
        hold.release.set()
        set_result = setting.result(timeout=30)
        deleted = deleting.result(timeout=30)

    assert set_result.status_code == 200, set_result.text
    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["detail"]["code"] == "connection_conflict"
    row = _connection(pg_client, account_id, effective)
    assert (row.status, row.auth_type) == ("active", "api_key")
    pair = _marker(pg_client, account_id)
    assert (pair.effective_connection_id, pair.generation) == (effective, 2)
    blob = _profile_blob(pg_client, account_id, name)
    assert blob is not None and json.loads(blob)["api_key"] == KEY
    document = _document(pg_client, account_id, name)
    assert document is not None and document.auth_type == "api_key"

    # The retried delete then retires the pair.
    retry = pg_client.delete(f"/v1/oauth/connections/{effective}")
    assert retry.status_code == 204, retry.text
    pair = _marker(pg_client, account_id)
    assert (pair.effective_connection_id, pair.generation) == (None, 3)
    assert _connection(pg_client, account_id, effective).status == "revoked"
    assert _profile_blob(pg_client, account_id, name) is None
    assert _document(pg_client, account_id, name) is None


def test_oauth_callback_holding_the_marker_makes_the_native_key_route_lose_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = _account_id(pg_client)
    name = _fresh_name()
    effective = _seed(pg_client, account_id, name, auth_type="api_key", blob=_api_key_blob(KEY))
    _app(pg_client).state.anthropic_http_factory = _token_factory("oauth-tok")
    started = pg_client.post(f"/v1/auth/{PROVIDER}/profiles", json={"name": name})
    assert started.status_code == 201, started.text
    generation_after_start = _marker(pg_client, account_id).generation
    hold = _MarkerHold(monkeypatch, holds=lambda i, _kw: i == 0)

    with ThreadPoolExecutor(max_workers=2) as executor:
        callback = executor.submit(
            pg_client.get,
            f"/v1/auth/{PROVIDER}/callback",
            params={"code": "code-1", "state": started.json()["state"]},
            follow_redirects=False,
        )
        assert hold.held.wait(20), "the callback never advanced the marker"
        setting = executor.submit(
            pg_client.put,
            f"/v1/oauth/connections/{effective}/api-key",
            json={"api_key": "sk-ant-api03-postgres-replacement-key-8642"},
        )
        assert hold.attempted.wait(20), "the key replacement never reached its marker advance"
        hold.release.set()
        completed = callback.result(timeout=30)
        set_result = setting.result(timeout=30)

    assert completed.status_code == 200, completed.text
    assert set_result.status_code == 409, set_result.text
    assert set_result.json()["detail"]["code"] == "connection_conflict"
    row = _connection(pg_client, account_id, effective)
    assert (row.status, row.auth_type) == ("active", "oauth")
    pair = _marker(pg_client, account_id)
    assert (pair.effective_connection_id, pair.generation) == (
        effective,
        generation_after_start + 1,
    )
    blob = _profile_blob(pg_client, account_id, name)
    assert blob is not None and json.loads(blob)["access_token"] == "oauth-tok"
    assert "replacement-key" not in blob
    document = _document(pg_client, account_id, name)
    assert document is not None and document.auth_type == "oauth"
