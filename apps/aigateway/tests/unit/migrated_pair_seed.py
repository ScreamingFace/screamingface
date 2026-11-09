"""Seed a migrated pair whose effective Connection sits at a credential's name address (E4a).

# FEATURE: Stage E plan §3 E4a — resolve reads no Profile document, so a test that wants "a stored
# credential named `name` in `state`" seeds a Connection-backed authority instead: an effective
# Connection whose locator IS the `name` address, in the status `state` maps to, and a `migrated`
# marker naming it. Credential names, cache keys and blobs stay exactly what the Profile-era test
# already used; since E5c (OME-1138) the state is the test-local `SeedState`.
# WHY not "what the backfill writes" for every state: the backfill migrates only an authenticated
# Profile-only pair this way; a pending or errored seed is an effective Connection that later
# went pending or errored, a state the runtime reaches on its own.
# INVARIANT: re-seeding the same address moves the SAME Connection (status and auth type) instead
# of adding a row, so the pair keeps one candidate and its context stamp's Connection id.
# WHY synchronous over the client's portal: the Connection and marker rows are Tortoise writes,
# which must run on the app's own loop.
"""

from __future__ import annotations

import json
import time
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from aigateway.core.auth_types import AuthType
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access import PairAuthorityStore
from tests.unit.seed_state import SeedState


def seed_migrated_pair(
    client: Any,
    account_id: str,
    provider: str,
    *,
    name: str = "default",
    state: SeedState = SeedState.AUTHENTICATED,
    auth_type: AuthType = "oauth",
    credential: str | None = None,
) -> UUID:
    """The pair's effective Connection at the `name` address; returns its id.

    `credential`, when given, is written to that address (an OAuth access token or an API key).
    """
    seed = partial(
        _seed,
        client.app,
        account_id,
        provider,
        name=name,
        state=state,
        auth_type=auth_type,
        credential=credential,
    )
    return client.portal.call(seed)


def disconnect_migrated_pair(client: Any, account_id: str, provider: str) -> None:
    """What a D18 DELETE leaves: the effective Connection revoked, the marker's reference null."""
    client.portal.call(partial(_disconnect, account_id, provider))


async def _seed(
    app: Any,
    account_id: str,
    provider: str,
    *,
    name: str,
    state: SeedState,
    auth_type: AuthType,
    credential: str | None,
) -> UUID:
    plugin = app.state.providers.get(provider)
    credential_provider = credential_service_provider_for(plugin, provider)
    locator = credential_locator_for(credential_provider, account_id, name)
    store = OAuthConnectionStore()
    live = await store.list(account_id, provider=provider)
    connection = next((c for c in live if c.credential_locator == locator), None)
    if connection is None:
        connection = await store.create_pending(
            account_id=account_id,
            provider=provider,
            label=name,
            connection_id=uuid4(),
            credential_provider=credential_provider,
            credential_locator=locator,
        )
    if connection.auth_type != auth_type:
        connection = await store.set_auth_type(connection, auth_type) or connection
    connection = await _move(store, connection, state, label=name)
    markers = PairAuthorityStore()
    current = await markers.read(account_id, provider)
    if (current.migration_state, current.effective_connection_id) != ("migrated", connection.id):
        await markers.advance(
            account_id,
            provider,
            expected_generation=current.generation,
            migration_state="migrated",
            effective_connection_id=connection.id,
        )
    if credential is not None:
        await app.state.credential_store.write(
            locator["service"], locator["account"], _blob(auth_type, credential)
        )
    return connection.id


async def _move(
    store: OAuthConnectionStore, connection: OAuthConnection, state: SeedState, *, label: str
) -> OAuthConnection:
    if state is SeedState.PENDING:
        if connection.status != "pending":
            await OAuthConnection.filter(id=connection.id).update(status="pending")
        return await store.get(connection.account_id, connection.id) or connection
    if connection.status != "active":
        connection = await store.complete(connection, label=label, identity=None)
    if state is SeedState.ERROR:
        # WHY via active: `mark_error` transitions only a usable row, as the read path does.
        connection = await store.mark_error(connection, "seeded error") or connection
    return connection


async def _disconnect(account_id: str, provider: str) -> None:
    markers = PairAuthorityStore()
    current = await markers.read(account_id, provider)
    store = OAuthConnectionStore()
    if current.effective_connection_id is not None:
        effective = await store.get(account_id, current.effective_connection_id)
        if effective is not None:
            await store.mark_revoked(effective)
    await markers.advance(
        account_id,
        provider,
        expected_generation=current.generation,
        migration_state="migrated",
        effective_connection_id=None,
    )


def _blob(auth_type: AuthType, credential: str) -> str:
    if auth_type == "api_key":
        return json.dumps({"auth_type": "api_key", "api_key": credential})
    expires_at_ms = int(time.time() * 1000) + 3_600_000
    token = {"access_token": credential, "refresh_token": "rt", "token_type": "Bearer"}
    return json.dumps({**token, "expires_at_ms": expires_at_ms})


__all__ = ["disconnect_migrated_pair", "seed_migrated_pair"]
