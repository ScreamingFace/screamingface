"""Pair-authority routing behind the provider-access port (OME-1208, Stage B S2'; D14).

# FEATURE: Stage B Target — the port reads the pair marker on every resolve; a `migrated` pair is
# served from its effective Connection. Reads go through the stored `credential_locator`, so a
# migrated Connection serves the Profile's blob with no secret re-entry. An unmarked, `none` or
# `quarantined` pair is pinned in `test_connection_only_resolve.py` (OME-1209, Stage E, E4a).
# INVARIANT: the legacy document's own state is never authority for a migrated pair; the effective
# Connection's status decides. An unreadable marker store is an error, never a silent fall-back to
# the legacy credential.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER, RealAppHarness

from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.provider_access import (
    ConnectionBackedProviderAccess,
    PairAuthorityStore,
    ProviderAccess,
    Selector,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from tests.unit.seed_state import SeedState

DEFAULT = Selector.from_header(None)
LEGACY_URL = "/v1/oauth/connections"


def _resolve(harness: Any, selector: Selector = DEFAULT) -> Any:
    return harness.call(
        harness.access.resolve, harness.account_id, PROVIDER, selector, plugin=ANTHROPIC
    )


def _authorize(harness: Any, target: Any) -> Any:
    return harness.call(harness.access.authorize, target, plugin=ANTHROPIC, provider=PROVIDER)


def _availability(harness: Any) -> dict[str, str]:
    rows = harness.call(harness.access.availability, harness.account_id)
    assert [row.provider for row in rows] == sorted(row.provider for row in rows)
    assert all(set(vars(row)) == {"provider", "status"} for row in rows)
    return {row.provider: row.status for row in rows}


@pytest.fixture
def legacy(authenticated_client: Any, credential_blobs: Any, monkeypatch: Any) -> RealAppHarness:
    return RealAppHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- wiring ---------------------------------------------------------------------------------------


def test_the_app_wires_the_connection_backed_port(authenticated_client: Any) -> None:
    access = authenticated_client.app.state.provider_access

    assert isinstance(access, ConnectionBackedProviderAccess)
    assert isinstance(access, ProviderAccess)


# --- the marker read ------------------------------------------------------------------------------


def test_an_unreadable_marker_store_never_falls_back_to_the_legacy_credential(
    legacy: RealAppHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy.seed_blob(credential="tok")

    async def unavailable(self: PairAuthorityStore, account_id: str, provider: str) -> Any:
        raise RuntimeError("marker table unavailable")

    monkeypatch.setattr(PairAuthorityStore, "read", unavailable)

    with pytest.raises(RuntimeError, match="marker table unavailable"):
        _resolve(legacy)


# --- migrated pairs: the effective Connection is the authority ------------------------------------


def test_a_migrated_pair_serves_the_profile_credential_through_its_connection_without_re_entry(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_credential(credential="profile-token")
    connection_id = migrated.migrated["default"]

    target = _resolve(migrated)
    authorization = _authorize(migrated, target)

    assert target.credential_name == credential_name_for(migrated.account_id, "default")
    assert target.context_stamp.startswith(
        f"acct:{migrated.account_id}|conn:{connection_id}:active:"
    )
    assert authorization.headers["Authorization"] == "Bearer profile-token"
    assert migrated.last_used(connection_id)
    assert migrated.evicted() == []
    assert migrated.invalidated() == []
    # INVARIANT (no re-entry, no copy): the secret exists ONLY at the Profile's address.
    uuid_address = credential_service_for(
        credential_key_for(migrated.account_id, UUID(connection_id))
    )
    assert migrated.blobs.read(uuid_address, "default") is None


@pytest.mark.parametrize(
    ("state", "refusal"),
    [(SeedState.PENDING, TargetPending), (SeedState.ERROR, TargetReauthRequired)],
    ids=["pending", "error"],
)
def test_the_effective_connection_status_decides_the_refusal_not_the_document(
    migrated: ConnectionBackedHarness, state: SeedState, refusal: type[Exception]
) -> None:
    # A readable blob at the name address beside an authority that is not usable.
    migrated.seed_blob(credential="tok")
    migrated.seed_authority(state=state)

    with pytest.raises(refusal) as info:
        _resolve(migrated)

    raised = cast(Any, info.value)
    assert (raised.provider, raised.requested) == (PROVIDER, "default")
    if refusal is TargetReauthRequired:
        assert raised.reauth_url == LEGACY_URL
        assert raised.message is None


def test_a_migrated_pair_with_no_effective_connection_is_missing_whatever_the_document_says(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_blob(credential="tok")
    # The legitimate post-delete state: Connection-owned and empty (S1) — never the blob at the
    # name address.
    migrated.call(
        PairAuthorityStore().advance,
        migrated.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
    )

    with pytest.raises(TargetMissing) as info:
        _resolve(migrated)

    assert (info.value.provider, info.value.requested) == (PROVIDER, "default")


def test_a_revoked_effective_connection_is_never_served(migrated: ConnectionBackedHarness) -> None:
    migrated.seed_credential(credential="tok")
    connection_id = migrated.migrated["default"]
    store = OAuthConnectionStore()
    connection = migrated.call(store.get, migrated.account_id, connection_id)
    migrated.call(store.mark_revoked, connection)

    with pytest.raises(TargetMissing):
        _resolve(migrated)


def test_a_selector_naming_the_effective_label_reads_through_the_locator(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_blob(credential="profile-token")
    connection_id = migrated.seed_authority(label="work")

    # WHY: `work` is the effective Connection's own label, so its reference answers the selector,
    # locator-authoritative: the Connection's own UUID address holds nothing, and it must NOT be
    # marked errored because a caller sent a header the pair never had a document for.
    target = _resolve(migrated, Selector.from_header("work"))
    authorization = _authorize(migrated, target)

    assert target.credential_name == credential_name_for(migrated.account_id, "default")
    assert authorization.headers["Authorization"] == "Bearer profile-token"
    assert migrated.connection_status(connection_id) == "active"


def test_a_rejected_credential_marks_the_connection_and_leaves_the_document_untouched(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_credential(credential="tok")
    connection_id = migrated.migrated["default"]
    target = _resolve(migrated)
    migrated.break_credential(str(target.credential_name))

    with pytest.raises(TargetReauthRequired) as info:
        _authorize(migrated, target)

    assert info.value.reauth_url == LEGACY_URL
    assert info.value.message
    assert migrated.connection_status(connection_id) == "error"
    assert migrated.evicted() == [target.credential_name]
    assert migrated.invalidated() == [target.credential_name]


def test_a_dispatch_failure_marks_the_connection_and_rewrites_with_the_legacy_url(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_credential(credential="tok")
    connection_id = migrated.migrated["default"]
    target = _resolve(migrated)

    rewritten = migrated.call(
        migrated.access.record_dispatch_failure,
        target,
        401,
        {"code": "auth_required", "message": "token expired"},
        plugin=ANTHROPIC,
    )

    assert rewritten == {
        "code": "auth_required",
        "message": "token expired",
        "reauth_url": LEGACY_URL,
    }
    assert migrated.connection_status(connection_id) == "error"
    assert migrated.evicted() == [target.credential_name]
    assert migrated.invalidated() == [target.credential_name]


# --- op 6: availability reads the pair authority --------------------------------------------------


@pytest.mark.parametrize(
    ("state", "status"),
    [
        (SeedState.AUTHENTICATED, "connected"),
        (SeedState.PENDING, "pending"),
        (SeedState.ERROR, "error"),
    ],
    ids=["active", "pending", "error"],
)
def test_availability_reports_a_migrated_pair_from_its_connection_not_its_document(
    migrated: ConnectionBackedHarness, state: SeedState, status: str
) -> None:
    # The same readable blob in every case; only the Connection's status differs.
    migrated.seed_blob(credential="tok")
    migrated.seed_authority(state=state)

    assert _availability(migrated)[PROVIDER] == status


def test_availability_of_a_migrated_pair_without_an_effective_connection_is_not_connected(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_blob(credential="tok")
    migrated.call(
        PairAuthorityStore().advance,
        migrated.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
    )

    assert _availability(migrated)[PROVIDER] == "not_connected"


def test_availability_leaves_every_other_provider_not_connected(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_credential(state=SeedState.PENDING, credential=None)
    before = _availability(migrated)
    others = {provider: status for provider, status in before.items() if provider != PROVIDER}

    assert before[PROVIDER] == "pending"
    assert others
    assert all(status == "not_connected" for status in others.values())


def test_api_key_operational_outcomes_project_without_changing_lifecycle(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_credential(auth_type="api_key", credential="tok")
    connection_id = migrated.migrated["default"]
    target = _resolve(migrated)

    insufficient = migrated.call(
        migrated.access.begin_dispatch, target, plugin=ANTHROPIC, provider=PROVIDER
    )
    assert insufficient is not None
    migrated.call(
        migrated.access.record_dispatch_outcome,
        target,
        insufficient,
        "insufficient_credits",
        None,
        plugin=ANTHROPIC,
    )
    assert _availability(migrated)[PROVIDER] == "error"
    assert _resolve(migrated).credential_name == target.credential_name
    assert migrated.connection_status(connection_id) == "active"

    recovered = migrated.call(
        migrated.access.begin_dispatch, target, plugin=ANTHROPIC, provider=PROVIDER
    )
    assert recovered is not None
    migrated.call(
        migrated.access.record_dispatch_outcome,
        target,
        recovered,
        "connected",
        None,
        plugin=ANTHROPIC,
    )
    assert _availability(migrated)[PROVIDER] == "connected"

    rejected = migrated.call(
        migrated.access.begin_dispatch, target, plugin=ANTHROPIC, provider=PROVIDER
    )
    assert rejected is not None
    rewritten = migrated.call(
        migrated.access.record_dispatch_outcome,
        target,
        rejected,
        "needs_reauth",
        {"code": "auth_required", "message": "token expired"},
        plugin=ANTHROPIC,
    )
    assert rewritten == {
        "code": "auth_required",
        "message": "token expired",
        "reauth_url": target.reauth_url,
    }
    assert _availability(migrated)[PROVIDER] == "needs_reauth"
    with pytest.raises(TargetReauthRequired):
        _resolve(migrated)
    assert migrated.connection_status(connection_id) == "active"


def test_api_key_availability_requires_the_effective_credential_blob(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_credential(auth_type="api_key", credential="tok")
    target = _resolve(migrated)
    migrated.blobs.delete(credential_service_for(str(target.credential_name)), "default")

    assert _availability(migrated)[PROVIDER] == "needs_reauth"
    with pytest.raises(TargetReauthRequired):
        _resolve(migrated)
