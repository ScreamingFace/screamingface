"""Pair-authority routing behind the provider-access port (OME-1208, Stage B S2'; D14).

# FEATURE: Stage B Target — the port reads the pair marker on every resolve; a `migrated` pair is
# served from its effective Connection, an unmarked or `quarantined` pair by today's Profile-backed
# path, byte for byte. Reads go through the stored `credential_locator`, so a migrated Connection
# serves the Profile's blob with no secret re-entry.
# INVARIANT: the legacy document's own state is never authority for a migrated pair; the effective
# Connection's status decides. An unreadable marker store is an error, never a silent fall-back to
# the legacy credential.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from connection_backed_harness import ConnectionBackedHarness
from provider_access_harness import ANTHROPIC, PROVIDER, ProfileBackedHarness

from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import ProfileDefaults, ProfileState, credential_name_for
from aigateway.core.provider_access import (
    ConnectionBackedProviderAccess,
    PairAuthorityStore,
    ProfileBackedProviderAccess,
    ProviderAccess,
    Selector,
    TargetMissing,
    TargetPending,
    TargetReauthRequired,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

DEFAULT = Selector.from_header(None)
LEGACY_URL = f"/v1/auth/{PROVIDER}/profiles/default"


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


def _document(harness: Any, name: str = "default") -> Any:
    index = ProfileIndexStore(credential_store=harness.blobs.store)
    return harness.call(index.get, harness.account_id, PROVIDER, name)


@pytest.fixture
def legacy(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ProfileBackedHarness:
    return ProfileBackedHarness(authenticated_client, credential_blobs, monkeypatch)


@pytest.fixture
def migrated(
    authenticated_client: Any, credential_blobs: Any, monkeypatch: Any
) -> ConnectionBackedHarness:
    return ConnectionBackedHarness(authenticated_client, credential_blobs, monkeypatch)


# --- wiring ---------------------------------------------------------------------------------------


def test_the_app_wires_the_connection_backed_port_within_the_profile_backed_family(
    authenticated_client: Any,
) -> None:
    access = authenticated_client.app.state.provider_access

    assert isinstance(access, ConnectionBackedProviderAccess)
    # WHY: every prior pin and seam (`isinstance`, patched `ProfileBackedProviderAccess.resolve` /
    # `.authorize`) keeps holding — the transition backing IS the Profile-backed family plus the
    # per-pair Connection authority, and the legacy branch is inherited, not copied.
    assert isinstance(access, ProfileBackedProviderAccess)
    assert isinstance(access, ProviderAccess)


# --- unmarked and quarantined pairs: the legacy path, unchanged ----------------------------------


def test_an_unmarked_pair_is_served_by_the_legacy_implementation_after_one_marker_read(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy.seed_profile(credential="tok")
    marker_reads: list[tuple[str, str]] = []
    real_read = PairAuthorityStore.read

    async def counting_read(self: PairAuthorityStore, account_id: str, provider: str) -> Any:
        marker_reads.append((account_id, provider))
        return await real_read(self, account_id, provider)

    legacy_calls: list[tuple[Any, ...]] = []
    real_resolve = ProfileBackedProviderAccess.resolve

    async def spying_resolve(self: Any, *args: Any, **kwargs: Any) -> Any:
        legacy_calls.append(args)
        return await real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(PairAuthorityStore, "read", counting_read)
    monkeypatch.setattr(ProfileBackedProviderAccess, "resolve", spying_resolve)

    target = _resolve(legacy)

    assert marker_reads == [(legacy.account_id, PROVIDER)]
    assert len(legacy_calls) == 1
    assert target.credential_name == credential_name_for(legacy.account_id, "default")
    assert target.context_stamp.startswith(f"acct:{legacy.account_id}|prof:")


def test_a_quarantined_pair_keeps_the_legacy_profile_authority(
    legacy: ProfileBackedHarness,
) -> None:
    legacy.seed_profile(credential="tok")
    legacy.call(
        PairAuthorityStore().advance,
        legacy.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="quarantined",
        migration_note="profile and connection could not be proven the same",
    )

    target = _resolve(legacy)
    authorization = _authorize(legacy, target)

    assert target.credential_name == credential_name_for(legacy.account_id, "default")
    assert target.context_stamp.startswith(f"acct:{legacy.account_id}|prof:")
    assert authorization.headers["Authorization"] == "Bearer tok"
    marker = legacy.call(PairAuthorityStore().read, legacy.account_id, PROVIDER)
    assert (marker.migration_state, marker.generation) == ("quarantined", 1)


def test_defaults_never_consult_the_marker(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy.seed_profile(defaults=ProfileDefaults(max_tokens=64))

    async def unavailable(self: PairAuthorityStore, account_id: str, provider: str) -> Any:
        raise RuntimeError("marker table unavailable")

    monkeypatch.setattr(PairAuthorityStore, "read", unavailable)

    # D16 (a): request defaults live in the legacy index until the Stage C cutover; op 1 sits ahead
    # of the response cache and must stay a plain index read.
    defaults = legacy.call(legacy.access.defaults_for, legacy.account_id, PROVIDER, DEFAULT)

    assert defaults == ProfileDefaults(max_tokens=64)


def test_an_unreadable_marker_store_never_falls_back_to_the_legacy_credential(
    legacy: ProfileBackedHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy.seed_profile(credential="tok")

    async def unavailable(self: PairAuthorityStore, account_id: str, provider: str) -> Any:
        raise RuntimeError("marker table unavailable")

    monkeypatch.setattr(PairAuthorityStore, "read", unavailable)

    with pytest.raises(RuntimeError, match="marker table unavailable"):
        _resolve(legacy)


# --- migrated pairs: the effective Connection is the authority ------------------------------------


def test_a_migrated_pair_serves_the_profile_credential_through_its_connection_without_re_entry(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile(credential="profile-token")
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
    [(ProfileState.PENDING, TargetPending), (ProfileState.ERROR, TargetReauthRequired)],
    ids=["pending", "error"],
)
def test_the_effective_connection_status_decides_the_refusal_not_the_document(
    migrated: ConnectionBackedHarness, state: ProfileState, refusal: type[Exception]
) -> None:
    # A stale, still-AUTHENTICATED document beside an authority that is not usable.
    migrated.seed_document(state=ProfileState.AUTHENTICATED, credential="tok")
    migrated.seed_authority(state=state)

    with pytest.raises(refusal) as info:
        _resolve(migrated)

    raised = cast(Any, info.value)
    assert (raised.provider, raised.requested) == (PROVIDER, "default")
    if refusal is TargetReauthRequired:
        assert raised.reauth_url == LEGACY_URL
        assert raised.message is None
    assert _document(migrated).state is ProfileState.AUTHENTICATED


def test_a_migrated_pair_with_no_effective_connection_is_missing_whatever_the_document_says(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(credential="tok")
    # The legitimate post-delete state: Connection-owned and empty (S1) — never the document.
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
    migrated.seed_profile(credential="tok")
    connection_id = migrated.migrated["default"]
    store = OAuthConnectionStore()
    connection = migrated.call(store.get, migrated.account_id, connection_id)
    migrated.call(store.mark_revoked, connection)

    with pytest.raises(TargetMissing):
        _resolve(migrated)


def test_a_selector_naming_no_document_takes_the_legacy_path_and_reads_through_the_locator(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(credential="profile-token")
    connection_id = migrated.seed_authority(label="work")

    # `work` names no legacy document → today's Connection-label path, now locator-authoritative:
    # the effective Connection's own UUID address holds nothing, and it must NOT be marked errored
    # because a caller sent a header the pair never had a document for.
    target = _resolve(migrated, Selector.from_header("work"))
    authorization = _authorize(migrated, target)

    assert target.credential_name == credential_name_for(migrated.account_id, "default")
    assert authorization.headers["Authorization"] == "Bearer profile-token"
    assert migrated.connection_status(connection_id) == "active"


def test_a_rejected_credential_marks_the_connection_and_leaves_the_document_untouched(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile(credential="tok")
    connection_id = migrated.migrated["default"]
    target = _resolve(migrated)
    migrated.break_credential(str(target.credential_name))

    with pytest.raises(TargetReauthRequired) as info:
        _authorize(migrated, target)

    assert info.value.reauth_url == LEGACY_URL
    assert info.value.message
    assert migrated.connection_status(connection_id) == "error"
    # INVARIANT (D14): one write owner — the Connection took the mark, the document did not.
    assert _document(migrated).state is ProfileState.AUTHENTICATED
    assert migrated.evicted() == [target.credential_name]
    assert migrated.invalidated() == [target.credential_name]


def test_a_dispatch_failure_marks_the_connection_and_rewrites_with_the_legacy_url(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile(credential="tok")
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
    assert _document(migrated).state is ProfileState.AUTHENTICATED
    assert migrated.evicted() == [target.credential_name]
    assert migrated.invalidated() == [target.credential_name]


# --- op 6: availability reads the pair authority --------------------------------------------------


@pytest.mark.parametrize(
    ("state", "status"),
    [
        (ProfileState.AUTHENTICATED, "connected"),
        (ProfileState.PENDING, "pending"),
        (ProfileState.ERROR, "error"),
    ],
    ids=["active", "pending", "error"],
)
def test_availability_reports_a_migrated_pair_from_its_connection_not_its_document(
    migrated: ConnectionBackedHarness, state: ProfileState, status: str
) -> None:
    # The stale document would report `connected` in every case.
    migrated.seed_document(state=ProfileState.AUTHENTICATED, credential="tok")
    migrated.seed_authority(state=state)

    assert _availability(migrated)[PROVIDER] == status


def test_availability_of_a_migrated_pair_without_an_effective_connection_is_not_connected(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_document(credential="tok")
    migrated.call(
        PairAuthorityStore().advance,
        migrated.account_id,
        PROVIDER,
        expected_generation=0,
        migration_state="migrated",
    )

    assert _availability(migrated)[PROVIDER] == "not_connected"


def test_availability_leaves_every_other_provider_on_the_legacy_precedence(
    migrated: ConnectionBackedHarness,
) -> None:
    migrated.seed_profile(state=ProfileState.PENDING, credential=None)
    before = _availability(migrated)
    others = {provider: status for provider, status in before.items() if provider != PROVIDER}

    assert before[PROVIDER] == "pending"
    assert others
    assert all(status == "not_connected" for status in others.values())
