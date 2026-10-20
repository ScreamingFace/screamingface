"""The D18 PUT's publication step — refusals, write order, sibling mirrors, the shared blob guard.

# FEATURE: OME-1138 D18 — `set_pair_api_key` publishes through
# `ConnectionBackedCredentialAdmin.publish_api_key`. These are the publication's own contracts,
# pinned on the live entry point (OME-1209 E3b retired the Profile-era admin ops that carried
# them until then).
# INVARIANT (§5.3): index row first, credential second, one transaction; a refused or lost
# publication writes nothing — no marker, row, document or blob changes.
# INVARIANT (D-R1-3): every other document of the pair mirrors the one API key and keeps its
# `defaults`, so an R1 rollback serves the same credential from whichever name it reads.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.credential_blob.store import CredentialBlobMutationConflict
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import INDEX_CREDENTIAL_SERVICE, ProfileTransitionConflict
from aigateway.core.profile_models import ProfileDefaults, ProfileState
from aigateway.core.provider_access import (
    PairAuthorityStore,
    UnsupportedAuthMode,
    WriteConflict,
    set_pair_api_key,
)
from aigateway.core.provider_access.connection_admin import ConnectionBackedCredentialAdmin
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.provider_access.profile_admin import addressed_by_a_live_connection

CREDENTIAL_PROVIDER = credential_service_provider_for(ANTHROPIC, PROVIDER)
NEW_KEY = "sk-ant-api03-new-key-0001"
OLD_KEY = "sk-ant-api03-old-key-0002"
CODEX = "codex"


@pytest.fixture
def harness(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


async def _valid() -> None:
    return None


def _put(harness: ProfileBackedHarness, provider: str = PROVIDER) -> Any:
    return harness.call(
        set_pair_api_key,
        harness.client.app,
        harness.account_id,
        provider,
        NEW_KEY,
        validate=_valid,
    )


def _address(harness: ProfileBackedHarness, name: str) -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, harness.account_id, name)


def _blob(harness: ProfileBackedHarness, name: str) -> str | None:
    locator = _address(harness, name)
    raw = harness.blobs.read(locator["service"], locator["account"])
    return None if raw is None else json.loads(raw).get("api_key")


def _state(harness: ProfileBackedHarness) -> tuple[Any, ...]:
    """Everything a refused publication must leave untouched, across every provider."""

    async def read() -> tuple[Any, ...]:
        markers = await ProviderCredentialSlot.filter(account_id=harness.account_id).values(
            "provider", "migration_state", "effective_connection_id", "generation"
        )
        rows = await OAuthConnection.filter(account_id=harness.account_id).values(
            "id", "provider", "status", "auth_type"
        )
        documents = await harness.client.app.state.profile_index.list(harness.account_id)
        return (
            markers,
            rows,
            sorted((d.provider, d.name, d.auth_type, d.state.value) for d in documents),
        )

    return harness.call(read)


# --- G1: an index conflict inside the publication -----------------------------------------------


@pytest.mark.parametrize(
    ("raised", "kind"),
    [
        (ProfileTransitionConflict("the document changed under the write"), "superseded"),
        (CredentialBlobMutationConflict("forced contention"), "retry_exhausted"),
    ],
    ids=["transition-conflict", "retry-exhausted"],
)
def test_an_index_conflict_inside_the_put_is_a_write_conflict_that_writes_nothing(
    harness, monkeypatch, raised, kind
) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    before = _state(harness)

    async def conflict(*_args: Any, **_kwargs: Any) -> None:
        raise raised

    monkeypatch.setattr(harness.client.app.state.profile_index, "upsert", conflict)

    with pytest.raises(WriteConflict) as refused:
        _put(harness)

    assert (refused.value.kind, refused.value.subject) == (kind, "profile")
    assert (refused.value.provider, refused.value.requested) == (PROVIDER, "work")
    assert str(raised) not in str(refused.value)
    assert _state(harness) == before
    assert _blob(harness, "work") == OLD_KEY


# --- G2: the write order --------------------------------------------------------------------


def test_the_put_writes_the_index_row_before_the_credential(harness, monkeypatch) -> None:
    calls: list[str] = []
    index = harness.client.app.state.profile_index
    store = harness.client.app.state.credential_store
    real_upsert = index.upsert
    real_write, real_mutate = store.write, store.mutate

    async def upsert(*args: Any, **kwargs: Any) -> None:
        calls.append("index")
        await real_upsert(*args, **kwargs)

    async def write(service: str, account: str, value: str) -> None:
        calls.append("credential")
        await real_write(service, account, value)

    async def mutate(service: str, account: str, mutator: Any) -> None:
        # The index store publishes through `mutate`; only a NON-index service is the credential.
        calls.append("index" if service == INDEX_CREDENTIAL_SERVICE else "credential")
        await real_mutate(service, account, mutator)

    monkeypatch.setattr(index, "upsert", upsert)
    monkeypatch.setattr(store, "write", write)
    monkeypatch.setattr(store, "mutate", mutate)

    _put(harness)

    assert "credential" in calls
    first_credential = calls.index("credential")
    assert first_credential > 0
    assert calls[:first_credential] == ["index"] * first_credential


# --- G3: a provider without an API-key strategy ---------------------------------------------


def test_a_provider_without_an_api_key_strategy_is_refused_and_writes_nothing(harness) -> None:
    before = _state(harness)

    with pytest.raises(UnsupportedAuthMode) as refused:
        _put(harness, provider=CODEX)

    assert (refused.value.auth_mode, refused.value.provider) == ("api_key", CODEX)
    assert _state(harness) == before


# --- G4: sibling documents mirror the one key -----------------------------------------------


def test_the_publication_mirrors_the_key_into_every_sibling_and_keeps_its_defaults(
    harness,
) -> None:
    defaults = ProfileDefaults(model="anthropic/claude-sonnet-4-5", max_tokens=1024)
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    harness.seed_profile(
        name="alias",
        auth_type="oauth",
        state=ProfileState.ERROR,
        defaults=defaults,
        credential=None,
    )
    pair = harness.call(PairAuthorityStore().read, harness.account_id, PROVIDER)
    admin = ConnectionBackedCredentialAdmin(harness.client.app)

    connection, mirror = harness.call(
        admin.publish_api_key,
        harness.account_id,
        PROVIDER,
        ANTHROPIC,
        pair=pair,
        reuse=None,
        name="work",
        raw_api_key=NEW_KEY,
        expected_live=frozenset(),
    )

    index = harness.client.app.state.profile_index
    alias = harness.call(index.get, harness.account_id, PROVIDER, "alias")
    assert alias is not None
    assert (alias.auth_type, alias.state) == ("api_key", ProfileState.AUTHENTICATED)
    assert alias.account_label == f"API key ····{NEW_KEY[-4:]}"
    assert alias.defaults == defaults
    assert (mirror.name, mirror.auth_type) == ("work", "api_key")
    assert connection.credential_locator == _address(harness, "work")
    assert _blob(harness, "work") == NEW_KEY
    # One credential: the alias document's own address holds nothing.
    assert _blob(harness, "alias") is None


# --- G5: the shared-address guard -----------------------------------------------------------


def test_only_a_live_connection_at_the_profile_address_keeps_the_legacy_blob(harness) -> None:
    async def create() -> OAuthConnection:
        return await OAuthConnectionStore().create_api_key(
            account_id=harness.account_id,
            provider=PROVIDER,
            label="at-work",
            connection_id=uuid4(),
            credential_provider=CREDENTIAL_PROVIDER,
            credential_locator=_address(harness, "work"),
        )

    def addressed(name: str) -> bool:
        return harness.call(
            addressed_by_a_live_connection, ANTHROPIC, PROVIDER, harness.account_id, name
        )

    connection = harness.call(create)

    assert addressed("work") is True
    assert addressed("other") is False

    async def revoke() -> None:
        await OAuthConnection.filter(id=connection.id).update(status="revoked")

    harness.call(revoke)

    assert addressed("work") is False
