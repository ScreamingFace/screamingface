"""G1 PUT/DELETE through the mutation bridge — every §5 row (OME-1497, G1 part 2).

# FEATURE: OME-1138 D18 (contract §5, §5.1, §5.2, §6) — an admin replaces or disconnects the ONE
# credential of an `(account, provider)` pair. A single-candidate `none` pair is adopted at
# mutation time: PUT publishes `migrated` with an active API-key Connection, DELETE ends the pair
# `migrated` with a null reference; no other pair is touched and no dummy Connection is created.
# STORY: as an operator, I attach a key to a tenant's provider, or disconnect it, without knowing
# whether the tenant's credential is still a legacy Profile or already a Connection.
# INVARIANT: a refused mutation (409/503, a failed key check, a superseded capture) writes
# nothing — no marker, document, row or blob changes.
# NOTE: the bridge runs over the real stores; `validate` stands in for the provider key
# check the route runs, so a test can fail it or race a writer into it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness
from tortoise.exceptions import OperationalError

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.pending_auth import PendingAuthEntry, PendingAuthTable
from aigateway.core.plugin_base import credential_service_provider_for
from aigateway.core.provider_access import (
    CredentialAuthorityUnavailable,
    CredentialStoreReadUnavailable,
    CredentialStoreUnavailable,
    MigrationState,
    PairAuthorityStore,
    PairCredential,
    PairInventory,
    PairMutation,
    PairNotManageable,
    ProviderUnknown,
    WriteConflict,
    delete_pair,
    pair_inventory,
    set_pair_api_key,
)
from aigateway.core.provider_access.models import ProviderCredentialSlot

CREDENTIAL_PROVIDER = credential_service_provider_for(ANTHROPIC, PROVIDER)
NEW_KEY = "sk-ant-api03-new-key-0001"
OLD_KEY = "sk-ant-api03-old-key-0002"


@pytest.fixture
def harness(authenticated_client, credential_blobs, monkeypatch) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


async def _valid() -> None:
    return None


def _put(
    harness: ProfileBackedHarness,
    *,
    validate: Callable[[], Awaitable[None]] = _valid,
    provider: str = PROVIDER,
) -> PairMutation:
    return harness.call(
        set_pair_api_key,
        harness.client.app,
        harness.account_id,
        provider,
        NEW_KEY,
        validate=validate,
    )


def _delete(harness: ProfileBackedHarness, provider: str = PROVIDER) -> PairMutation:
    return harness.call(delete_pair, harness.client.app, harness.account_id, provider)


def _address(harness: ProfileBackedHarness, name: str) -> dict[str, str]:
    return credential_locator_for(CREDENTIAL_PROVIDER, harness.account_id, name)


def _blob(harness: ProfileBackedHarness, locator: dict[str, Any]) -> str | None:
    raw = harness.blobs.read(locator["service"], locator["account"])
    return None if raw is None else json.loads(raw).get("api_key")


def _seed_key(harness: ProfileBackedHarness, locator: dict[str, Any], key: str) -> None:
    harness.blobs.write(
        locator["service"], locator["account"], json.dumps({"auth_type": "api_key", "api_key": key})
    )


def _connection(
    harness: ProfileBackedHarness,
    *,
    locator: dict[str, str] | None = None,
    pending: bool = False,
    key: str | None = OLD_KEY,
) -> OAuthConnection:
    connection_id = uuid4()
    store = OAuthConnectionStore()
    create = store.create_pending if pending else store.create_api_key
    connection = harness.call(
        create,
        account_id=harness.account_id,
        provider=PROVIDER,
        label=f"conn-{connection_id}",
        connection_id=connection_id,
        credential_provider=CREDENTIAL_PROVIDER,
        credential_locator=locator,
    )
    if key is not None:
        _seed_key(harness, connection.credential_locator, key)
    return connection


def _set_status(harness: ProfileBackedHarness, connection: OAuthConnection, status: str) -> None:
    async def update() -> None:
        await OAuthConnection.filter(id=connection.id).update(status=status)

    harness.call(update)


def _rows(harness: ProfileBackedHarness) -> list[dict[str, Any]]:
    async def rows() -> list[dict[str, Any]]:
        return await OAuthConnection.filter(account_id=harness.account_id).values(
            "id", "status", "auth_type", "credential_locator"
        )

    return harness.call(rows)


def _live(harness: ProfileBackedHarness) -> list[dict[str, Any]]:
    return [row for row in _rows(harness) if row["status"] != "revoked"]


def _marker(harness: ProfileBackedHarness) -> dict[str, Any] | None:
    async def read() -> list[dict[str, Any]]:
        return await ProviderCredentialSlot.filter(
            account_id=harness.account_id, provider=PROVIDER
        ).values("migration_state", "effective_connection_id", "generation")

    rows = harness.call(read)
    return rows[0] if rows else None


def _documents(harness: ProfileBackedHarness) -> list[tuple[str, str, str]]:
    documents = harness.call(harness.client.app.state.profile_index.list, harness.account_id)
    return sorted((d.name, d.auth_type, d.state.value) for d in documents)


def _mark(
    harness: ProfileBackedHarness, state: MigrationState, *, effective: UUID | None = None
) -> None:
    async def advance() -> None:
        current = await PairAuthorityStore().read(harness.account_id, PROVIDER)
        await PairAuthorityStore().advance(
            harness.account_id,
            PROVIDER,
            expected_generation=current.generation,
            migration_state=state,
            effective_connection_id=effective,
        )

    harness.call(advance)


def _inventory(harness: ProfileBackedHarness) -> PairInventory:
    return harness.call(pair_inventory, harness.client.app, harness.account_id)


def _state(harness: ProfileBackedHarness) -> tuple[Any, ...]:
    """Everything a refused mutation must leave untouched."""
    return (_marker(harness), _rows(harness), _documents(harness))


ACTIVE = PairCredential(PROVIDER, "api_key", "active", None)


# --- row 7: an empty pair -------------------------------------------------------------------


def test_put_on_an_empty_pair_creates_one_connection_at_the_default_address(harness) -> None:
    mutation = _put(harness)

    (row,) = _live(harness)
    assert row["auth_type"] == "api_key"
    assert row["credential_locator"] == _address(harness, "default")
    assert _blob(harness, _address(harness, "default")) == NEW_KEY
    marker = _marker(harness)
    assert marker is not None
    assert marker["migration_state"] == "migrated"
    assert marker["effective_connection_id"] == row["id"]
    # The private compatibility mirror: one `default` document, never on the wire.
    assert _documents(harness) == [("default", "api_key", "authenticated")]
    assert mutation.credential is not None
    assert mutation.credential.provider == PROVIDER
    assert mutation.credential.auth_type == "api_key"
    assert mutation.credential.credential_state == "active"
    assert _inventory(harness).credentials == (mutation.credential,)


def test_delete_on_an_empty_pair_is_a_no_op_that_mints_no_marker(harness) -> None:
    mutation = _delete(harness)

    assert mutation.credential is None
    assert _marker(harness) is None
    assert _rows(harness) == []


# --- a sole legacy Profile: its document names the PUT's mirror (§5.2) ----------------------


def test_put_adopts_a_sole_profile_on_its_own_name_and_address(harness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)

    _put(harness)

    (row,) = _live(harness)
    assert row["credential_locator"] == _address(harness, "work")
    assert _blob(harness, _address(harness, "work")) == NEW_KEY
    assert _documents(harness) == [("work", "api_key", "authenticated")]
    marker = _marker(harness)
    assert marker is not None
    assert (marker["migration_state"], marker["effective_connection_id"]) == ("migrated", row["id"])


# --- row 9: a sole Connection ---------------------------------------------------------------


@pytest.mark.parametrize("pending", [False, True], ids=["active", "pending"])
def test_put_keeps_a_sole_connections_id_and_locator(harness, pending) -> None:
    connection = _connection(harness, pending=pending)

    mutation = _put(harness)

    (row,) = _live(harness)
    assert row["id"] == connection.id
    assert row["credential_locator"] == connection.credential_locator
    assert (row["status"], row["auth_type"]) == ("active", "api_key")
    assert _blob(harness, connection.credential_locator) == NEW_KEY
    # One private `default` mirror when none exists; the credential is never copied to it.
    assert _documents(harness) == [("default", "api_key", "authenticated")]
    assert _blob(harness, _address(harness, "default")) is None
    marker = _marker(harness)
    assert marker is not None
    assert marker["effective_connection_id"] == connection.id
    assert mutation.connection_ids == (str(connection.id),)


def test_delete_revokes_a_sole_connection_and_its_blob(harness) -> None:
    connection = _connection(harness)

    mutation = _delete(harness)

    assert _live(harness) == []
    assert _blob(harness, connection.credential_locator) is None
    marker = _marker(harness)
    assert marker is not None
    assert (marker["migration_state"], marker["effective_connection_id"]) == ("migrated", None)
    assert mutation.connection_ids == (str(connection.id),)


# --- row 9 with a Profile document at the Connection's address ------------------------------


def test_put_on_a_same_locator_pair_keeps_the_row_and_the_name(harness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    connection = _connection(harness, locator=_address(harness, "work"), key=None)

    _put(harness)

    (row,) = _live(harness)
    assert row["id"] == connection.id
    assert _blob(harness, _address(harness, "work")) == NEW_KEY
    assert _documents(harness) == [("work", "api_key", "authenticated")]


def test_delete_on_a_same_locator_pair_retires_both_owners_and_the_blob(harness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _connection(harness, locator=_address(harness, "work"), key=None)

    mutation = _delete(harness)

    assert _live(harness) == []
    assert _documents(harness) == []
    assert _blob(harness, _address(harness, "work")) is None
    assert mutation.profile_names == ("work",)


# --- rows 5 and 6: a migrated pair ----------------------------------------------------------


def test_a_repeated_put_replaces_the_key_on_the_same_effective_row(harness) -> None:
    _put(harness)
    (first,) = _live(harness)
    generation = (_marker(harness) or {})["generation"]

    harness.call(
        set_pair_api_key,
        harness.client.app,
        harness.account_id,
        PROVIDER,
        "sk-ant-api03-third-0003",
        validate=_valid,
    )

    (second,) = _live(harness)
    assert second["id"] == first["id"]
    assert _blob(harness, _address(harness, "default")) == "sk-ant-api03-third-0003"
    assert (_marker(harness) or {})["generation"] == generation + 1


@pytest.mark.parametrize("status", ["pending", "error"])
def test_put_recovers_a_pending_or_errored_effective_row(harness, status) -> None:
    connection = _connection(harness, locator=_address(harness, "default"), pending=True)
    if status == "error":
        _set_status(harness, connection, "error")
    _mark(harness, "migrated", effective=connection.id)

    mutation = _put(harness)

    (row,) = _live(harness)
    assert (row["id"], row["status"]) == (connection.id, "active")
    assert mutation.credential is not None
    assert (mutation.credential.auth_type, mutation.credential.credential_state) == (
        "api_key",
        "active",
    )


def test_delete_then_a_repeated_delete_both_succeed(harness) -> None:
    _put(harness)

    _delete(harness)
    second = _delete(harness)

    assert second.credential is None
    assert _live(harness) == []
    assert _blob(harness, _address(harness, "default")) is None
    assert _documents(harness) == []
    marker = _marker(harness)
    assert marker is not None
    assert marker["effective_connection_id"] is None


def test_put_after_a_delete_reuses_a_single_leftover_document_as_the_mirror(harness) -> None:
    # Row 6 with one leftover compatibility document: it becomes the mirror under its own name
    # and address; no second `default` document, so the pair never turns ambiguous.
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _mark(harness, "migrated")

    _put(harness)

    (row,) = _live(harness)
    assert row["credential_locator"] == _address(harness, "work")
    assert _documents(harness) == [("work", "api_key", "authenticated")]
    assert _inventory(harness).conflicts == ()


def test_delete_on_a_disconnected_pair_with_a_leftover_document_is_a_no_op(harness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _mark(harness, "migrated")
    before = _state(harness)

    _delete(harness)

    assert _state(harness) == before


# --- refusals: nothing is written -----------------------------------------------------------


def _two_live(harness: ProfileBackedHarness) -> None:
    _connection(harness)
    _connection(harness)


def _quarantined(harness: ProfileBackedHarness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _mark(harness, "quarantined")


def _migrated_null_beside_a_live_row(harness: ProfileBackedHarness) -> None:
    _mark(harness, "migrated")
    _connection(harness)


@pytest.mark.parametrize(
    ("seed", "kind"),
    [
        (_two_live, "ambiguous"),
        (_quarantined, "unresolved"),
        (_migrated_null_beside_a_live_row, "unresolved"),
    ],
    ids=["row-3", "row-4", "migrated-null-live"],
)
@pytest.mark.parametrize("operation", ["put", "delete"])
def test_an_unmanageable_pair_refuses_and_writes_nothing(harness, seed, kind, operation) -> None:
    seed(harness)
    before = _state(harness)
    validated: list[bool] = []

    async def validate() -> None:
        validated.append(True)

    with pytest.raises(PairNotManageable) as refused:
        if operation == "put":
            _put(harness, validate=validate)
        else:
            _delete(harness)

    assert (refused.value.provider, refused.value.kind) == (PROVIDER, kind)
    # Refused before the provider key check: a conflicting pair costs no validation I/O.
    assert validated == []
    assert _state(harness) == before


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_an_inconsistent_pair_is_unavailable(harness, operation) -> None:
    connection = _connection(harness)
    _set_status(harness, connection, "unavailable")

    with pytest.raises(CredentialAuthorityUnavailable):
        if operation == "put":
            _put(harness)
        else:
            _delete(harness)


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_an_unknown_provider_keeps_the_existing_refusal(harness, operation) -> None:
    with pytest.raises(ProviderUnknown):
        if operation == "put":
            _put(harness, provider="no-such-provider")
        else:
            _delete(harness, provider="no-such-provider")


def test_a_failed_key_check_leaves_owner_and_data_unchanged(harness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    before = _state(harness)

    class Rejected(Exception):
        pass

    async def reject() -> None:
        raise Rejected

    with pytest.raises(Rejected):
        _put(harness, validate=reject)

    assert _state(harness) == before
    assert _blob(harness, _address(harness, "work")) == OLD_KEY


def test_a_second_candidate_created_during_validation_makes_the_bridge_refuse(harness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _connection(harness, locator=_address(harness, "work"), key=None)

    async def native_create_meanwhile() -> None:
        await OAuthConnectionStore().create_api_key(
            account_id=harness.account_id,
            provider=PROVIDER,
            label="raced",
            connection_id=uuid4(),
            credential_provider=CREDENTIAL_PROVIDER,
        )

    with pytest.raises(PairNotManageable):
        _put(harness, validate=native_create_meanwhile)

    assert _marker(harness) is None
    assert _blob(harness, _address(harness, "work")) == OLD_KEY


def test_a_live_row_added_after_the_capture_supersedes_the_publication(
    harness, monkeypatch
) -> None:
    # A native create on a migrated pair claims nothing (owner decision 2026-10-06), so only the
    # bridge's own re-check of the live rows inside its transaction can see it.
    _put(harness)
    before = _marker(harness)
    index = harness.client.app.state.profile_index
    real_get = index.get
    raced: list[bool] = []

    async def get_then_race(*args: Any, **kwargs: Any) -> Any:
        if not raced:
            raced.append(True)
            await OAuthConnectionStore().create_api_key(
                account_id=harness.account_id,
                provider=PROVIDER,
                label="raced",
                connection_id=uuid4(),
                credential_provider=CREDENTIAL_PROVIDER,
            )
        return await real_get(*args, **kwargs)

    monkeypatch.setattr(index, "get", get_then_race)

    with pytest.raises(WriteConflict) as conflict:
        _put(harness)

    assert conflict.value.kind == "superseded"
    assert raced == [True]
    assert _marker(harness) == before
    assert _blob(harness, _address(harness, "default")) == NEW_KEY


def test_a_live_row_added_after_a_delete_captured_the_pair_supersedes_it(
    harness, monkeypatch
) -> None:
    # The delete's own capture saw one Connection; a native create landing before its transaction
    # (no claim on the pair it adds to) must not be swept away by the delete it never saw.
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _connection(harness, locator=_address(harness, "work"), key=None)
    before = _marker(harness)
    real_list = OAuthConnectionStore.list
    calls: list[int] = []

    async def list_then_race(self: OAuthConnectionStore, *args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        listed = await real_list(self, *args, **kwargs)
        if len(calls) == 1:
            await OAuthConnectionStore().create_api_key(
                account_id=harness.account_id,
                provider=PROVIDER,
                label="raced",
                connection_id=uuid4(),
                credential_provider=CREDENTIAL_PROVIDER,
            )
        return listed

    monkeypatch.setattr(OAuthConnectionStore, "list", list_then_race)

    with pytest.raises(WriteConflict) as conflict:
        _delete(harness)

    assert conflict.value.kind == "superseded"
    assert len(calls) >= 1
    assert _marker(harness) == before
    assert _documents(harness) == [("work", "api_key", "authenticated")]
    assert _blob(harness, _address(harness, "work")) == OLD_KEY


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_a_store_outage_inside_the_write_is_the_scoped_write_refusal(
    harness, monkeypatch, operation
) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _connection(harness, locator=_address(harness, "work"), key=None)
    before = _state(harness)

    async def down(*_args: Any, **_kwargs: Any) -> Any:
        raise OperationalError("server closed the connection unexpectedly")

    monkeypatch.setattr(PairAuthorityStore, "advance", down)

    with pytest.raises(CredentialStoreUnavailable) as refused:
        if operation == "put":
            _put(harness)
        else:
            _delete(harness)

    assert "server closed" not in str(refused.value)
    monkeypatch.undo()
    assert _state(harness) == before


def test_a_store_outage_reading_the_documents_to_delete_is_a_read_refusal(
    harness, monkeypatch
) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _connection(harness, locator=_address(harness, "work"), key=None)
    index = harness.client.app.state.profile_index
    real_list = index.list
    calls: list[int] = []

    async def list_then_fail(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("server closed the connection unexpectedly")
        return await real_list(*args, **kwargs)

    monkeypatch.setattr(index, "list", list_then_fail)

    with pytest.raises(CredentialStoreReadUnavailable):
        _delete(harness)


# --- post-commit cleanup ------------------------------------------------------------------------


def test_the_mutation_evicts_the_cached_credential_it_changed(harness) -> None:
    harness.seed_profile(name="work", auth_type="api_key", credential=OLD_KEY)
    _connection(harness, locator=_address(harness, "work"), key=None)

    _delete(harness)

    assert any("work" in name for name in harness.evicted())


def test_pending_cleanup_pops_only_the_pairs_captured_targets() -> None:
    table = PendingAuthTable()

    def entry(provider: str, profile: str, connection: str) -> PendingAuthEntry:
        return PendingAuthEntry(
            account_id="acct",
            provider=provider,
            profile_name=profile,
            code_verifier="v",
            redirect_uri="https://example.invalid/cb",
            connection_id=connection,
        )

    table.put("by-name", entry(PROVIDER, "work", "c-work"))
    table.put("by-connection", entry(PROVIDER, "", "c-1"))
    table.put("other-name", entry(PROVIDER, "other", "c-other"))
    table.put("other-provider", entry("openai", "work", "c-openai"))

    removed = table.pop_for_pair("acct", PROVIDER, profile_names=("work",), connection_ids=("c-1",))

    assert sorted(removed) == ["by-connection", "by-name"]
    assert table.peek("other-name") is not None
    assert table.peek("other-provider") is not None
