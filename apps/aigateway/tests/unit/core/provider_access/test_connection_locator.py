"""Locator-authoritative credential addressing for Connections (OME-1208, Stage B S1).

# FEATURE: "reads without re-entry" (card v4, Stage B Target) — a migrated Connection reads the
# blob its `credential_locator` names, which is the blob the legacy Profile already addresses, so
# the encrypted credential is neither decrypted for transfer nor re-entered; a new Connection keeps
# its UUID locator and reads exactly what it reads today.
# INVARIANT: the locator, not the Connection id, decides which blob a strategy reads AND writes; a
# malformed locator falls back to today's UUID-derived name, which addresses a blob unique to that
# Connection, so no other pair's secret can ever be served through it.
# AIDEV-NOTE: the address format `aigateway:<credential-provider>:<credential-name>` is owned by
# each plugin's `credential_service_for` and mirrored by the core's `credential_locator_for`;
# `test_a_profile_locator_names_the_legacy_profile_blob` pins the round trip so the migration tool
# (S4) may write `credential_locator_for(provider, account, profile_name)` and know it points at
# the Profile's blob.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

import pytest

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
    credential_locator_for,
)
from aigateway.core.profile_models import AuthType, credential_name_for
from aigateway.core.provider_access.connection_locator import (
    credential_name_from_locator,
    credential_strategy_for_connection,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

PROVIDER = "anthropic"
ACCOUNT = "11111111-1111-1111-1111-111111111111"
CONNECTION = UUID("22222222-2222-2222-2222-222222222222")


class _Addressed(Protocol):
    """The blob address a built strategy reports — not part of the `CredentialStrategy` port."""

    def credential_service(self) -> str: ...


def _name(locator: Mapping[str, Any] | None, *, credential_provider: str = PROVIDER) -> str:
    return credential_name_from_locator(
        locator,
        credential_provider=credential_provider,
        account_id=ACCOUNT,
        connection_id=CONNECTION,
    )


# --- the pure derivation --------------------------------------------------------------------------


def test_a_uuid_locator_names_todays_connection_blob() -> None:
    locator = credential_locator_for(PROVIDER, ACCOUNT, CONNECTION)
    assert _name(locator) == credential_key_for(ACCOUNT, CONNECTION)


def test_a_profile_locator_names_the_legacy_profile_blob() -> None:
    # STORY: as alice, after migration my anthropic Connection reads the blob my Profile wrote — I
    # never re-enter the secret.
    locator = credential_locator_for(PROVIDER, ACCOUNT, "default")
    name = _name(locator)
    assert name == credential_name_for(ACCOUNT, "default")
    # INVARIANT: the address round-trips through the plugin's own service naming.
    assert credential_service_for(name) == locator["service"]


def test_the_locator_wins_over_the_connection_id() -> None:
    locator = credential_locator_for(PROVIDER, ACCOUNT, "work")
    assert _name(locator) == credential_name_for(ACCOUNT, "work")
    assert _name(locator) != credential_key_for(ACCOUNT, CONNECTION)


def test_a_credential_provider_alias_is_honoured() -> None:
    # WHY: `gemini-cli` stores under `aigateway:gemini:…` — its `credential_service_provider`.
    locator = credential_locator_for("gemini", ACCOUNT, "default")
    assert _name(locator, credential_provider="gemini") == credential_name_for(ACCOUNT, "default")


@pytest.mark.parametrize(
    "locator",
    [
        None,
        {},
        {"service": f"aigateway:codex:{credential_name_for(ACCOUNT, 'default')}"},
        {"service": f"aigateway:{PROVIDER}:"},
        {"service": 5},
        {
            "service": credential_service_for(credential_name_for(ACCOUNT, "default")),
            "account": "x",
        },
        {"account": "default"},
    ],
    ids=[
        "absent",
        "empty",
        "other-provider",
        "empty-name",
        "non-string",
        "non-default-slot",
        "no-service",
    ],
)
def test_a_malformed_locator_falls_back_to_the_connections_own_blob(
    locator: Mapping[str, Any] | None,
) -> None:
    # INVARIANT: the fallback addresses a blob unique to THIS Connection — never another pair's.
    assert _name(locator) == credential_key_for(ACCOUNT, CONNECTION)


# --- the strategy factory on the real app -----------------------------------------------------


def _oauth_blob(access_token: str) -> str:
    expires_at_ms = int(time.time() * 1000) + 3_600_000
    token = {"access_token": access_token, "refresh_token": "rt", "token_type": "Bearer"}
    return json.dumps({**token, "expires_at_ms": expires_at_ms})


def _connection(
    client: Any,
    account_id: str,
    *,
    locator: dict[str, str] | None = None,
    auth_type: AuthType = "oauth",
) -> OAuthConnection:
    """An active Connection; with `locator`, one the migration tool has repointed (S4's write)."""

    async def create() -> OAuthConnection:
        store = OAuthConnectionStore()
        pending = await store.create_pending(
            account_id=account_id, provider=PROVIDER, label="default", connection_id=uuid4()
        )
        connection = await store.complete(pending, label="default", identity=None)
        if auth_type != "oauth":
            retagged = await store.set_auth_type(connection, auth_type)
            assert retagged is not None
            connection = retagged
        if locator is not None:
            connection.credential_locator = locator
            await connection.save(update_fields=["credential_locator"])
        return connection

    return cast(OAuthConnection, client.portal.call(create))


def test_the_factory_reads_the_profile_blob_through_a_migrated_connection(
    authenticated_client: Any, credential_blobs: Any
) -> None:
    client = authenticated_client
    account_id = client.get("/v1/auth/me").json()["id"]
    locator = credential_locator_for(PROVIDER, account_id, "default")
    credential_blobs.write(locator["service"], locator["account"], _oauth_blob("profile-token"))
    connection = _connection(client, account_id, locator=locator)
    plugin = client.app.state.providers.get(PROVIDER)

    strategy = credential_strategy_for_connection(
        client.app, plugin, PROVIDER, connection, account_id=account_id
    )

    assert strategy is not None
    assert cast(_Addressed, strategy).credential_service() == locator["service"]
    headers = client.portal.call(strategy.get_authorization_header)
    assert headers["Authorization"] == "Bearer profile-token"


def test_the_factory_keeps_todays_address_for_a_uuid_locator(
    authenticated_client: Any, credential_blobs: Any
) -> None:
    client = authenticated_client
    account_id = client.get("/v1/auth/me").json()["id"]
    connection = _connection(client, account_id)
    own = credential_locator_for(PROVIDER, account_id, connection.id)
    assert connection.credential_locator == own
    credential_blobs.write(own["service"], own["account"], _oauth_blob("connection-token"))
    plugin = client.app.state.providers.get(PROVIDER)

    strategy = credential_strategy_for_connection(
        client.app, plugin, PROVIDER, connection, account_id=account_id
    )

    assert strategy is not None
    assert cast(_Addressed, strategy).credential_service() == credential_service_for(
        credential_key_for(account_id, connection.id)
    )
    headers = client.portal.call(strategy.get_authorization_header)
    assert headers["Authorization"] == "Bearer connection-token"


def test_the_factory_follows_the_persisted_auth_type(
    authenticated_client: Any, credential_blobs: Any
) -> None:
    client = authenticated_client
    # INVARIANT: the auth type is never caller-declared — it comes from the stored Connection.
    account_id = client.get("/v1/auth/me").json()["id"]
    locator = credential_locator_for(PROVIDER, account_id, "default")
    credential_blobs.write(
        locator["service"],
        locator["account"],
        json.dumps({"auth_type": "api_key", "api_key": "profile-key"}),
    )
    connection = _connection(client, account_id, locator=locator, auth_type="api_key")
    plugin = client.app.state.providers.get(PROVIDER)

    strategy = credential_strategy_for_connection(
        client.app, plugin, PROVIDER, connection, account_id=account_id
    )

    assert strategy is not None
    assert cast(_Addressed, strategy).credential_service() == locator["service"]
    headers = client.portal.call(strategy.get_authorization_header)
    assert any("profile-key" in value for value in headers.values())
