"""D18 classifies a pair without the Profile index (OME-1209, Stage E, E4a; spec §9 Q8).

# FEATURE: OME-1138 D18 after Stage E plan §3 E4a — a pair's marker and its live Connections alone
# choose the §5 row. Rows 8 and 10, the document half of row 3 and the row-11 shadow proof are
# gone: the empty-pair row (7) and the single-Connection row (9) keep publishing `migrated`.
# STORY: as an operator, the credential I manage is the Connection the runtime would use; a legacy
# Profile document beside it neither shows up nor changes which row the pair is in.
# INVARIANT: LIST and the mutation capture read no Profile document; row 11 is refused exactly
# like row 4, with no identity proof; a Profile-only pair is the empty pair.
# WHY no mirror (OME-1209 E4b): the PUT names no compatibility document any more; the pair's
# one document, if any, stays as it was until E5.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID, uuid4

import pytest
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import ProfileState
from aigateway.core.provider_access import (
    MigrationState,
    PairAuthority,
    PairAuthorityStore,
    PairCredential,
    PairDisposition,
    PairInventory,
    PairMutation,
    PairNotManageable,
    classify_pair,
    delete_pair,
    pair_inventory,
    set_pair_api_key,
)
from aigateway.core.provider_access.models import ProviderCredentialSlot
from tests.unit.migrated_pair_seed import seed_migrated_pair

CREDENTIAL_PROVIDER = credential_service_provider_for(ANTHROPIC, PROVIDER)
NEW_KEY = "sk-ant-api03-new-key-0001"
OLD_KEY = "sk-ant-api03-old-key-0002"


@pytest.fixture
def h(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def index_reads(h: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every read of a Profile index, by method name, in order."""
    reads: list[str] = []

    def spy(name: str, real: Callable[..., Coroutine[Any, Any, Any]]) -> Any:
        async def read(*args: Any, **kwargs: Any) -> Any:
            reads.append(name)
            return await real(*args, **kwargs)

        return read

    # WHY the class (OME-1209 E4b): the app wires no index, so a read could only come through a
    # store built on the spot; the class sees every one.
    for name in ("get", "list"):
        monkeypatch.setattr(ProfileIndexStore, name, spy(name, getattr(ProfileIndexStore, name)))
    return reads


async def _valid() -> None:
    return None


def _put(h: ProfileBackedHarness) -> PairMutation:
    return h.call(set_pair_api_key, h.client.app, h.account_id, PROVIDER, NEW_KEY, validate=_valid)


def _delete(h: ProfileBackedHarness) -> PairMutation:
    return h.call(delete_pair, h.client.app, h.account_id, PROVIDER)


def _inventory(h: ProfileBackedHarness) -> PairInventory:
    return h.call(pair_inventory, h.client.app, h.account_id)


def _address(h: ProfileBackedHarness, name: str) -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, h.account_id, name)


def _blob(h: ProfileBackedHarness, locator: dict[str, Any]) -> str | None:
    raw = h.blobs.read(locator["service"], locator["account"])
    return None if raw is None else json.loads(raw).get("api_key")


def _connection(
    h: ProfileBackedHarness, *, locator: dict[str, str] | None = None
) -> OAuthConnection:
    connection_id = uuid4()
    connection = h.call(
        OAuthConnectionStore().create_api_key,
        account_id=h.account_id,
        provider=PROVIDER,
        label=f"conn-{connection_id}",
        connection_id=connection_id,
        credential_provider=CREDENTIAL_PROVIDER,
        credential_locator=locator,
    )
    stored = connection.credential_locator
    h.blobs.write(
        stored["service"],
        stored["account"],
        json.dumps({"auth_type": "api_key", "api_key": OLD_KEY}),
    )
    return connection


def _mark(h: ProfileBackedHarness, state: MigrationState, *, effective: UUID | None = None) -> None:
    async def advance() -> None:
        current = await PairAuthorityStore().read(h.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            h.account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state=state,
            effective_connection_id=effective,
        )

    h.call(advance)


def _marker(h: ProfileBackedHarness) -> dict[str, Any] | None:
    async def read() -> list[dict[str, Any]]:
        return await ProviderCredentialSlot.filter(
            account_id=h.account_id, provider=PROVIDER
        ).values("migration_state", "effective_connection_id", "generation")

    rows = h.call(read)
    return rows[0] if rows else None


def _live(h: ProfileBackedHarness) -> list[dict[str, Any]]:
    async def rows() -> list[dict[str, Any]]:
        return (
            await OAuthConnection.filter(account_id=h.account_id)
            .exclude(status="revoked")
            .values("id", "status", "auth_type", "credential_locator")
        )

    return h.call(rows)


