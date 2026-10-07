from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
from tortoise import connections

from aigateway.config import Settings
from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
    credential_locator_for,
)
from aigateway.core.profile_models import credential_name_for
from aigateway.main import create_app
from aigateway.plugins.anthropic_provider.auth import credential_service_for

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_API_KEY = "sk-ant-api03-postgres-race-key-1234"


class _ValidValidationService:
    async def validate(self, _plugin, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            ApiKeyValidationState.VALID,
            stage=ApiKeyValidationStage.READINESS,
        )


@pytest.fixture(scope="module")
def postgres_database_url() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = (
            f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
            f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
            f"/{postgres.dbname}"
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tortoise",
                "-c",
                "aigateway.db.TORTOISE_CONFIG",
                "migrate",
            ],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


@pytest.fixture
def pg_client(postgres_database_url: str) -> Generator[TestClient, None, None]:
    settings = Settings(
        database_url=SecretStr(postgres_database_url),
        admin_password=SecretStr("test-admin-password"),
        jwt_secret=SecretStr("x" * 32),
        provisioning_token=SecretStr("p" * 32),
        secret_key=SecretStr(base64.b64encode(b"k" * 32).decode()),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "test-admin-password"},
        )
        assert login.status_code == 200, login.text
        client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})
        app.state.api_key_validation_service = _ValidValidationService()
        yield client


def _token_factory(token: str):
    async def _handler(_request: httpx.Request) -> httpx.Response:
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
        transport=httpx.MockTransport(_handler),
        timeout=httpx.Timeout(5.0),
    )


def _app(client: TestClient) -> FastAPI:
    app = client.app
    if not isinstance(app, FastAPI):
        raise AssertionError("TestClient is not running the expected FastAPI app")
    return app


def _read_credential(client: TestClient, service: str, account: str) -> str | None:
    portal = client.portal
    if portal is None:
        raise AssertionError("TestClient portal is not active")
    value = portal.call(_app(client).state.credential_store.read, service, account)
    if value is not None and not isinstance(value, str):
        raise AssertionError("credential store returned a non-string value")
    return value


def _failing_token_factory():
    async def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
        timeout=httpx.Timeout(5.0),
    )


def _profile_credential(client: TestClient, account_id: str, name: str) -> str | None:
    service = credential_service_for(credential_name_for(account_id, name))
    return _read_credential(client, service, "default")


def _connection_credential(client: TestClient, account_id: str, connection_id: UUID) -> str | None:
    locator = credential_locator_for("anthropic", account_id, connection_id)
    return _read_credential(client, locator["service"], locator["account"])


async def _lock_waiters() -> int:
    rows = await connections.get("default").execute_query_dict(
        "SELECT count(*) AS n FROM pg_stat_activity"
        " WHERE wait_event_type = 'Lock' AND datname = current_database()"
    )
    return int(rows[0]["n"])


def _overlaps(client: TestClient, attempted: threading.Event) -> bool:
    """The second writer reached its hook, or is parked on a PostgreSQL lock.

    # WHY (OME-1497, G0 §5.3): a writer on a legacy-owned pair now claims the pair marker FIRST,
    # so the second writer parks on that claim before it reaches the index or the row hook;
    # either signal means the two writers truly overlap before the first commits.
    """
    portal = client.portal
    if portal is None:
        raise AssertionError("TestClient portal is not active")
    deadline = time.monotonic() + 10
    while not attempted.is_set() and portal.call(_lock_waiters) == 0:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def test_postcondition_owner_check_and_cas_are_atomic_on_postgres(
    pg_client: TestClient,
    monkeypatch,
) -> None:
    name = f"ownership-{uuid4()}"
    account_id = pg_client.get("/v1/auth/me").json()["id"]
    _app(pg_client).state.anthropic_http_factory = _token_factory("oauth-A-token")
    start_a = pg_client.post("/v1/auth/anthropic/profiles", json={"name": name})
    index = _app(pg_client).state.profile_index
    authenticate_pending = index.authenticate_pending
    cas_reached = threading.Event()
    release_cas = threading.Event()

    async def _pause_before_cas(profile, **kwargs) -> None:
        cas_reached.set()
        if not await asyncio.to_thread(release_cas.wait, 10):
            raise TimeoutError("profile CAS was not released")
        await authenticate_pending(profile, **kwargs)

    monkeypatch.setattr(index, "authenticate_pending", _pause_before_cas)
    with ThreadPoolExecutor(max_workers=1) as executor:
        callback_a = executor.submit(
            pg_client.get,
            "/v1/auth/anthropic/callback",
            params={"code": "code-A", "state": start_a.json()["state"]},
            follow_redirects=False,
        )
        assert cas_reached.wait(10), "A never reached its production durable-CAS boundary"
        start_b = pg_client.post("/v1/auth/anthropic/profiles", json={"name": name})
        release_cas.set()
        response_a = callback_a.result(timeout=10)

    assert start_b.status_code == 201
    assert response_a.status_code == 409
    assert response_a.json()["detail"]["code"] == "profile_auth_conflict"
    assert _profile_credential(pg_client, account_id, name) is None
    assert pg_client.get(f"/v1/auth/anthropic/profiles/{name}").json()["state"] == "pending"

    _app(pg_client).state.anthropic_http_factory = _token_factory("oauth-B-token")
    response_b = pg_client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code-B", "state": start_b.json()["state"]},
        follow_redirects=False,
    )
    assert response_b.status_code == 200


