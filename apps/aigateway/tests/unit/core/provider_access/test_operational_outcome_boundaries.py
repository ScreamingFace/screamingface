from __future__ import annotations

from typing import Any

import pytest
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER

from aigateway.core.oauth.store import credential_key_for
from aigateway.core.profile_models import credential_name_for
from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    Selector,
    TargetReauthRequired,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings


@pytest.fixture
def migrated(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def _resolve(harness: ConnectionBackedHarness, *, plugin: Any = ANTHROPIC) -> Any:
    return harness.call(
        harness.access.resolve,
        harness.account_id,
        PROVIDER,
        Selector.from_header(None),
        plugin=plugin,
    )


def test_operational_register_uses_the_strategy_credential_slot(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile(auth_type="api_key", credential="tok")
    name = credential_name_for(migrated.account_id, "default")
    service = credential_service_for(name)
    raw = migrated.blobs.read_raw(service, "default")
    assert raw is not None
    migrated.blobs.write_raw(service, "account-custom", raw, ciphertext_version="v1")
    migrated.blobs.delete(service, "default")
    plugin = AnthropicProviderPlugin(
        settings=AnthropicPluginSettings(keychain_account="account-custom")
    )

    target = _resolve(migrated, plugin=plugin)
    observation = migrated.call(
        migrated.access.begin_dispatch, target, plugin=plugin, provider=PROVIDER
    )

    state = migrated.call(
        migrated.client.app.state.credential_store.operational_state,
        service,
        "account-custom",
    )
    assert observation is not None
    assert state is not None
    assert observation.blob_id == state.blob_id


def test_operational_state_read_failure_becomes_a_typed_store_refusal(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated.seed_profile(auth_type="api_key", credential="tok")

    async def unavailable(_service: str, _account: str) -> None:
        raise RuntimeError("database secret")

    monkeypatch.setattr(
        migrated.client.app.state.credential_store, "operational_state", unavailable
    )

    with pytest.raises(CredentialStoreUnavailable):
        _resolve(migrated)


def test_needs_reauth_evicts_the_strategy_and_invalidates_its_session(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile(auth_type="api_key", credential="tok")
    target = _resolve(migrated)
    observation = migrated.call(
        migrated.access.begin_dispatch, target, plugin=ANTHROPIC, provider=PROVIDER
    )
    assert observation is not None

    migrated.call(
        migrated.access.record_dispatch_outcome,
        target,
        observation,
        "needs_reauth",
        {"code": "auth_required"},
        plugin=ANTHROPIC,
    )

    assert migrated.evicted() == [target.credential_name]
    assert migrated.invalidated() == [target.credential_name]
    with pytest.raises(TargetReauthRequired):
        _resolve(migrated)


def test_dispatch_observation_requires_the_effective_connection(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile(auth_type="api_key", credential="tok")
    other_id = migrated.seed_connection(label="other", auth_type="api_key", credential="other")
    target = migrated.call(
        migrated.access.resolve,
        migrated.account_id,
        PROVIDER,
        Selector.from_header("other"),
        plugin=ANTHROPIC,
    )

    observation = migrated.call(
        migrated.access.begin_dispatch, target, plugin=ANTHROPIC, provider=PROVIDER
    )
    other_state = migrated.call(
        migrated.client.app.state.credential_store.operational_state,
        credential_service_for(credential_key_for(migrated.account_id, other_id)),
        "default",
    )

    assert observation is None
    assert other_state is not None
    assert other_state.next_dispatch_sequence == 0


def test_oauth_listing_never_reads_the_api_key_operational_register(
    migrated: ConnectionBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrated.seed_profile(auth_type="oauth", credential="tok")

    async def forbidden(_service: str, _account: str) -> None:
        raise AssertionError("OAuth listing read the API-key operational register")

    monkeypatch.setattr(migrated.client.app.state.credential_store, "operational_state", forbidden)

    rows = migrated.call(migrated.access.availability, migrated.account_id)

    assert {row.provider: row.status for row in rows}[PROVIDER] == "connected"
