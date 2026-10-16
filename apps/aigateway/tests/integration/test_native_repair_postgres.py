"""PostgreSQL races of a native repair of a migrated pair (OME-1209, E1b).

# FEATURE: Stage E spec R6 — the native callback that repairs a migrated pair advances the marker
# first (D14) and then locks its rows in one ascending id order. On PostgreSQL (READ COMMITTED) the
# marker row lock decides a race; SQLite's single writer cannot show it.
# INVARIANT: a repair and a racing writer never both commit; nothing deadlocks; the pair never
# names a row a concurrent failure already broke.
# WHY bound: fixtures and helpers are bound from the S2'c module; run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
KEY = "sk-ant-api03-postgres-repair-key-2468"


def _broken_pair(client: TestClient, account_id: str, name: str) -> UUID:
    """A migrated OAuth pair whose effective row a refresh failure has broken."""
    effective = backing._seed(
        client, account_id, name, auth_type="oauth", blob=backing._oauth_blob("old-tok")
    )
    _mark_error(client, account_id, effective)
    return effective


def _mark_error(client: TestClient, account_id: str, connection_id: UUID | str) -> None:
    row = backing._connection(client, account_id, connection_id)
    backing._call(client, OAuthConnectionStore().mark_error, row, "refresh rejected")


def _start(client: TestClient, label: str, token: str) -> dict[str, Any]:
    backing._app(client).state.anthropic_http_factory = backing._token_factory(token)
    started = client.post("/v1/oauth/connections", json={"provider": PROVIDER, "label": label})
    assert started.status_code == 201, started.text
    return started.json()


def _callback(client: TestClient, state: str) -> Any:
    return client.get(
        f"/v1/auth/{PROVIDER}/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )


def _access_token(client: TestClient, account_id: str, connection_id: UUID | str) -> Any:
    locator = backing._connection(client, account_id, connection_id).credential_locator
    store = backing._app(client).state.credential_store
    blob = backing._call(client, store.read, locator["service"], locator["account"])
    return None if blob is None else json.loads(blob).get("access_token")


async def _has_label(account_id: str, label: str) -> bool:
    return await OAuthConnection.filter(
        account_id=account_id, provider=PROVIDER, label=label
    ).exists()


def _held_callback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, state: str, racer: Any
) -> tuple[Any, Any]:
    """Hold the callback on its marker advance, run `racer`, then let the callback commit."""
    hold = backing._MarkerHold(monkeypatch, holds=lambda index, _kw: index == 0)
    with ThreadPoolExecutor(max_workers=2) as executor:
        completing = executor.submit(_callback, client, state)
        assert hold.held.wait(20), "the callback never advanced the marker"
        racing = executor.submit(racer)
        hold.attempted.wait(5)
        hold.release.set()
        return completing.result(timeout=30), racing.result(timeout=30)


def test_a_repair_holding_the_marker_makes_a_racing_key_takeover_lose_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = backing._account_id(pg_client)
    old = _broken_pair(pg_client, account_id, backing._fresh_name())
    repair = _start(pg_client, "work", "new-tok")

    def take_over() -> Any:
        return pg_client.post(
            "/v1/oauth/connections/api-key",
            json={"provider": PROVIDER, "label": "key", "api_key": KEY},
        )

    completed, taken = _held_callback(pg_client, monkeypatch, repair["state"], take_over)

    assert completed.status_code == 200, completed.text
    assert taken.status_code == 409, taken.text
    assert taken.json()["detail"]["code"] == "connection_conflict"
    new = repair["connection_id"]
    assert str(backing._marker(pg_client, account_id).effective_connection_id) == new
    assert backing._connection(pg_client, account_id, old).status == "revoked"
    assert backing._connection(pg_client, account_id, new).status == "active"
    assert _access_token(pg_client, account_id, new) == "new-tok"
    assert not backing._call(pg_client, _has_label, account_id, "key")


def test_a_repair_and_a_delete_of_the_replaced_row_do_not_deadlock_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = backing._account_id(pg_client)
    old = _broken_pair(pg_client, account_id, backing._fresh_name())
    repair = _start(pg_client, "work", "new-tok")

    def delete_old() -> Any:
        return pg_client.delete(f"/v1/oauth/connections/{old}")

    completed, deleted = _held_callback(pg_client, monkeypatch, repair["state"], delete_old)

    pair = backing._marker(pg_client, account_id)
    new = repair["connection_id"]
    if completed.status_code == 200:
        # The repair committed first: the delete found its row already retired.
        assert deleted.status_code in (404, 409), deleted.text
        assert str(pair.effective_connection_id) == new
        assert backing._connection(pg_client, account_id, new).status == "active"
        assert _access_token(pg_client, account_id, new) == "new-tok"
    else:
        # The delete won the pair: the repair published nothing.
        assert completed.status_code == 409, completed.text
        assert deleted.status_code in (200, 204), deleted.text
        assert pair.effective_connection_id is None
        assert backing._connection(pg_client, account_id, new).status == "revoked"
    assert backing._connection(pg_client, account_id, old).status == "revoked"


def test_a_sibling_broken_after_its_lookup_is_not_made_effective_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: the identity lookup runs before the transaction; a refresh failure that commits before
    # the promotion locks the sibling must make the promotion refuse, not publish an `error` row.
    # WHY only before: a failure that arrives AFTER the promotion's marker update waits on the FK
    # lock the marker takes on the sibling and lands after the commit — that is the stale-refresh
    # class of every in-place re-key on a migrated pair, outside this test.
    account_id = backing._account_id(pg_client)
    name = backing._fresh_name()
    old = backing._seed(
        pg_client, account_id, name, auth_type="oauth", blob=backing._oauth_blob("old-tok")
    )

    async def same_identity(*_args: Any, **_kwargs: Any) -> AccountIdentity:
        return AccountIdentity(sub="user-1")

    monkeypatch.setattr(AnthropicProviderPlugin, "extract_identity", same_identity)
    sibling_flow = _start(pg_client, "sibling", "sibling-tok")
    assert _callback(pg_client, sibling_flow["state"]).status_code == 200
    sibling = sibling_flow["connection_id"]
    _mark_error(pg_client, account_id, old)
    before = backing._marker(pg_client, account_id)
    repair = _start(pg_client, "work", "new-tok")
    find_by_identity = OAuthConnectionStore.find_by_identity

    async def breaks_after_lookup(self: Any, *args: Any, **kwargs: Any) -> Any:
        found = await find_by_identity(self, *args, **kwargs)
        if found is not None and str(found.id) == sibling:
            # A committed write on its own connection, before the repair's transaction.
            await OAuthConnectionStore().mark_error(
                await OAuthConnection.get(id=found.id), "refresh rejected"
            )
        return found

    monkeypatch.setattr(OAuthConnectionStore, "find_by_identity", breaks_after_lookup)

    completed = _callback(pg_client, repair["state"])

    assert completed.status_code == 409, completed.text
    assert completed.json()["detail"]["code"] == "connection_conflict"
    assert backing._marker(pg_client, account_id) == before
    assert backing._connection(pg_client, account_id, sibling).status == "error"
    assert _access_token(pg_client, account_id, sibling) == "sibling-tok"
    assert backing._connection(pg_client, account_id, repair["connection_id"]).status == "revoked"