def _documents(h: ProfileBackedHarness) -> list[str]:
    index = ProfileIndexStore(credential_store=h.client.app.state.credential_store)
    return sorted(d.name for d in h.call(index.list, h.account_id))


# --- the table ---------------------------------------------------------------------------------


def test_the_disposition_names_no_document() -> None:
    assert "document" not in {field.name for field in dataclasses.fields(PairDisposition)}


def test_classify_pair_decides_on_the_marker_and_the_connections_alone() -> None:
    marker = PairAuthority("acct", PROVIDER, "none", None, 0, None)

    disposition = classify_pair(marker, [], credential_provider=CREDENTIAL_PROVIDER)

    assert (disposition.row, disposition.connection) == (7, None)


# --- LIST ----------------------------------------------------------------------------------------


def test_list_shows_nothing_for_a_profile_only_pair_and_reads_no_index(
    h: ProfileBackedHarness, index_reads: list[str]
) -> None:
    h.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)

    assert _inventory(h) == PairInventory(credentials=(), conflicts=())
    assert index_reads == []


def test_list_shows_the_connection_not_the_profile_at_its_address(
    h: ProfileBackedHarness, index_reads: list[str]
) -> None:
    h.seed_profile(state=ProfileState.ERROR, auth_type="api_key", credential=OLD_KEY)
    _connection(h, locator=_address(h, "default"))

    inventory = _inventory(h)

    assert inventory.conflicts == ()
    assert [(c.provider, c.auth_type, c.credential_state) for c in inventory.credentials] == [
        (PROVIDER, "api_key", "active")
    ]
    assert index_reads == []


def test_list_shows_the_one_connection_beside_several_profiles(
    h: ProfileBackedHarness, index_reads: list[str]
) -> None:
    h.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    h.seed_profile(name="home", auth_type="api_key", credential=OLD_KEY)
    _connection(h)

    inventory = _inventory(h)

    assert inventory.conflicts == ()
    assert [c.provider for c in inventory.credentials] == [PROVIDER]
    assert index_reads == []


# --- PUT and DELETE ------------------------------------------------------------------------------


def test_put_adopts_the_one_connection_of_a_none_pair_beside_a_profile(
    h: ProfileBackedHarness,
) -> None:
    h.seed_profile(name="work", auth_type="oauth", credential="tok")
    connection = _connection(h)

    mutation = _put(h)

    (row,) = _live(h)
    assert (row["id"], row["credential_locator"]) == (connection.id, connection.credential_locator)
    assert _blob(h, connection.credential_locator) == NEW_KEY
    marker = _marker(h)
    assert marker is not None
    assert (marker["migration_state"], marker["effective_connection_id"]) == (
        "migrated",
        connection.id,
    )
    credential = mutation.credential
    assert isinstance(credential, PairCredential)
    assert (credential.provider, credential.auth_type, credential.credential_state) == (
        PROVIDER,
        "api_key",
        "active",
    )


def test_put_on_a_migrated_pair_keeps_its_row_and_mirrors_no_document(
    h: ProfileBackedHarness,
) -> None:
    # The backfill's shape: the effective Connection sits at the `work` document's address.
    h.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    effective = seed_migrated_pair(
        h.client, h.account_id, PROVIDER, name="work", auth_type="api_key"
    )

    mutation = _put(h)

    (row,) = _live(h)
    assert row["id"] == effective
    assert _blob(h, _address(h, "work")) == NEW_KEY
    assert _blob(h, _address(h, "default")) is None
    assert _documents(h) == ["work"]
    assert mutation.connection_ids == (str(effective),)
    assert _inventory(h).conflicts == ()


def test_delete_leaves_a_profile_only_pair_untouched(
    h: ProfileBackedHarness, index_reads: list[str]
) -> None:
    h.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)

    mutation = _delete(h)

    assert mutation == PairMutation(None)
    assert _marker(h) is None
    assert _blob(h, _address(h, "work")) == OLD_KEY
    assert index_reads == []
    assert _documents(h) == ["work"]


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_row_11_is_refused_without_an_identity_proof(
    h: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    _connection(h)
    _mark(h, "migrated")
    before = (_marker(h), _live(h))

    async def never(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("row 11 is refused before any identity is read")

    monkeypatch.setattr(ANTHROPIC, "extract_identity", never)
    with pytest.raises(PairNotManageable) as refused:
        _put(h) if operation == "put" else _delete(h)

    assert (refused.value.provider, refused.value.kind) == (PROVIDER, "unresolved")
    assert (_marker(h), _live(h)) == before
