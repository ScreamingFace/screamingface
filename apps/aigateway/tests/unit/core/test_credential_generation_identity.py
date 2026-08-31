"""OME-1026 remediation F3 — the private cache identity needs a real generation.

FEATURE: a private snapshot describes exactly ONE credential generation. Rotate the
key and the previous listing becomes unreadable, not merely scheduled for eviction.

STORY: as an account owner I replace a leaked API key and no worker anywhere can
still show me — or bill me for — what the old key could call.

INVARIANT (why a wall-clock stamp was not enough): the identity previously embedded
``last_refreshed_at``, assigned with ``datetime.now(UTC)`` at publication. Two
replacements inside one clock tick produce EQUAL stamps, so the second credential
inherited the first's cache identity and the first's snapshot was served as fresh
under it. Process-local invalidation hid this on the worker that did the rotation and
could not help any other worker at all. The generation must therefore be a durable,
strictly-advancing token written atomically with the credential — not a timestamp.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio

from aigateway.core.model_discovery_scope import DiscoveryScope, ProviderAuthContext
from aigateway.core.parameter_discovery import RawResponse
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_model_catalog import ProfileModelCatalog
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.core.profile_snapshot_store import profile_credential_revision

# The whole point: every profile below shares ONE stamp.
_FROZEN = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)

_SOURCE = ModelDiscoverySource(
    key="fake:models:list",
    revision="fake-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)


class _NoClient:
    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        raise AssertionError(f"DIAL ATTEMPTED: {url}")


def _entries(*names: str) -> tuple[ModelEntry, ...]:
    return tuple(
        ModelEntry(model_name=name, litellm_params={"model": f"fake/{name}"}) for name in names
    )


@dataclass
class _FakePlugin:
    custom_llm_provider: str = "fake"
    result: tuple[ModelEntry, ...] = field(default_factory=lambda: _entries("from-key-1"))
    dials: int = 0

    def model_discovery_scope(self) -> DiscoveryScope:
        return DiscoveryScope.PROFILE_CREDENTIAL

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return _SOURCE

    def profile_discovery_unsupported_reason(self, *, auth_type: str) -> str | None:
        return None

    async def discover_profile_models(
        self, *, client: Any, limits: Any = None, auth: ProviderAuthContext
    ) -> tuple[ModelEntry, ...] | None:
        self.dials += 1
        return self.result


async def _auth() -> ProviderAuthContext:
    return ProviderAuthContext(headers={"x-api-key": "whatever"}, auth_type="api_key")


def _profile(*, account_id: str = "acct-a", name: str = "work") -> Profile:
    """A profile whose stamp NEVER moves — the collision the fix must survive."""
    return Profile(
        id=profile_id_for(account_id, "fake", name),
        account_id=account_id,
        provider="fake",
        name=name,
        state=ProfileState.AUTHENTICATED,
        auth_type="api_key",
        last_refreshed_at=_FROZEN,
    )


@pytest_asyncio.fixture
async def catalog():
    cat = ProfileModelCatalog(max_identities=8, max_inflight_refreshes=4)
    try:
        yield cat
    finally:
        await cat.aclose()


async def _ask(catalog: ProfileModelCatalog, plugin: Any, *, generation: int):
    return await catalog.snapshot_for(
        plugin,
        account_id="acct-a",
        profile=_profile(),
        client=_NoClient(),
        limits=None,
        auth_provider=_auth,
        credential_generation=generation,
    )


# ── the revision itself ───────────────────────────────────────────────────────


def test_the_revision_is_derived_from_the_generation_not_the_clock() -> None:
    profile = _profile()

    first = profile_credential_revision(profile, 1)
    second = profile_credential_revision(profile, 2)

    assert first != second, "a new credential generation must be a new identity"
    assert profile_credential_revision(profile, 1) == first, "and it must be stable"
    # INVARIANT: never credential-derived, and no longer clock-derived either.
    assert _FROZEN.isoformat() not in first
    assert "whatever" not in first


def test_the_revision_still_separates_an_auth_type_switch() -> None:
    """Defence in depth: a switch bumps the generation too, but this costs nothing."""
    api_key = _profile()
    oauth = api_key.model_copy(update={"auth_type": "oauth"})

    assert profile_credential_revision(api_key, 7) != profile_credential_revision(oauth, 7)


# ── the reported adversarial schedules ────────────────────────────────────────


@pytest.mark.asyncio
async def test_replacement_within_one_clock_tick_retires_the_old_snapshot(catalog) -> None:
    """The reproduced defect: equal timestamps, different credentials."""
    plugin = _FakePlugin()

    first = await _ask(catalog, plugin, generation=1)
    assert [entry.model_name for entry in first.entries or ()] == ["from-key-1"]

    # Same profile, same stamp — only the durable generation moved.
    plugin.result = _entries("from-key-2")
    second = await _ask(catalog, plugin, generation=2)

    assert [entry.model_name for entry in second.entries or ()] == ["from-key-2"], (
        "the old key's catalog was served under the new key"
    )
    assert plugin.dials == 2, "the new generation must actually re-dial"


@pytest.mark.asyncio
async def test_another_worker_cannot_serve_the_previous_generation(catalog) -> None:
    """Worker A never sees worker B's invalidation — the identity must carry the fence.

    # WHY this is the load-bearing case: invalidation is process-local by design, so
    # correctness across workers cannot depend on it running. Worker A here does NOT
    # invalidate anything; it simply reads the profile again and computes the identity.
    """
    worker_a = catalog
    worker_b = ProfileModelCatalog(max_identities=8, max_inflight_refreshes=4)
    try:
        plugin = _FakePlugin()
        await _ask(worker_a, plugin, generation=1)  # A caches generation 1
        assert plugin.dials == 1

        # B publishes a new credential and invalidates ONLY its own process.
        plugin.result = _entries("from-key-2")
        worker_b.invalidate(account_id="acct-a", provider="fake", profile_name="work")

        served = await _ask(worker_a, plugin, generation=2)

        assert [entry.model_name for entry in served.entries or ()] == ["from-key-2"]
        assert plugin.dials == 2
    finally:
        await worker_b.aclose()


@pytest.mark.asyncio
async def test_the_same_generation_is_still_served_from_cache(catalog) -> None:
    """The fix must not defeat caching: an unchanged credential re-uses its snapshot."""
    plugin = _FakePlugin()

    await _ask(catalog, plugin, generation=4)
    again = await _ask(catalog, plugin, generation=4)

    assert plugin.dials == 1, "an unchanged generation must not re-dial"
    assert again.status == "fresh"


# ── the durable store: the generation must survive a restart ──────────────────


@pytest.mark.asyncio
async def test_the_generation_is_persisted_and_advances_on_every_publication(
    credential_blobs: Any,
) -> None:
    """It lives in the index ROW, so another worker and a restart both observe it."""
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    profile = _profile()

    await store.upsert(profile)
    first = await store.get_with_credential_generation("acct-a", "fake", "work")
    await store.upsert(profile)  # a second publication, identical stamp
    second = await store.get_with_credential_generation("acct-a", "fake", "work")

    assert first is not None and second is not None
    assert second[1] > first[1], "each credential publication advances the generation"
    # A FRESH store object over the same row — the restart / other-worker case.
    reread = await ProfileIndexStore(
        credential_store=credential_blobs.store
    ).get_with_credential_generation("acct-a", "fake", "work")
    assert reread is not None and reread[1] == second[1]


@pytest.mark.asyncio
async def test_a_deleted_profile_does_not_reset_its_generation(credential_blobs: Any) -> None:
    """INVARIANT: recreating a name must not rewind to an identity a snapshot may hold.

    # WHY the map entry deliberately outlives the profile: clearing it on delete would
    # restart at 1, and a cached snapshot from the ORIGINAL generation 1 — on this or
    # any other worker — would match the recreated profile's identity exactly.
    """
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    profile = _profile()
    await store.upsert(profile)
    before = await store.get_with_credential_generation("acct-a", "fake", "work")
    assert before is not None

    await store.remove(profile.id)
    await store.upsert(profile)

    after = await store.get_with_credential_generation("acct-a", "fake", "work")
    assert after is not None and after[1] > before[1]


@pytest.mark.asyncio
async def test_concurrent_publications_never_share_a_generation(credential_blobs: Any) -> None:
    """The bump happens inside the index CAS, so racing writers cannot collide."""
    store = ProfileIndexStore(credential_store=credential_blobs.store)
    profile = _profile()
    await store.upsert(profile)

    await asyncio.gather(*(store.upsert(profile) for _ in range(5)))

    final = await store.get_with_credential_generation("acct-a", "fake", "work")
    assert final is not None
    assert final[1] == 6, f"six publications must produce six distinct generations: {final[1]}"