def test_stale_error_read_before_delete_cannot_resurrect_profile_on_postgres(
    pg_client: TestClient,
    monkeypatch,
) -> None:
    name = f"error-delete-{uuid4()}"
    account_id = pg_client.get("/v1/auth/me").json()["id"]
    _app(pg_client).state.anthropic_http_factory = _failing_token_factory()
    started = pg_client.post("/v1/auth/anthropic/profiles", json={"name": name})
    index = _app(pg_client).state.profile_index
    mark_pending_error = index.mark_pending_error
    error_precondition_read = threading.Event()
    release_error_cas = threading.Event()

    async def _pause_after_error_precondition(profile_id: str, **kwargs) -> None:
        observed = await index.get(account_id, "anthropic", name)
        assert observed is not None and observed.state.value == "pending"
        error_precondition_read.set()
        if not await asyncio.to_thread(release_error_cas.wait, 10):
            raise TimeoutError("error CAS was not released")
        await mark_pending_error(profile_id, **kwargs)

    monkeypatch.setattr(index, "mark_pending_error", _pause_after_error_precondition)
    with ThreadPoolExecutor(max_workers=1) as executor:
        callback = executor.submit(
            pg_client.get,
            "/callback",
            params={"code": "bad-code", "state": started.json()["state"]},
            follow_redirects=False,
        )
        assert error_precondition_read.wait(10), "failure path never read its pending profile"
        deleted = pg_client.delete(f"/v1/auth/anthropic/profiles/{name}")
        release_error_cas.set()
        failed = callback.result(timeout=10)

    assert deleted.status_code == 204
    assert failed.status_code == 500
    assert pg_client.get(f"/v1/auth/anthropic/profiles/{name}").status_code == 404
    assert _profile_credential(pg_client, account_id, name) is None


