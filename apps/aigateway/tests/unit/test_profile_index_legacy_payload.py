"""A pre-E3b ProfileIndex remains readable and mutable without a data migration."""

from __future__ import annotations

import json

import pytest

from aigateway.core.credential_names import profile_id_for
from aigateway.core.profile_index import INDEX_CREDENTIAL_SERVICE, ProfileIndexStore
from aigateway.core.profile_models import Profile

ACCOUNT_ID = "legacy-account"


def _index_account(account_id: str) -> str:
    return f"account:{account_id}"


@pytest.mark.asyncio
async def test_a_legacy_oauth_generation_map_is_ignored_and_dropped_on_mutation(
    credential_blobs,
) -> None:
    """INVARIANT: E3b needs no migration for ProfileIndex documents already stored at rest."""
    profile = Profile(
        id=profile_id_for(ACCOUNT_ID, "anthropic", "default"),
        account_id=ACCOUNT_ID,
        provider="anthropic",
        name="default",
    )
    legacy = {
        "version": 1,
        "profiles": [profile.model_dump(mode="json")],
        "oauth_generations": {profile.id: 7},
    }
    credential_blobs.write(
        INDEX_CREDENTIAL_SERVICE,
        _index_account(ACCOUNT_ID),
        json.dumps(legacy),
    )
    store = ProfileIndexStore(credential_store=credential_blobs.store)

    loaded = await store.read(ACCOUNT_ID)
    assert loaded.profiles == [profile]

    profile.account_label = "updated"
    await store.upsert(profile)

    persisted = json.loads(
        credential_blobs.read(INDEX_CREDENTIAL_SERVICE, _index_account(ACCOUNT_ID))
    )
    assert persisted["profiles"][0]["account_label"] == "updated"
    assert "oauth_generations" not in persisted
