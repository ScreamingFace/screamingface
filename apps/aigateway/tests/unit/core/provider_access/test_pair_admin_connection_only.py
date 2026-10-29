"""D18 classifies a pair without the Profile index (OME-1209, Stage E, E4a; spec §9 Q8).

# FEATURE: OME-1138 D18 after Stage E plan §3 E4a — a pair's marker and its live Connections alone
# choose the §5 row. Rows 8 and 10, the document half of row 3 and the row-11 shadow proof are
# gone: the empty-pair row (7) and the single-Connection row (9) keep publishing `migrated`.
# STORY: as an operator, the credential I manage is the Connection the runtime would use; a legacy
# blob at a name address beside it neither shows up nor changes which row the pair is in.
# INVARIANT: row 11 is refused as `unresolved`, with no identity proof; a pair holding only a
# legacy blob at a name address is the empty pair, and that blob stays as it was.
# WHY no mirror (OME-1209 E4b): the PUT writes the effective Connection's blob and no other name
# address.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from provider_access_harness import ANTHROPIC, PROVIDER, RealAppHarness

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.plugin_base import credential_service_provider_for
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
def h(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> RealAppHarness:
    return RealAppHarness(authenticated_client, credential_blobs, monkeypatch)


async def _valid() -> None:
    return None


def _put(h: RealAppHarness) -> PairMutation:
    return h.call(set_pair_api_key, h.client.app, h.account_id, PROVIDER, NEW_KEY, validate=_valid)


def _delete(h: RealAppHarness) -> PairMutation:
    return h.call(delete_pair, h.client.app, h.account_id, PROVIDER)


def _inventory(h: RealAppHarness) -> PairInventory:
    return h.call(pair_inventory, h.client.app, h.account_id)


def _address(h: RealAppHarness, name: str) -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, h.account_id, name)


def _blob(h: RealAppHarness, locator: dict[str, Any]) -> str | None:
    raw = h.blobs.read(locator["service"], locator["account"])
    return None if raw is None else json.loads(raw).get("api_key")


def _connection(h: RealAppHarness, *, locator: dict[str, str] | None = None) -> OAuthConnection:
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


def _mark(h: RealAppHarness, state: MigrationState, *, effective: UUID | None = None) -> None:
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


def _marker(h: RealAppHarness) -> dict[str, Any] | None:
    async def read() -> list[dict[str, Any]]:
        return await ProviderCredentialSlot.filter(
            account_id=h.account_id, provider=PROVIDER
        ).values("migration_state", "effective_connection_id", "generation")

    rows = h.call(read)
    return rows[0] if rows else None


def _live(h: RealAppHarness) -> list[dict[str, Any]]:
    async def rows() -> list[dict[str, Any]]:
        return (
            await OAuthConnection.filter(account_id=h.account_id)
            .exclude(status="revoked")
            .values("id", "status", "auth_type", "credential_locator")
        )

    return h.call(rows)


# --- the table ---------------------------------------------------------------------------------


def test_the_disposition_names_no_document() -> None:
    assert "document" not in {field.name for field in dataclasses.fields(PairDisposition)}


def test_classify_pair_decides_on_the_marker_and_the_connections_alone() -> None:
    marker = PairAuthority("acct", PROVIDER, "none", None, 0)

    disposition = classify_pair(marker, [], credential_provider=CREDENTIAL_PROVIDER)

    assert (disposition.row, disposition.connection) == (7, None)


# --- LIST ----------------------------------------------------------------------------------------


def test_list_shows_nothing_for_a_profile_only_pair_and_reads_no_index(h: RealAppHarness) -> None:
    h.seed_blob(name="work", auth_type="api_key", credential=OLD_KEY)

    assert _inventory(h) == PairInventory(credentials=(), conflicts=())


def test_list_shows_the_connection_not_the_profile_at_its_address(h: RealAppHarness) -> None:
    h.seed_blob(auth_type="api_key", credential=OLD_KEY)
    _connection(h, locator=_address(h, "default"))

    inventory = _inventory(h)

    assert inventory.conflicts == ()
    assert [(c.provider, c.auth_type, c.credential_state) for c in inventory.credentials] == [
        (PROVIDER, "api_key", "active")
    ]


def test_list_shows_the_one_connection_beside_several_profiles(h: RealAppHarness) -> None:
    h.seed_blob(name="work", auth_type="api_key", credential=OLD_KEY)
    h.seed_blob(name="home", auth_type="api_key", credential=OLD_KEY)
    _connection(h)

    inventory = _inventory(h)

    assert inventory.conflicts == ()
    assert [c.provider for c in inventory.credentials] == [PROVIDER]


# --- PUT and DELETE ------------------------------------------------------------------------------


def test_put_adopts_the_one_connection_of_a_none_pair_beside_a_profile(
    h: RealAppHarness,
) -> None:
    h.seed_blob(name="work", auth_type="oauth", credential="tok")
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
    h: RealAppHarness,
) -> None:
    # The migrated shape: the effective Connection sits at the `work` name address.
    h.seed_blob(name="work", auth_type="api_key", credential=OLD_KEY)
    effective = seed_migrated_pair(
        h.client, h.account_id, PROVIDER, name="work", auth_type="api_key"
    )

    mutation = _put(h)

    (row,) = _live(h)
    assert row["id"] == effective
    assert _blob(h, _address(h, "work")) == NEW_KEY
    assert _blob(h, _address(h, "default")) is None
    assert mutation.connection_ids == (str(effective),)
    assert _inventory(h).conflicts == ()


def test_delete_leaves_a_profile_only_pair_untouched(h: RealAppHarness) -> None:
    h.seed_blob(name="work", auth_type="api_key", credential=OLD_KEY)

    mutation = _delete(h)

    assert mutation == PairMutation(None)
    assert _marker(h) is None
    assert _blob(h, _address(h, "work")) == OLD_KEY


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_row_11_is_refused_without_an_identity_proof(
    h: RealAppHarness, monkeypatch: pytest.MonkeyPatch, operation: str
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