def test_profile_absent_credential_delete_set_commit_orders_on_postgres(
    pg_client: TestClient,
    monkeypatch,
) -> None:
    account_id = pg_client.get("/v1/auth/me").json()["id"]
    index = _app(pg_client).state.profile_index

    delete_first = f"profile-delete-first-{uuid4()}"
    assert (
        pg_client.post("/v1/auth/anthropic/profiles", json={"name": delete_first}).status_code
        == 201
    )
    remove = index.remove
    upsert = index.upsert
    delete_holds_index = threading.Event()
    set_attempted_index = threading.Event()
    release_delete = threading.Event()

    async def _holding_remove(profile_id: str) -> None:
        await remove(profile_id)
        delete_holds_index.set()
        if not await asyncio.to_thread(release_delete.wait, 10):
            raise TimeoutError("profile delete was not released")

    async def _attempting_upsert(*args, **kwargs) -> None:
        set_attempted_index.set()
        await upsert(*args, **kwargs)

    monkeypatch.setattr(index, "remove", _holding_remove)
    monkeypatch.setattr(index, "upsert", _attempting_upsert)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(
            pg_client.delete,
            f"/v1/auth/anthropic/profiles/{delete_first}",
        )
        assert delete_holds_index.wait(10)
        setting = executor.submit(
            pg_client.put,
            f"/v1/auth/anthropic/profiles/{delete_first}/api-key",
            json={"api_key": _API_KEY},
        )
        assert _overlaps(pg_client, set_attempted_index)
        release_delete.set()
        deleted = deleting.result(timeout=10)
        set_result = setting.result(timeout=10)

    assert deleted.status_code == 204
    assert set_result.status_code == 409
    assert pg_client.get(f"/v1/auth/anthropic/profiles/{delete_first}").status_code == 404
    assert _profile_credential(pg_client, account_id, delete_first) is None

    monkeypatch.setattr(index, "remove", remove)
    monkeypatch.setattr(index, "upsert", upsert)
    set_first = f"profile-set-first-{uuid4()}"
    assert (
        pg_client.post("/v1/auth/anthropic/profiles", json={"name": set_first}).status_code == 201
    )
    set_holds_index = threading.Event()
    delete_attempted_index = threading.Event()
    release_set = threading.Event()

    async def _holding_upsert(*args, **kwargs) -> None:
        await upsert(*args, **kwargs)
        set_holds_index.set()
        if not await asyncio.to_thread(release_set.wait, 10):
            raise TimeoutError("profile set was not released")

    async def _attempting_remove(profile_id: str) -> None:
        delete_attempted_index.set()
        await remove(profile_id)

    monkeypatch.setattr(index, "upsert", _holding_upsert)
    monkeypatch.setattr(index, "remove", _attempting_remove)
    with ThreadPoolExecutor(max_workers=2) as executor:
        setting = executor.submit(
            pg_client.put,
            f"/v1/auth/anthropic/profiles/{set_first}/api-key",
            json={"api_key": _API_KEY},
        )
        assert set_holds_index.wait(10)
        deleting = executor.submit(
            pg_client.delete,
            f"/v1/auth/anthropic/profiles/{set_first}",
        )
        assert _overlaps(pg_client, delete_attempted_index)
        release_set.set()
        set_result = setting.result(timeout=10)
        deleted = deleting.result(timeout=10)

    assert set_result.status_code == 200
    # WHY 409 (OME-1497, G0 §5.3): the delete read the pair before the set's claim committed, so
    # its own claim loses and its whole transaction rolls back; a retry reads the new pair.
    assert deleted.status_code == 409
    assert pg_client.delete(f"/v1/auth/anthropic/profiles/{set_first}").status_code == 204
    assert pg_client.get(f"/v1/auth/anthropic/profiles/{set_first}").status_code == 404
    assert _profile_credential(pg_client, account_id, set_first) is None


def test_connection_absent_credential_delete_set_commit_orders_on_postgres(
    pg_client: TestClient,
    monkeypatch,
) -> None:
    account_id = pg_client.get("/v1/auth/me").json()["id"]

    async def _seed_errored_connection(label: str) -> UUID:
        store = OAuthConnectionStore()
        connection_id = uuid4()
        connection = await store.create_api_key(
            account_id=account_id,
            provider="anthropic",
            label=label,
            connection_id=connection_id,
        )
        await store.mark_error(connection, "credential absent")
        return connection_id

    portal = pg_client.portal
    if portal is None:
        raise AssertionError("TestClient portal is not active")
    delete_first: UUID = portal.call(_seed_errored_connection, f"conn-delete-first-{uuid4()}")
    mark_revoked = OAuthConnectionStore.mark_revoked
    reactivate = OAuthConnectionStore.reactivate
    delete_holds_connection = threading.Event()
    set_attempted_connection = threading.Event()
    release_delete = threading.Event()

    async def _holding_revoke(self, connection, *args, **kwargs):
        revoked = await mark_revoked(self, connection, *args, **kwargs)
        delete_holds_connection.set()
        if not await asyncio.to_thread(release_delete.wait, 10):
            raise TimeoutError("connection delete was not released")
        return revoked

    async def _attempting_reactivate(self, connection):
        set_attempted_connection.set()
        return await reactivate(self, connection)

    monkeypatch.setattr(OAuthConnectionStore, "mark_revoked", _holding_revoke)
    monkeypatch.setattr(OAuthConnectionStore, "reactivate", _attempting_reactivate)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(pg_client.delete, f"/v1/oauth/connections/{delete_first}")
        assert delete_holds_connection.wait(10)
        setting = executor.submit(
            pg_client.put,
            f"/v1/oauth/connections/{delete_first}/api-key",
            json={"api_key": _API_KEY},
        )
        assert _overlaps(pg_client, set_attempted_connection)
        release_delete.set()
        deleted = deleting.result(timeout=10)
        set_result = setting.result(timeout=10)

    assert deleted.status_code == 204
    assert set_result.status_code == 409
    assert pg_client.get(f"/v1/oauth/connections/{delete_first}").json()["status"] == "revoked"
    assert _connection_credential(pg_client, account_id, delete_first) is None

    monkeypatch.setattr(OAuthConnectionStore, "mark_revoked", mark_revoked)
    monkeypatch.setattr(OAuthConnectionStore, "reactivate", reactivate)
    set_first: UUID = portal.call(_seed_errored_connection, f"conn-set-first-{uuid4()}")
    set_holds_connection = threading.Event()
    delete_attempted_connection = threading.Event()
    release_set = threading.Event()

    async def _holding_reactivate(self, connection):
        activated = await reactivate(self, connection)
        set_holds_connection.set()
        if not await asyncio.to_thread(release_set.wait, 10):
            raise TimeoutError("connection set was not released")
        return activated

    async def _attempting_revoke(self, connection, *args, **kwargs):
        delete_attempted_connection.set()
        return await mark_revoked(self, connection, *args, **kwargs)

    monkeypatch.setattr(OAuthConnectionStore, "reactivate", _holding_reactivate)
    monkeypatch.setattr(OAuthConnectionStore, "mark_revoked", _attempting_revoke)
    with ThreadPoolExecutor(max_workers=2) as executor:
        setting = executor.submit(
            pg_client.put,
            f"/v1/oauth/connections/{set_first}/api-key",
            json={"api_key": _API_KEY},
        )
        assert set_holds_connection.wait(10)
        deleting = executor.submit(pg_client.delete, f"/v1/oauth/connections/{set_first}")
        assert _overlaps(pg_client, delete_attempted_connection)
        release_set.set()
        set_result = setting.result(timeout=10)
        deleted = deleting.result(timeout=10)

    assert set_result.status_code == 200
    # WHY 409 (OME-1497, G0 §5.3): the delete read the pair before the set's claim committed, so
    # its own claim loses and its whole transaction rolls back; a retry reads the new pair.
    assert deleted.status_code == 409
    assert pg_client.delete(f"/v1/oauth/connections/{set_first}").status_code == 204
    assert pg_client.get(f"/v1/oauth/connections/{set_first}").json()["status"] == "revoked"
    assert _connection_credential(pg_client, account_id, set_first) is None


