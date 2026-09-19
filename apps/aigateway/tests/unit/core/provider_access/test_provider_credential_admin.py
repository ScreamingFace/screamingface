"""The Profile-backed `ProviderCredentialAdmin` (OME-1230, Stage A3 of OME-1138; spec §3.3 ops 7–9).

# FEATURE: the credential admin routes become shells; the OME-307 write bodies live behind this
# interface so Stage B can swap the backing without touching a route.
# INVARIANT (OME-307, re-asserted at the seam): index-row CAS FIRST, credential blob SECOND, one
# transaction, delete-wins. Rollback is the sole atomicity mechanism — a failed credential write
# leaves no index row behind.
# INVARIANT: no summary, projection, repr or refusal message ever carries a raw key.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest

from aigateway.core.credential_blob.store import CredentialBlobMutationConflict
from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.core.provider_access import (
    CredentialStoreUnavailable,
    CredentialSummary,
    ProfileBackedCredentialAdmin,
    ProviderCredentialAdmin,
    ProviderUnknown,
    TargetMissing,
    UnsupportedAuthMode,
    WriteConflict,
    provider_credential_admin_for,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.anthropic_provider.plugin import PLUGIN as ANTHROPIC

KEY = "sk-ant-api03-boundary-key-4242"
ROTATED = "sk-ant-api03-boundary-key-9999"


class _Seam:
    """The real app's admin interface plus the probes the contract needs."""

    def __init__(self, client: Any, blobs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self.client = client
        self.blobs = blobs
        self.app = client.app
        self.admin: ProviderCredentialAdmin = client.app.state.provider_credential_admin
        self.account_id: str = client.get("/v1/auth/me").json()["id"]
        self.index: ProfileIndexStore = client.app.state.profile_index
        self.store = client.app.state.credential_store
        self.evicted: list[str] = []
        self.invalidated: list[str] = []
        cache = credential_strategy_cache(client.app)
        real_evict = cache.evict

        def recording_evict(credential_name: str) -> int:
            self.evicted.append(credential_name)
            return real_evict(credential_name)

        monkeypatch.setattr(cache, "evict", recording_evict)
        monkeypatch.setattr(ANTHROPIC, "invalidate_profile_session", self.invalidated.append)

    def call(self, fn: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any) -> Any:
        return self.client.portal.call(partial(fn, *args, **kwargs))

    def set_api_key(self, name: str | None = "keyed", key: str = KEY, **kwargs: Any) -> Any:
        kwargs.setdefault("defaults", None)
        return self.call(
            self.admin.set_api_key,
            self.account_id,
            "anthropic",
            raw_api_key=key,
            legacy_name=name,
            **kwargs,
        )

    def profile(self, name: str = "keyed", provider: str = "anthropic") -> Profile | None:
        return self.call(self.index.get, self.account_id, provider, name)

    def blob(self, name: str = "keyed") -> str | None:
        return self.blobs.read(
            credential_service_for(credential_name_for(self.account_id, name)), "default"
        )

    def seed_oauth_profile(
        self, name: str, *, state: ProfileState = ProfileState.AUTHENTICATED
    ) -> Profile:
        profile = Profile(
            id=profile_id_for(self.account_id, "anthropic", name),
            account_id=self.account_id,
            provider="anthropic",
            name=name,
            state=state,
            auth_type="oauth",
            defaults=ProfileDefaults(model="anthropic/claude-sonnet-4-5"),
        )
        self.call(self.index.upsert, profile)
        return profile


@pytest.fixture
def seam(authenticated_client, credential_blobs, monkeypatch) -> _Seam:
    return _Seam(authenticated_client, credential_blobs, monkeypatch)


def _projection_of(profile: Profile) -> dict[str, Any]:
    return profile.model_dump(mode="json")


# --- wiring ---------------------------------------------------------------------------------


def test_the_app_wires_the_admin_interface_beside_the_read_port(seam: _Seam) -> None:
    assert isinstance(seam.admin, ProviderCredentialAdmin)
    assert isinstance(seam.admin, ProfileBackedCredentialAdmin)
    assert provider_credential_admin_for(seam.app) is seam.admin


def test_the_accessor_fills_only_an_absent_slot() -> None:
    app = SimpleNamespace(state=SimpleNamespace())

    created = provider_credential_admin_for(app)

    assert isinstance(created, ProfileBackedCredentialAdmin)
    assert app.state.provider_credential_admin is created
    assert provider_credential_admin_for(app) is created


# --- set_api_key (op 8) ---------------------------------------------------------------------


def test_set_api_key_publishes_an_authenticated_legacy_profile_and_its_blob(seam: _Seam) -> None:
    summary = seam.set_api_key("keyed", defaults=ProfileDefaults(max_tokens=2048))

    stored = seam.profile("keyed")
    assert stored is not None
    assert stored.state is ProfileState.AUTHENTICATED
    assert stored.auth_type == "api_key"
    assert stored.account_label == "API key ····4242"
    assert stored.scopes == []
    assert stored.defaults == ProfileDefaults(max_tokens=2048)
    assert json.loads(seam.blob("keyed") or "{}") == {"auth_type": "api_key", "api_key": KEY}

    assert isinstance(summary, CredentialSummary)
    assert (summary.provider, summary.selector, summary.auth_type, summary.state) == (
        "anthropic",
        "keyed",
        "api_key",
        "authenticated",
    )
    # F1: the one opaque window-only projection IS today's Profile JSON, byte for byte.
    assert summary.legacy_projection == _projection_of(stored)


def test_set_api_key_names_the_default_legacy_profile_when_no_name_is_given(seam: _Seam) -> None:
    summary = seam.set_api_key(None)

    assert summary.selector == "default"
    assert seam.profile("default") is not None


def test_set_api_key_replaces_defaults_wholesale_and_keeps_them_when_omitted(seam: _Seam) -> None:
    seam.set_api_key("keyed", defaults=ProfileDefaults(model="anthropic/x", max_tokens=1024))

    seam.set_api_key("keyed", key=ROTATED, defaults=ProfileDefaults(temperature=0.2))
    replaced = seam.profile("keyed")
    assert replaced is not None
    # Wholesale: the earlier model and max_tokens are GONE, not merged.
    assert replaced.defaults == ProfileDefaults(temperature=0.2)
    assert replaced.account_label == "API key ····9999"

    seam.set_api_key("keyed", key=KEY, defaults=None)
    kept = seam.profile("keyed")
    assert kept is not None
    # Omitted: today's PUT without a `defaults` field leaves the stored defaults untouched.
    assert kept.defaults == ProfileDefaults(temperature=0.2)
    assert json.loads(seam.blob("keyed") or "{}")["api_key"] == KEY


def test_set_api_key_writes_the_index_row_before_the_credential(seam: _Seam, monkeypatch) -> None:
    calls: list[str] = []
    real_upsert = seam.index.upsert
    real_write, real_mutate = seam.store.write, seam.store.mutate

    async def _index(*args: Any, **kwargs: Any) -> None:
        calls.append("index")
        await real_upsert(*args, **kwargs)

    async def _write(service: str, account: str, value: str) -> None:
        calls.append("credential")
        await real_write(service, account, value)

    async def _mutate(service: str, account: str, mutator: Any) -> None:
        # The index store publishes through `mutate`; only a NON-index service is the credential.
        calls.append("index" if service == "aigateway:index" else "credential")
        await real_mutate(service, account, mutator)

    monkeypatch.setattr(seam.index, "upsert", _index)
    monkeypatch.setattr(seam.store, "write", _write)
    monkeypatch.setattr(seam.store, "mutate", _mutate)

    seam.set_api_key("keyed")

    assert "credential" in calls
    assert calls.index("index") < calls.index("credential")
    assert calls[: calls.index("credential")] == ["index"] * calls.index("credential")


def test_set_api_key_over_an_observed_profile_loses_to_a_concurrent_delete(
    seam: _Seam, monkeypatch
) -> None:
    seam.seed_oauth_profile("keyed")
    real_get = seam.index.get
    real_remove = seam.index.remove

    async def _observe_then_lose_to_a_delete(*args: Any, **kwargs: Any) -> Profile | None:
        # The other worker's delete COMMITS between our read and our publish — outside our
        # transaction, so it must survive our rollback exactly as a real concurrent commit would.
        observed = await real_get(*args, **kwargs)
        if observed is not None:
            await real_remove(observed.id)
        return observed

    monkeypatch.setattr(seam.index, "get", _observe_then_lose_to_a_delete)

    with pytest.raises(WriteConflict) as info:
        seam.set_api_key("keyed")

    assert (info.value.kind, info.value.subject) == ("superseded", "profile")
    assert (info.value.provider, info.value.requested) == ("anthropic", "keyed")
    # Delete wins: nothing resurrected, no orphaned credential.
    assert seam.profile("keyed") is None
    assert seam.blob("keyed") is None


def test_set_api_key_refuses_when_the_credential_store_is_unavailable_and_rolls_back(
    seam: _Seam, monkeypatch
) -> None:
    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"store exploded while holding {KEY}")

    # WHY only `write`: the API-key strategy persists its blob through `write`; the index row
    # publishes through `mutate` and must SUCCEED first so the rollback below is what removes it.
    monkeypatch.setattr(seam.store, "write", _boom)

    with pytest.raises(CredentialStoreUnavailable) as info:
        seam.set_api_key("keyed")

    assert info.value.description == "API-key credentials"
    assert KEY not in str(info.value)
    assert KEY not in repr(info.value)
    # One transaction: the index publish rolled back with the failed credential write.
    assert seam.profile("keyed") is None
    assert seam.blob("keyed") is None


