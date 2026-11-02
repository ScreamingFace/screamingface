"""A D18 PUT mints its row at the row's own address (Stage E history cleanup, E5a).

# FEATURE: OME-1138 E5 — the history purge deletes the credential blobs no Connection addresses.
# A PUT that minted its row at the `default` Profile address could adopt such a blob while the
# purge deletes it, and `ORMStore.write` (get, then UPDATE by id) would lose the key silently.
# STORY: as an operator, the key I attach to a tenant's provider is stored where nothing else
# points, so no cleanup can take it.
# INVARIANT: a minted row addresses `<account_id>:<row id>`, like a native API-key row; a reused
# row keeps its locator, so a migrated Connection that reads its Profile's blob is unchanged.
# INVARIANT: the pending-flow drop follows the captured Connection, never a Profile name.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from provider_access_harness import ANTHROPIC, PROVIDER, RealAppHarness

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.pending_auth import PendingAuthEntry, PendingAuthTable
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access import PairMutation, set_pair_api_key
from tests.unit.migrated_pair_seed import seed_migrated_pair

CREDENTIAL_PROVIDER = credential_service_provider_for(ANTHROPIC, PROVIDER)
NEW_KEY = "sk-ant-api03-e5a-new-key-0001"
OLD_KEY = "sk-ant-api03-e5a-old-key-0002"


@pytest.fixture
def h(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> RealAppHarness:
    return RealAppHarness(authenticated_client, credential_blobs, monkeypatch)


async def _valid() -> None:
    return None


def _put(h: RealAppHarness) -> PairMutation:
    return h.call(set_pair_api_key, h.client.app, h.account_id, PROVIDER, NEW_KEY, validate=_valid)


def _address(h: RealAppHarness, name: str | UUID) -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, h.account_id, name)


def _raw(h: RealAppHarness, locator: dict[str, str]) -> str | None:
    return h.blobs.read(locator["service"], locator["account"])


def _key(h: RealAppHarness, locator: dict[str, str]) -> str | None:
    raw = _raw(h, locator)
    return None if raw is None else json.loads(raw).get("api_key")


def _rows(h: RealAppHarness) -> list[OAuthConnection]:
    return h.call(OAuthConnectionStore().list, h.account_id, provider=PROVIDER)


def _live(h: RealAppHarness) -> list[OAuthConnection]:
    return [row for row in _rows(h) if row.status != "revoked"]


def test_a_put_on_an_empty_pair_stores_the_key_at_its_rows_own_address(
    h: RealAppHarness,
) -> None:
    _put(h)

    (row,) = _live(h)
    assert row.credential_locator == _address(h, row.id)
    assert _key(h, _address(h, row.id)) == NEW_KEY
    assert _raw(h, _address(h, "default")) is None


def test_a_put_beside_a_leftover_default_blob_neither_adopts_nor_changes_it(
    h: RealAppHarness,
) -> None:
    # The shape a `none` pair's DELETE leaves (E4a ledger): a blob at the `default` address that
    # no Connection and no document names — exactly what the purge deletes.
    leftover = _address(h, "default")
    h.blobs.write(
        leftover["service"],
        leftover["account"],
        json.dumps({"auth_type": "api_key", "api_key": OLD_KEY}),
    )
    before = _raw(h, leftover)

    _put(h)

    (row,) = _live(h)
    assert row.credential_locator == _address(h, row.id)
    assert _key(h, _address(h, row.id)) == NEW_KEY
    assert _raw(h, leftover) == before
    assert all(r.credential_locator != leftover for r in _rows(h))


def test_a_put_on_a_migrated_pair_still_writes_the_blob_its_row_reads(
    h: RealAppHarness,
) -> None:
    effective = seed_migrated_pair(
        h.client, h.account_id, PROVIDER, name="work", auth_type="api_key", credential=OLD_KEY
    )

    _put(h)

    (row,) = _live(h)
    assert row.id == effective
    assert row.credential_locator == _address(h, "work")
    assert _key(h, _address(h, "work")) == NEW_KEY
    assert _raw(h, _address(h, row.id)) is None


def test_the_pending_flow_drop_follows_the_captured_connection_not_a_name(
    h: RealAppHarness,
) -> None:
    pending_id = uuid4()
    h.call(
        OAuthConnectionStore().create_pending,
        account_id=h.account_id,
        provider=PROVIDER,
        label=f"conn-{pending_id}",
        connection_id=pending_id,
        credential_provider=CREDENTIAL_PROVIDER,
    )

    mutation = _put(h)

    assert mutation.connection_ids == (str(pending_id),)
    assert not hasattr(mutation, "profile_names")
    table = PendingAuthTable()

    def flow(name: str, connection_id: str) -> PendingAuthEntry:
        return PendingAuthEntry(
            account_id=h.account_id,
            provider=PROVIDER,
            profile_name=name,
            code_verifier="v",
            redirect_uri="https://example.invalid/cb",
            connection_id=connection_id,
        )

    table.put("captured", flow("work", str(pending_id)))
    table.put("same-name-only", flow("default", "another-connection"))

    removed = table.pop_for_pair(h.account_id, PROVIDER, connection_ids=mutation.connection_ids)

    assert removed == ["captured"]
    assert table.peek("same-name-only") is not None