def test_connection_refresh_republish_loses_to_committed_revoke_on_postgres(
    pg_client: TestClient,
    monkeypatch,
) -> None:
    """OME-307 H-1 — a manual connection refresh republish loses to a concurrent committed revoke.

    FEATURE: manual OAuth connection refresh with delete/revoke-race safety.
    STORY: as an operator, when I refresh a connection that another request revokes mid-flight, the
    refresh must fail rather than silently resurrect the revoked connection.
    INVARIANT (OME-307 H-1): complete_active() is a status-fenced conditional UPDATE. When a revoke
    commits on an independent transaction during the refresh's provider-network window, the
    republish UPDATE (WHERE status='active') WAITS on the revoked row's lock, RE-EVALUATES after
    the revoke commits, matches ZERO rows, and returns None -> the route 409s instead of activating.
    """
    account_id = pg_client.get("/v1/auth/me").json()["id"]

    async def _seed_active_oauth_connection(label: str) -> UUID:
        store = OAuthConnectionStore()
        connection_id = uuid4()
        connection = await store.create_pending(
            account_id=account_id,
            provider="anthropic",
            label=label,
            connection_id=connection_id,
        )
        await store.complete(connection, label=label, identity=None)
        return connection_id

    portal = pg_client.portal
    if portal is None:
        raise AssertionError("TestClient portal is not active")
    connection_id: UUID = portal.call(_seed_active_oauth_connection, f"refresh-revoke-{uuid4()}")

    # refresh_connection resolves its strategy from the shared cache; pre-seed a no-op strategy so
    # the provider-network step is a nop and the test isolates the complete_active CAS race. This is
    # the same cache-seeding idiom the single-loop unit test uses.
    class _NoopRefreshStrategy:
        async def refresh_credentials(self) -> None:
            return None

    credential_strategy_cache(_app(pg_client)).get_or_create(
        provider="anthropic",
        auth_type="oauth",
        credential_name=credential_key_for(account_id, connection_id),
        build=lambda: _NoopRefreshStrategy(),
    )

    mark_revoked = OAuthConnectionStore.mark_revoked
    complete_active = OAuthConnectionStore.complete_active
    revoke_holds_row = threading.Event()
    refresh_reached_cas = threading.Event()
    release_revoke = threading.Event()

    async def _holding_revoke(self, connection, *args, **kwargs):
        # Runs inside delete_connection's in_transaction(): mark_revoked UPDATEs the row by PK and
        # holds its row lock until we release and the transaction commits.
        revoked = await mark_revoked(self, connection, *args, **kwargs)
        revoke_holds_row.set()
        if not await asyncio.to_thread(release_revoke.wait, 10):
            raise TimeoutError("connection revoke was not released")
        return revoked

    async def _attempting_complete_active(self, connection, **kwargs):
        # Signal just before the status-fenced UPDATE, which then blocks on the revoke's row lock.
        refresh_reached_cas.set()
        return await complete_active(self, connection, **kwargs)

    monkeypatch.setattr(OAuthConnectionStore, "mark_revoked", _holding_revoke)
    monkeypatch.setattr(OAuthConnectionStore, "complete_active", _attempting_complete_active)
    with ThreadPoolExecutor(max_workers=2) as executor:
        revoking = executor.submit(pg_client.delete, f"/v1/oauth/connections/{connection_id}")
        assert revoke_holds_row.wait(10), "revoke never took the connection-row lock"
        refreshing = executor.submit(
            pg_client.post, f"/v1/oauth/connections/{connection_id}/refresh"
        )
        assert refresh_reached_cas.wait(10), "refresh never reached the complete_active CAS"
        release_revoke.set()
        revoked = revoking.result(timeout=10)
        refreshed = refreshing.result(timeout=10)

    assert revoked.status_code == 204
    assert refreshed.status_code == 409
    assert refreshed.json()["detail"]["code"] == "connection_conflict"
    # Not resurrected: the conditional update matched zero rows, so the row stays revoked.
    assert pg_client.get(f"/v1/oauth/connections/{connection_id}").json()["status"] == "revoked"
    assert _connection_credential(pg_client, account_id, connection_id) is None


