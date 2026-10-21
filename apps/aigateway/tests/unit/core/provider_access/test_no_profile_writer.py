"""No runtime path writes or removes a Profile document (OME-1209, Stage E, E4b; spec §9 Q10).

# FEATURE: Stage E plan §3 E4b — the native OAuth callback, the native key replacement and delete,
# and the D18 PUT and DELETE change only the pair marker, its Connections and their blobs. The
# legacy index is offline-only until E5: a document left behind is neither updated nor removed.
# STORY: as an operator, the credential I manage is the Connection; a leftover Profile document
# is history the E5 cleanup reads, not state a request rewrites.
# INVARIANT: none of these paths calls a `ProfileIndexStore` write (a class-level spy sees every
# instance), and a seeded document reads back exactly as it was.
# INVARIANT (D5, D11): a blob goes with its last live Connection; a document is no owner.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import uuid4

import pytest
from connection_backed_admin_probes import blob_at_profile_address, document, marker
from connection_backed_harness import ConnectionBackedHarness
from connection_backed_oauth_probes import callback, use_tokens
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import PairMutation, delete_pair, set_pair_api_key

CREDENTIAL_PROVIDER = credential_service_provider_for(ANTHROPIC, PROVIDER)
NEW_KEY = "sk-ant-api03-e4b-new-key-0001"
OLD_KEY = "sk-ant-api03-e4b-old-key-0002"
_WRITES = ("upsert", "stamp_refreshed", "mark_authenticated_error", "remove")


@pytest.fixture
def legacy(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> Any:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> Any:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


def watch_index_writes(h: Any) -> list[str]:
    """From now on, every `ProfileIndexStore` write on ANY instance, by method name, in order.

    # WHY after seeding: the harness seeds its documents through the same `upsert`.
    """
    writes: list[str] = []

    def spy(name: str, real: Callable[..., Coroutine[Any, Any, Any]]) -> Any:
        async def write(*args: Any, **kwargs: Any) -> Any:
            writes.append(name)
            return await real(*args, **kwargs)

        return write

    for name in _WRITES:
        h.monkeypatch.setattr(ProfileIndexStore, name, spy(name, getattr(ProfileIndexStore, name)))
    return writes


def documents(h: Any) -> list[dict[str, Any]]:
    index = ProfileIndexStore(credential_store=h.blobs.store)
    return [d.model_dump(mode="json") for d in h.call(index.list, h.account_id)]


def address(h: Any, name: str) -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, h.account_id, name)


def api_key_at(h: Any, locator: dict[str, str]) -> str | None:
    raw = h.blobs.read(locator["service"], locator["account"])
    return None if raw is None else json.loads(raw).get("api_key")


class _AcceptingValidation:
    async def validate(self, _plugin: Any, _provider: str, _api_key: str) -> ApiKeyValidationResult:
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )


async def _valid() -> None:
    return None


def put_pair(h: Any) -> PairMutation:
    return h.call(set_pair_api_key, h.client.app, h.account_id, PROVIDER, NEW_KEY, validate=_valid)


# --- the native routes ----------------------------------------------------------------------


def test_a_native_callback_leaves_a_same_named_document_as_it_was(legacy: Any) -> None:
    legacy.seed_profile(name="work", state=ProfileState.PENDING, credential=None)
    before = documents(legacy)
    started = legacy.client.post(
        "/v1/oauth/connections", json={"provider": PROVIDER, "label": "work"}
    )
    assert started.status_code == 201, started.text
    use_tokens(legacy, "fresh-tok")
    writes = watch_index_writes(legacy)

    response = callback(legacy, started.json()["state"])

    assert response.status_code == 200, response.text
    assert legacy.connection_status(started.json()["connection_id"]) == "active"
    assert writes == []
    assert documents(legacy) == before


def test_a_native_key_replacement_fences_the_pair_and_mirrors_no_document(migrated: Any) -> None:
    migrated.seed_profile(auth_type="api_key", credential=OLD_KEY)
    effective = migrated.migrated["default"]
    migrated.client.app.state.api_key_validation_service = _AcceptingValidation()
    before, generation = documents(migrated), marker(migrated).generation
    writes = watch_index_writes(migrated)

    response = migrated.client.put(
        f"/v1/oauth/connections/{effective}/api-key", json={"api_key": NEW_KEY}
    )

    assert response.status_code == 200, response.text
    pair = marker(migrated)
    # INVARIANT: the generation still moves, so a repair callback in flight loses its CAS.
    assert (pair.generation, str(pair.effective_connection_id)) == (generation + 1, effective)
    assert api_key_at(migrated, address(migrated, "default")) == NEW_KEY
    assert writes == []
    assert documents(migrated) == before


def test_a_native_delete_of_the_effective_row_removes_no_document(migrated: Any) -> None:
    migrated.seed_profile()
    effective = migrated.migrated["default"]
    before = documents(migrated)
    writes = watch_index_writes(migrated)

    response = migrated.client.delete(f"/v1/oauth/connections/{effective}")

    assert response.status_code == 204, response.text
    pair = marker(migrated)
    assert (pair.migration_state, pair.effective_connection_id) == ("migrated", None)
    assert blob_at_profile_address(migrated) is None
    assert writes == []
    assert documents(migrated) == before


def test_a_native_delete_takes_the_blob_a_document_of_an_unmarked_pair_addresses(
    legacy: Any,
) -> None:
    legacy.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    locator = address(legacy, "work")
    connection_id = uuid4()
    legacy.call(
        OAuthConnectionStore().create_api_key,
        account_id=legacy.account_id,
        provider=PROVIDER,
        label=f"conn-{connection_id}",
        connection_id=connection_id,
        credential_provider=CREDENTIAL_PROVIDER,
        credential_locator=locator,
    )

    response = legacy.client.delete(f"/v1/oauth/connections/{connection_id}")

    assert response.status_code == 204, response.text
    # WHY: no Profile document owns a blob after E4a — the Connection was its last addresser.
    assert api_key_at(legacy, locator) is None
    assert document(legacy, "work") is not None


# --- the D18 successor ----------------------------------------------------------------------


def test_the_pair_put_on_an_empty_pair_creates_no_document(legacy: Any) -> None:
    writes = watch_index_writes(legacy)

    mutation = put_pair(legacy)

    assert mutation.credential is not None
    assert api_key_at(legacy, address(legacy, "default")) == NEW_KEY
    assert writes == []
    assert documents(legacy) == []


def test_the_pair_put_names_its_row_default_beside_a_leftover_document(legacy: Any) -> None:
    legacy.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    before = documents(legacy)
    writes = watch_index_writes(legacy)

    mutation = put_pair(legacy)

    assert mutation.profile_names == ("default",)
    assert api_key_at(legacy, address(legacy, "default")) == NEW_KEY
    assert api_key_at(legacy, address(legacy, "work")) == OLD_KEY
    assert writes == []
    assert documents(legacy) == before


def test_the_pair_delete_removes_no_document(migrated: Any) -> None:
    migrated.seed_profile()
    before = documents(migrated)
    writes = watch_index_writes(migrated)

    mutation = migrated.call(delete_pair, migrated.client.app, migrated.account_id, PROVIDER)

    assert mutation.profile_names == ()
    pair = marker(migrated)
    assert (pair.migration_state, pair.effective_connection_id) == ("migrated", None)
    assert writes == []
    assert documents(migrated) == before
