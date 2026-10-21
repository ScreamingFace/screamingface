"""The D18 PUT's publication step — a refused publication writes nothing.

# FEATURE: OME-1138 D18 — `set_pair_api_key` publishes through
# `ConnectionBackedCredentialAdmin.publish_api_key`. These are the publication's own contracts,
# pinned on the live entry point (OME-1209 E3b retired the Profile-era admin ops that carried
# them until then).
# INVARIANT (§5.3): marker, row and credential publish in one transaction; a refused or lost
# publication writes nothing — no marker, row, document or blob changes.
# WHY only G3 remains (OME-1209 E4b): G1 (an index conflict inside the PUT), G2 (index row before
# the credential), G4 (sibling documents mirror the key) and G5 (the shared-address guard on a
# document) pinned the compatibility mirror, which E4b removes. Successors:
# `test_no_profile_writer.py` (the PUT writes, removes and reads no document) and
# `test_connection_backed_shared_addresses.py` (a blob stays while a live Connection serves it).
"""

from __future__ import annotations

from typing import Any

import pytest
from provider_access_harness import PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.provider_access import UnsupportedAuthMode, set_pair_api_key
from aigateway.core.provider_access.models import ProviderCredentialSlot

NEW_KEY = "sk-ant-api03-new-key-0001"
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


def _state(harness: ProfileBackedHarness) -> tuple[Any, ...]:
    """Everything a refused publication must leave untouched, across every provider."""

    async def read() -> tuple[Any, ...]:
        markers = await ProviderCredentialSlot.filter(account_id=harness.account_id).values(
            "provider", "migration_state", "effective_connection_id", "generation"
        )
        rows = await OAuthConnection.filter(account_id=harness.account_id).values(
            "id", "provider", "status", "auth_type"
        )
        index = ProfileIndexStore(credential_store=harness.client.app.state.credential_store)
        documents = await index.list(harness.account_id)
        return (
            markers,
            rows,
            sorted((d.provider, d.name, d.auth_type, d.state.value) for d in documents),
        )

    return harness.call(read)


# --- G3: a provider without an API-key strategy ---------------------------------------------


def test_a_provider_without_an_api_key_strategy_is_refused_and_writes_nothing(harness) -> None:
    before = _state(harness)

    with pytest.raises(UnsupportedAuthMode) as refused:
        _put(harness, provider=CODEX)

    assert (refused.value.auth_mode, refused.value.provider) == ("api_key", CODEX)
    assert _state(harness) == before