def test_set_api_key_reports_index_retry_exhaustion_as_a_write_conflict(
    seam: _Seam, monkeypatch
) -> None:
    async def _exhausted(*_args: Any, **_kwargs: Any) -> None:
        raise CredentialBlobMutationConflict("forced contention")

    monkeypatch.setattr(seam.index, "upsert", _exhausted)

    with pytest.raises(WriteConflict) as info:
        seam.set_api_key("keyed")

    assert (info.value.kind, info.value.subject) == ("retry_exhausted", "profile")
    assert "forced contention" not in str(info.value)
    assert seam.blob("keyed") is None


def test_set_api_key_refuses_an_unknown_provider(seam: _Seam) -> None:
    with pytest.raises(ProviderUnknown) as info:
        seam.call(
            seam.admin.set_api_key,
            seam.account_id,
            "nope",
            raw_api_key=KEY,
            legacy_name="keyed",
            defaults=None,
        )

    assert info.value.provider == "nope"


def test_set_api_key_refuses_a_provider_without_an_api_key_strategy(seam: _Seam) -> None:
    with pytest.raises(UnsupportedAuthMode) as info:
        seam.call(
            seam.admin.set_api_key,
            seam.account_id,
            "codex",
            raw_api_key=KEY,
            legacy_name="keyed",
            defaults=None,
        )

    assert (info.value.auth_mode, info.value.provider) == ("api_key", "codex")
    assert seam.profile("keyed", provider="codex") is None


