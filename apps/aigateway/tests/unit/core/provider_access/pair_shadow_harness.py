"""Shared seeds and probes for the row-11 shadow identity proof tests (OME-1497, G1 part 3).

# NOTE: `stub_identity` replaces the served plugin's `extract_identity`; the real extractors are
# the OAuth callback's own and are covered by the plugin tests.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access import (
    delete_pair,
    set_pair_api_key,
)
from aigateway.core.provider_access.models import ProviderCredentialSlot

CREDENTIAL_PROVIDER = credential_service_provider_for(ANTHROPIC, PROVIDER)
NEW_KEY = "sk-ant-api03-new-key-0001"
PROFILE = "work"
SUB = "account-sub-1"
# The callback's extractor reads an identity out of the token; this stub maps tokens to subs.
IDENTITY_OF = {"profile-token": SUB, "rotated-profile-token": SUB, "other-token": "account-sub-2"}
# A token the stubbed extractor fails on, carrying it in the exception as Python's codecs do.
RAISING_TOKEN = "raising-token-secret"


def stub_identity(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stub the served plugin's identity extraction; records every credential it was given."""
    seen: list[dict[str, Any]] = []

    async def extract_identity(
        credentials: dict[str, Any], *, http_client_factory: Any | None = None
    ) -> AccountIdentity | None:
        seen.append(credentials)
        token = credentials.get("access_token", "")
        if token == RAISING_TOKEN:
            raise UnicodeEncodeError("ascii", f"Bearer {token}", 7, 8, "ordinal not in range")
        sub = IDENTITY_OF.get(credentials.get("access_token", ""))
        return None if sub is None else AccountIdentity(sub=sub)

    monkeypatch.setattr(ANTHROPIC, "extract_identity", extract_identity)
    return seen


async def _valid() -> None:
    return None


def _put(harness: ProfileBackedHarness, *, validate: Callable[[], Awaitable[None]] = _valid) -> Any:
    return harness.call(
        set_pair_api_key,
        harness.client.app,
        harness.account_id,
        PROVIDER,
        NEW_KEY,
        validate=validate,
    )


def _delete(harness: ProfileBackedHarness) -> Any:
    return harness.call(delete_pair, harness.client.app, harness.account_id, PROVIDER)


def _address(harness: ProfileBackedHarness, name: str) -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, harness.account_id, name)


def _raw(harness: ProfileBackedHarness, locator: dict[str, Any]) -> str | None:
    return harness.blobs.read(locator["service"], locator["account"])


def _shadow(
    harness: ProfileBackedHarness,
    *,
    profile_token: str = "profile-token",
    identity_sub: str | None = SUB,
) -> OAuthConnection:
    """A legacy OAuth login on `none`: a Profile plus a shadow Connection at a UUID locator."""
    harness.seed_profile(name=PROFILE, auth_type="oauth", credential=profile_token)
    connection_id = uuid4()
    connection = harness.call(
        OAuthConnectionStore().create_pending,
        account_id=harness.account_id,
        provider=PROVIDER,
        label=f"conn-{connection_id}",
        connection_id=connection_id,
        credential_provider=CREDENTIAL_PROVIDER,
        credential_locator=None,
    )

    async def activate() -> None:
        await OAuthConnection.filter(id=connection.id).update(
            status="active", identity_sub=identity_sub
        )

    harness.call(activate)
    locator = connection.credential_locator
    harness.blobs.write(
        locator["service"],
        locator["account"],
        json.dumps({"access_token": "shadow-token", "refresh_token": "rt"}),
    )
    assert locator != _address(harness, PROFILE), "a shadow sits at its own UUID locator"
    return connection


def _rows(harness: ProfileBackedHarness) -> list[dict[str, Any]]:
    async def rows() -> list[dict[str, Any]]:
        return await OAuthConnection.filter(account_id=harness.account_id).values(
            "id", "status", "auth_type", "credential_locator", "identity_sub"
        )

    return harness.call(rows)


def _marker(harness: ProfileBackedHarness) -> dict[str, Any] | None:
    async def read() -> list[dict[str, Any]]:
        return await ProviderCredentialSlot.filter(
            account_id=harness.account_id, provider=PROVIDER
        ).values("migration_state", "effective_connection_id", "generation")

    rows = harness.call(read)
    return rows[0] if rows else None


def _documents(harness: ProfileBackedHarness) -> list[str]:
    documents = harness.call(harness.client.app.state.profile_index.list, harness.account_id)
    return sorted(d.name for d in documents)


def _state(harness: ProfileBackedHarness, connection: OAuthConnection) -> tuple[Any, ...]:
    """Everything a refused or superseded mutation must leave untouched."""
    return (
        _marker(harness),
        _rows(harness),
        _documents(harness),
        _raw(harness, _address(harness, PROFILE)),
        _raw(harness, connection.credential_locator),
    )