def test_profile_refresh_publication_loses_to_committed_delete_on_postgres(
    pg_client: TestClient,
    monkeypatch,
) -> None:
    """OME-307 H-1 — profile refresh success-publish loses to a concurrent committed delete.

    FEATURE: manual profile refresh with delete-race safety.
    INVARIANT (OME-307 H-1): the success branch publishes with upsert(require_present=True). When a
    DELETE commits on an independent transaction during the refresh's provider-network window, the
    publication's require_present CAS WAITS on the profile-index row lock, RE-EVALUATES after the
    delete commits, finds the row ABSENT, and raises ProfileTransitionConflict -> the route 409s
    instead of resurrecting the profile as AUTHENTICATED.
    """
    account_id = pg_client.get("/v1/auth/me").json()["id"]
    name = f"refresh-delete-{uuid4()}"
    assert pg_client.post("/v1/auth/anthropic/profiles", json={"name": name}).status_code == 201

    # refresh_profile builds its strategy via credential_strategy_from (not the shared cache), so
    # substitute a no-op strategy to isolate the require_present publication CAS from the network.
    class _NoopProfileStrategy:
        async def refresh_credentials(self) -> None:
            return None

        async def delete_credentials(self) -> None:
            return None

    monkeypatch.setattr(
        "aigateway.routes.auth.credential_strategy_from",
        lambda *args, **kwargs: _NoopProfileStrategy(),
    )

    index = _app(pg_client).state.profile_index
    remove = index.remove
    upsert = index.upsert
    delete_holds_index = threading.Event()
    refresh_reached_publish = threading.Event()
    release_delete = threading.Event()

    async def _holding_remove(profile_id: str) -> None:
        # Runs inside delete_profile's in_transaction(): remove DELETEs the index row by PK,
        # holding its row lock until we release and the transaction commits.
        await remove(profile_id)
        delete_holds_index.set()
        if not await asyncio.to_thread(release_delete.wait, 10):
            raise TimeoutError("profile delete was not released")

    async def _attempting_upsert(*args, **kwargs):
        # Signal just before require_present publishes, which then blocks on the delete's row lock.
        refresh_reached_publish.set()
        return await upsert(*args, **kwargs)

    monkeypatch.setattr(index, "remove", _holding_remove)
    monkeypatch.setattr(index, "upsert", _attempting_upsert)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(pg_client.delete, f"/v1/auth/anthropic/profiles/{name}")
        assert delete_holds_index.wait(10), "delete never took the profile-index row lock"
        refreshing = executor.submit(pg_client.post, f"/v1/auth/anthropic/profiles/{name}/refresh")
        assert refresh_reached_publish.wait(10), "refresh never reached the require_present publish"
        release_delete.set()
        deleted = deleting.result(timeout=10)
        refreshed = refreshing.result(timeout=10)

    assert deleted.status_code == 204
    assert refreshed.status_code == 409
    assert refreshed.json()["detail"]["code"] == "profile_conflict"
    # Not resurrected: the row stays deleted, so the require_present publication found no row.
    assert pg_client.get(f"/v1/auth/anthropic/profiles/{name}").status_code == 404
    assert _profile_credential(pg_client, account_id, name) is None