def test_set_api_key_invalidates_the_session_and_evicts_the_cached_strategy(seam: _Seam) -> None:
    seam.set_api_key("keyed")

    credential_name = credential_name_for(seam.account_id, "keyed")
    assert seam.evicted == [credential_name]
    assert seam.invalidated == [credential_name]


# --- delete (op 9) --------------------------------------------------------------------------


def test_delete_removes_the_row_and_the_blob_then_invalidates(seam: _Seam) -> None:
    seam.set_api_key("keyed")
    seam.evicted.clear()
    seam.invalidated.clear()

    seam.call(seam.admin.delete, seam.account_id, "anthropic", legacy_name="keyed")

    assert seam.profile("keyed") is None
    assert seam.blob("keyed") is None
    credential_name = credential_name_for(seam.account_id, "keyed")
    assert seam.evicted == [credential_name]
    assert seam.invalidated == [credential_name]


def test_delete_removes_the_index_row_before_the_credential(seam: _Seam, monkeypatch) -> None:
    seam.set_api_key("keyed")
    calls: list[str] = []
    real_remove = seam.index.remove
    real_delete = seam.store.delete

    async def _remove(profile_id: str) -> None:
        calls.append("index")
        await real_remove(profile_id)

    async def _delete(service: str, account: str) -> None:
        calls.append("credential")
        await real_delete(service, account)

    monkeypatch.setattr(seam.index, "remove", _remove)
    monkeypatch.setattr(seam.store, "delete", _delete)

    seam.call(seam.admin.delete, seam.account_id, "anthropic", legacy_name="keyed")

    assert calls == ["index", "credential"]


def test_delete_refuses_an_unknown_provider_and_a_missing_target(seam: _Seam) -> None:
    with pytest.raises(ProviderUnknown) as unknown:
        seam.call(seam.admin.delete, seam.account_id, "nope", legacy_name="keyed")
    assert unknown.value.provider == "nope"

    with pytest.raises(TargetMissing) as missing:
        seam.call(seam.admin.delete, seam.account_id, "anthropic", legacy_name="absent")
    assert (missing.value.provider, missing.value.requested) == ("anthropic", "absent")


# --- list (op 7) ----------------------------------------------------------------------------


def test_list_returns_masked_summaries_carrying_the_legacy_projection(seam: _Seam) -> None:
    seam.set_api_key("keyed")
    oauth = seam.seed_oauth_profile("work", state=ProfileState.PENDING)

    everything = seam.call(seam.admin.list, seam.account_id)
    only_anthropic = seam.call(seam.admin.list, seam.account_id, "anthropic")
    nothing = seam.call(seam.admin.list, seam.account_id, "codex")

    assert isinstance(everything, tuple)
    assert {s.selector for s in everything} == {"keyed", "work"}
    assert everything == only_anthropic
    assert nothing == ()
    by_selector = {s.selector: s for s in everything}
    assert by_selector["work"].legacy_projection == _projection_of(oauth)
    assert (by_selector["work"].auth_type, by_selector["work"].state) == ("oauth", "pending")
    keyed = seam.profile("keyed")
    assert keyed is not None
    assert by_selector["keyed"].legacy_projection == _projection_of(keyed)


def test_no_summary_or_projection_carries_the_raw_key(seam: _Seam) -> None:
    published = seam.set_api_key("keyed")
    listed = seam.call(seam.admin.list, seam.account_id)

    for summary in (published, *listed):
        assert KEY not in repr(summary)
        assert KEY not in json.dumps(summary.legacy_projection)
        assert "api_key" not in summary.legacy_projection
