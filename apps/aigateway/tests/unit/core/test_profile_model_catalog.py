"""OME-1026 rework U3 — the PRIVATE per-profile live model catalog.

FEATURE: profile-scoped live model discovery. A provider whose catalog answers
"what may THIS credential call" gets one private snapshot per authenticated
account profile, served only to that profile's owner.

STORY: as an account owner who stored an Anthropic API key, I open my profile's
model list and see the models my own key can actually call — without re-entering
the key, and without my entitlements becoming the deployment's public listing.

INVARIANT (the load-bearing one, asserted repeatedly below): a snapshot derived
from one account's credential can never be served to another account, and never
reaches the shared ``ModelCatalog`` / ``GET /v1/models`` path at all.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio

from aigateway.core.model_discovery_scope import DiscoveryScope, ProviderAuthContext
from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry
from aigateway.core.profile_model_catalog import (
    ProfileModelCatalog,
    profile_credential_revision,
)
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for

_SOURCE = ModelDiscoverySource(
    key="fake:models:list",
    revision="fake-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)


class _FakeClock:
    """Deterministic monotonic time — TTL boundaries must not depend on wall time."""

    def __init__(self) -> None:
        self._t = 1000.0

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class _NoClient:
    """The transport seam, protocol-shaped — and a tripwire.

    # WHY not ``object()``: the fake plugin owns the dial in these tests, so the
    # client must never be touched. Giving the sentinel the REAL
    # ``DiscoveryHttpClient`` signature means the type checker confirms the catalog
    # forwards a transport it could actually use, while any attempt to use it here
    # fails the test loudly instead of returning a plausible stub value.
    """

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        raise AssertionError(f"DIAL ATTEMPTED: {url}")


def _entries(*names: str) -> tuple[ModelEntry, ...]:
    return tuple(
        ModelEntry(model_name=name, litellm_params={"model": f"fake/{name}"}) for name in names
    )


@dataclass
class _FakePlugin:
    """A PROFILE_CREDENTIAL provider under the plugin contract's private hooks."""

    custom_llm_provider: str = "fake"
    scope: DiscoveryScope = DiscoveryScope.PROFILE_CREDENTIAL
    source: ModelDiscoverySource | None = _SOURCE
    unsupported_reason: str | None = None
    result: tuple[ModelEntry, ...] | None = field(default_factory=lambda: _entries("m-1", "m-2"))
    raises: BaseException | None = None
    gate: asyncio.Event | None = None
    dials: list[ProviderAuthContext] = field(default_factory=list)

    def model_discovery_scope(self) -> DiscoveryScope:
        return self.scope

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return self.source

    def profile_discovery_unsupported_reason(self, *, auth_type: str) -> str | None:
        return self.unsupported_reason

    async def discover_profile_models(
        self, *, client: Any, limits: Any = None, auth: ProviderAuthContext
    ) -> tuple[ModelEntry, ...] | None:
        self.dials.append(auth)
        if self.gate is not None:
            await self.gate.wait()
        if self.raises is not None:
            raise self.raises
        return self.result


@dataclass
class _FakeAuth:
    """Stands in for the profile's credential strategy: counts DECRYPTIONS."""

    headers: dict[str, str] = field(default_factory=lambda: {"x-api-key": "secret-value"})
    calls: int = 0

    async def __call__(self) -> ProviderAuthContext:
        self.calls += 1
        return ProviderAuthContext(headers=dict(self.headers), auth_type="api_key")


def _profile(
    *,
    account_id: str = "acct-a",
    name: str = "work",
    state: ProfileState = ProfileState.AUTHENTICATED,
    auth_type: str = "api_key",
    refreshed_at: datetime | None = None,
) -> Profile:
    return Profile(
        id=profile_id_for(account_id, "fake", name),
        account_id=account_id,
        provider="fake",
        name=name,
        state=state,
        auth_type=auth_type,  # type: ignore[arg-type]
        last_refreshed_at=refreshed_at or datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )


@pytest_asyncio.fixture
async def catalog():
    cat = ProfileModelCatalog(clock=_FakeClock(), max_identities=8, max_inflight_refreshes=4)
    try:
        yield cat
    finally:
        await cat.aclose()


async def _ask(
    catalog: ProfileModelCatalog,
    plugin: Any,
    auth: Any,
    profile: Profile,
    *,
    generation: int = 1,
):
    # OME-1026 F3: the credential generation is now an explicit input. It comes from the
    # profile index's durable ``credential_generations`` map, not from the wall clock.
    return await catalog.snapshot_for(
        plugin,
        account_id=profile.account_id,
        profile=profile,
        client=_NoClient(),
        limits=None,
        auth_provider=auth,
        credential_generation=generation,
    )


# ── refusal gates: zero egress AND zero credential reads ──────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "reason"),
    [
        (DiscoveryScope.NONE, "discovery_disabled"),
        (DiscoveryScope.PUBLIC_GLOBAL, "not_profile_scoped"),
    ],
)
async def test_a_non_private_scope_never_dials_and_never_reads_a_credential(
    catalog, scope, reason
) -> None:
    """INVARIANT: only a PROFILE_CREDENTIAL provider has a private path at all."""
    plugin = _FakePlugin(scope=scope)
    auth = _FakeAuth()

    snap = await _ask(catalog, plugin, auth, _profile())

    assert (snap.status, snap.reason) == ("fallback", reason)
    assert snap.entries is None
    assert plugin.dials == [], "no upstream dial"
    assert auth.calls == 0, "no credential decryption"


@pytest.mark.asyncio
async def test_an_unauthenticated_profile_is_refused_before_any_credential_read(catalog) -> None:
    plugin = _FakePlugin()
    auth = _FakeAuth()

    snap = await _ask(catalog, plugin, auth, _profile(state=ProfileState.PENDING))

    assert (snap.status, snap.reason) == ("fallback", "profile_not_authenticated")
    assert plugin.dials == [] and auth.calls == 0


@pytest.mark.asyncio
async def test_an_unsupported_auth_type_is_refused_before_any_credential_read(catalog) -> None:
    """FEATURE: an OAuth profile spends ZERO credentialed requests to learn it cannot.

    # WHY it matters here and not only in the provider: the refusal must happen
    # before the credential is decrypted, so "OAuth ⇒ no Models-API egress" holds by
    # construction rather than by a 401 handler.
    """
    plugin = _FakePlugin(unsupported_reason="unsupported_auth_type")
    auth = _FakeAuth()

    snap = await _ask(catalog, plugin, auth, _profile(auth_type="oauth"))

    assert (snap.status, snap.reason) == ("fallback", "unsupported_auth_type")
    assert plugin.dials == [] and auth.calls == 0


@pytest.mark.asyncio
async def test_no_declared_source_means_no_private_discovery(catalog) -> None:
    plugin = _FakePlugin(source=None)
    auth = _FakeAuth()

    snap = await _ask(catalog, plugin, auth, _profile())

    assert (snap.status, snap.reason) == ("fallback", "discovery_disabled")
    assert plugin.dials == [] and auth.calls == 0


@pytest.mark.asyncio
async def test_an_empty_auth_context_fails_closed_without_dialing(catalog) -> None:
    """A profile whose credential vanished must not produce an unauthenticated dial."""
    plugin = _FakePlugin()
    auth = _FakeAuth(headers={})

    snap = await _ask(catalog, plugin, auth, _profile())

    assert (snap.status, snap.reason) == ("fallback", "missing_credential")
    assert plugin.dials == [], "the provider is never asked to dial without a credential"


# ── the happy path, and the credential is read once, not per request ──────────


@pytest.mark.asyncio
async def test_a_cold_profile_dials_once_and_serves_its_own_models(catalog) -> None:
    plugin = _FakePlugin()
    auth = _FakeAuth()

    snap = await _ask(catalog, plugin, auth, _profile())

    assert snap.status == "fresh"
    assert snap.reason is None
    assert snap.provider == "fake" and snap.profile_name == "work"
    assert [entry.model_name for entry in snap.entries or ()] == ["m-1", "m-2"]
    assert len(plugin.dials) == 1 and auth.calls == 1


@pytest.mark.asyncio
async def test_a_cached_profile_is_served_without_re_reading_the_credential(catalog) -> None:
    """INVARIANT: a cache hit decrypts nothing.

    # WHY: every avoided read is one less plaintext key in a process frame, and the
    # model picker polls. A hit must cost no credential access and no upstream request.
    """
    plugin = _FakePlugin()
    auth = _FakeAuth()
    profile = _profile()

    first = await _ask(catalog, plugin, auth, profile)
    second = await _ask(catalog, plugin, auth, profile)

    assert (first.status, second.status) == ("fresh", "fresh")
    assert len(plugin.dials) == 1, "one upstream attempt"
    assert auth.calls == 1, "one decryption"


@pytest.mark.asyncio
async def test_the_provider_receives_the_catalogs_own_supersede_token(catalog) -> None:
    """INVARIANT: ONE source of truth for ``credential_revision``.

    # WHY the catalog overwrites it: the cache is KEYED by this token. If a route or a
    # credential strategy could pass a different value, the token the provider sees
    # would no longer identify the snapshot the cache stores under it.
    """
    plugin = _FakePlugin()
    profile = _profile()

    await _ask(catalog, plugin, _FakeAuth(), profile)

    assert plugin.dials[0].credential_revision == profile_credential_revision(profile, 1)


# ── stale-while-revalidate: the wait is bounded, the work is not ───────────────


@pytest.mark.asyncio
async def test_an_expired_snapshot_serves_stale_immediately_and_refreshes_behind_it(
    catalog,
) -> None:
    """FEATURE: the picker is never empty and never slow.

    # WHY return stale WITHOUT waiting: we already have an answer good enough to show.
    # Spending the user's budget to maybe upgrade it is a worse trade than showing it
    # now and letting the next request see the refreshed list.
    """
    plugin = _FakePlugin()
    auth = _FakeAuth()
    profile = _profile()

    assert (await _ask(catalog, plugin, auth, profile)).status == "fresh"
    catalog.clock.advance(_SOURCE.ttl_s + 1)

    plugin.result = _entries("m-3")
    stale = await _ask(catalog, plugin, auth, profile)

    assert stale.status == "stale"
    assert [entry.model_name for entry in stale.entries or ()] == ["m-1", "m-2"], "last good"

    await catalog.drain()  # the background refresh keeps running after we answered
    assert len(plugin.dials) == 2

    refreshed = await _ask(catalog, plugin, auth, profile)
    assert refreshed.status == "fresh"
    assert [entry.model_name for entry in refreshed.entries or ()] == ["m-3"]


@pytest.mark.asyncio
async def test_a_slow_cold_refresh_answers_refreshing_within_the_budget(catalog) -> None:
    """INVARIANT: the budget bounds the WAIT, never the WORK.

    # WHY this is the whole design: the alternative — wrapping the refresh in
    # ``asyncio.wait_for(..., 3)`` — cancels the winner while it holds the
    # single-flight lock, records no failure, and makes the NEXT caller dial again.
    # One upstream attempt becomes N under exactly the slow-upstream conditions that
    # produced the timeout.
    """
    gate = asyncio.Event()
    plugin = _FakePlugin(gate=gate)
    catalog.wait_budget_s = 0.01

    snap = await _ask(catalog, plugin, _FakeAuth(), _profile())

    assert snap.status == "refreshing"
    assert snap.entries is None
    assert len(plugin.dials) == 1, "the dial started"

    gate.set()
    await catalog.drain()

    later = await _ask(catalog, plugin, _FakeAuth(), _profile())
    assert later.status == "fresh", "the refresh we gave up waiting for still landed"
    assert len(plugin.dials) == 1, "and it was never re-attempted"


@pytest.mark.asyncio
async def test_concurrent_callers_for_one_profile_cause_one_dial(catalog) -> None:
    gate = asyncio.Event()
    plugin = _FakePlugin(gate=gate)
    auth = _FakeAuth()
    profile = _profile()

    waiters = [asyncio.ensure_future(_ask(catalog, plugin, auth, profile)) for _ in range(4)]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*waiters)

    assert {snap.status for snap in results} == {"fresh"}
    assert len(plugin.dials) == 1, "one upstream attempt for four callers"
    assert auth.calls == 1, "and one decryption"


# ── failures degrade honestly and are damped ──────────────────────────────────


@pytest.mark.asyncio
async def test_a_cold_failure_falls_back_with_a_sanitized_reason(catalog) -> None:
    plugin = _FakePlugin(raises=DiscoveryError("bad_status", status=401))
    auth = _FakeAuth()

    snap = await _ask(catalog, plugin, auth, _profile())

    assert (snap.status, snap.reason) == ("fallback", "bad_status")
    assert snap.entries is None


@pytest.mark.asyncio
async def test_a_failure_over_a_last_good_snapshot_serves_stale_with_the_reason(catalog) -> None:
    plugin = _FakePlugin()
    auth = _FakeAuth()
    profile = _profile()

    await _ask(catalog, plugin, auth, profile)
    catalog.clock.advance(_SOURCE.ttl_s + 1)
    plugin.raises = DiscoveryError("timeout")

    stale = await _ask(catalog, plugin, auth, profile)  # serves stale, refresh fails behind
    await catalog.drain()
    again = await _ask(catalog, plugin, auth, profile)

    assert stale.status == "stale"
    assert again.status == "stale"
    assert again.reason == "timeout", "the reason the list is not advancing"
    assert [entry.model_name for entry in again.entries or ()] == ["m-1", "m-2"]


@pytest.mark.asyncio
async def test_a_recent_failure_suppresses_further_dials(catalog) -> None:
    """FEATURE: a revoked key must not cost one upstream 401 per page load."""
    plugin = _FakePlugin(raises=DiscoveryError("bad_status", status=401))
    auth = _FakeAuth()
    profile = _profile()

    await _ask(catalog, plugin, auth, profile)
    await _ask(catalog, plugin, auth, profile)
    await _ask(catalog, plugin, auth, profile)

    assert len(plugin.dials) == 1, "damped inside the failure window"
    assert auth.calls == 1

    catalog.clock.advance(_SOURCE.failure_ttl_s + 1)
    await _ask(catalog, plugin, auth, profile)
    assert len(plugin.dials) == 2, "and retried once the window closed"


@pytest.mark.asyncio
async def test_a_none_listing_under_a_declared_source_is_a_failed_attempt(catalog) -> None:
    """A None here is an inconsistency, not an empty catalog — never cached as success."""
    plugin = _FakePlugin(result=None)

    snap = await _ask(catalog, plugin, _FakeAuth(), _profile())

    assert (snap.status, snap.reason) == ("fallback", "no_snapshot")


@pytest.mark.asyncio
async def test_an_unexpected_provider_error_is_sanitized_not_propagated(catalog) -> None:
    plugin = _FakePlugin(raises=ZeroDivisionError("upstream parser blew up"))

    snap = await _ask(catalog, plugin, _FakeAuth(), _profile())

    assert (snap.status, snap.reason) == ("fallback", "internal_error")


@pytest.mark.asyncio
async def test_an_assertion_error_is_never_absorbed_as_degradation(catalog) -> None:
    """INVARIANT: the suite's no-egress tripwire raises AssertionError.

    # WHY it must reach the caller: absorbing it would turn a forbidden REAL network
    # dial into a quiet "fallback", and a test that actually reached the internet
    # would pass green.
    """
    plugin = _FakePlugin(raises=AssertionError("test attempted real discovery egress"))

    with pytest.raises(AssertionError, match="real discovery egress"):
        await _ask(catalog, plugin, _FakeAuth(), _profile())


# ── isolation: the load-bearing security property ─────────────────────────────


@pytest.mark.asyncio
async def test_two_accounts_with_the_same_profile_name_never_share_a_snapshot(catalog) -> None:
    """INVARIANT: identity includes the ACCOUNT, so B can never read A's catalog."""
    plugin = _FakePlugin()
    profile_a = _profile(account_id="acct-a", name="work")
    profile_b = _profile(account_id="acct-b", name="work")

    plugin.result = _entries("a-only")
    snap_a = await _ask(catalog, plugin, _FakeAuth(), profile_a)
    plugin.result = _entries("b-only")
    snap_b = await _ask(catalog, plugin, _FakeAuth(), profile_b)

    assert [e.model_name for e in snap_a.entries or ()] == ["a-only"]
    assert [e.model_name for e in snap_b.entries or ()] == ["b-only"]
    assert len(plugin.dials) == 2, "no cross-account cache hit"

    again_a = await _ask(catalog, plugin, _FakeAuth(), profile_a)
    assert [e.model_name for e in again_a.entries or ()] == ["a-only"], "A still sees only A's"


@pytest.mark.asyncio
async def test_two_profiles_of_one_account_stay_distinct_with_provenance(catalog) -> None:
    plugin = _FakePlugin()
    work = _profile(name="work")
    personal = _profile(name="personal")

    plugin.result = _entries("work-model")
    snap_work = await _ask(catalog, plugin, _FakeAuth(), work)
    plugin.result = _entries("personal-model")
    snap_personal = await _ask(catalog, plugin, _FakeAuth(), personal)

    assert (snap_work.profile_name, snap_personal.profile_name) == ("work", "personal")
    assert [e.model_name for e in snap_work.entries or ()] == ["work-model"]
    assert [e.model_name for e in snap_personal.entries or ()] == ["personal-model"]


# ── supersede: replacement, invalidation, deletion ────────────────────────────


@pytest.mark.asyncio
async def test_replacing_the_credential_retires_the_previous_snapshot(catalog) -> None:
    """INVARIANT: a snapshot describes ONE credential generation.

    # WHY the revision rides in the cache identity rather than being cleaned up by a
    # hook: even if every invalidation call site were forgotten, a snapshot gathered
    # under the previous key can never be served under the new one.
    """
    plugin = _FakePlugin()
    # STRENGTHENED for F3: the stamp no longer moves. Rotation is expressed only by the
    # durable generation, so this case now also covers a replacement inside one clock tick.
    stamp = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    before = _profile(refreshed_at=stamp)

    first = await _ask(catalog, plugin, _FakeAuth(), before, generation=1)
    plugin.result = _entries("after-rotation")
    after = _profile(refreshed_at=stamp)
    second = await _ask(catalog, plugin, _FakeAuth(), after, generation=2)

    assert profile_credential_revision(before, 1) != profile_credential_revision(after, 2)
    assert [e.model_name for e in first.entries or ()] == ["m-1", "m-2"]
    assert [e.model_name for e in second.entries or ()] == ["after-rotation"]
    assert len(plugin.dials) == 2


@pytest.mark.asyncio
async def test_invalidate_drops_the_snapshot_and_forces_a_fresh_dial(catalog) -> None:
    plugin = _FakePlugin()
    auth = _FakeAuth()
    profile = _profile()

    await _ask(catalog, plugin, auth, profile)
    catalog.invalidate(account_id="acct-a", provider="fake", profile_name="work")
    plugin.result = _entries("re-read")
    snap = await _ask(catalog, plugin, auth, profile)

    assert [e.model_name for e in snap.entries or ()] == ["re-read"]
    assert len(plugin.dials) == 2


@pytest.mark.asyncio
async def test_invalidate_cancels_an_in_flight_refresh_so_it_cannot_publish(catalog) -> None:
    """INVARIANT: a task started by the PREVIOUS owner must never publish a snapshot.

    # WHY both mechanisms: cancelling stops the wasted credentialed request, and the
    # revision in the identity means even a task that slipped past cancellation would
    # store under a key no later caller reads.
    """
    gate = asyncio.Event()
    plugin = _FakePlugin(gate=gate)
    catalog.wait_budget_s = 0.01
    profile = _profile()

    first = await _ask(catalog, plugin, _FakeAuth(), profile)
    assert first.status == "refreshing"

    catalog.invalidate(account_id="acct-a", provider="fake", profile_name="work")
    gate.set()
    await catalog.drain()

    assert catalog.inflight_refreshes == 0
    plugin.result = _entries("new-owner")
    after = await _ask(catalog, plugin, _FakeAuth(), profile)
    assert [e.model_name for e in after.entries or ()] == ["new-owner"]


@pytest.mark.asyncio
async def test_invalidate_touches_only_the_named_identity(catalog) -> None:
    plugin = _FakePlugin()
    other = _profile(account_id="acct-b", name="work")

    await _ask(catalog, plugin, _FakeAuth(), _profile())
    await _ask(catalog, plugin, _FakeAuth(), other)
    catalog.invalidate(account_id="acct-a", provider="fake", profile_name="work")
    await _ask(catalog, plugin, _FakeAuth(), other)

    assert len(plugin.dials) == 2, "the other account's snapshot survived"


# ── boundedness ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_snapshot_store_is_bounded_and_evicts_least_recently_used() -> None:
    """INVARIANT: no unbounded per-profile snapshot map.

    # WHY LRU eviction is safe here (unlike evicting a TASK): the cost of dropping a
    # snapshot is one later re-dial, whereas dropping a task would abandon work a
    # caller is awaiting.
    """
    cat = ProfileModelCatalog(clock=_FakeClock(), max_identities=2, max_inflight_refreshes=4)
    plugin = _FakePlugin()
    try:
        for name in ("p1", "p2", "p3"):
            await _ask(cat, plugin, _FakeAuth(), _profile(name=name))
        assert cat.tracked_identities == 2, "bounded, not grown"

        await _ask(cat, plugin, _FakeAuth(), _profile(name="p1"))
        assert len(plugin.dials) == 4, "the evicted identity re-dialled"
    finally:
        await cat.aclose()


@pytest.mark.asyncio
async def test_at_refresh_capacity_a_new_profile_degrades_instead_of_growing() -> None:
    cat = ProfileModelCatalog(clock=_FakeClock(), max_identities=8, max_inflight_refreshes=1)
    gate = asyncio.Event()
    plugin = _FakePlugin(gate=gate)
    cat.wait_budget_s = 0.01
    try:
        held = await _ask(cat, plugin, _FakeAuth(), _profile(name="holder"))
        assert held.status == "refreshing"

        snap = await _ask(cat, plugin, _FakeAuth(), _profile(name="second"))
        assert (snap.status, snap.reason) == ("fallback", "refresh_deferred")
        assert len(plugin.dials) == 1, "the refused caller started no dial"
    finally:
        gate.set()
        await cat.aclose()


@pytest.mark.asyncio
async def test_shutdown_cancels_unfinished_refreshes() -> None:
    cat = ProfileModelCatalog(clock=_FakeClock(), max_identities=8, max_inflight_refreshes=4)
    gate = asyncio.Event()
    plugin = _FakePlugin(gate=gate)
    cat.wait_budget_s = 0.01

    assert (await _ask(cat, plugin, _FakeAuth(), _profile())).status == "refreshing"
    await cat.aclose()

    assert cat.inflight_refreshes == 0
    assert cat.snapshot_for.__doc__ is not None, (
        "sanity: the catalog object survives shutdown for a clean second aclose"
    )
    await cat.aclose()


# ── the revision token itself ─────────────────────────────────────────────────


def test_the_credential_revision_is_non_secret_and_ownership_derived() -> None:
    """INVARIANT: never derived from the credential.

    # WHY: the cache identity is logged and compared. Deriving it from the key — even
    # by hashing — would make a secret-dependent value flow through cache keys and
    # log lines, which is exactly what the owner brief forbids.
    """
    profile = _profile()

    revision = profile_credential_revision(profile, 3)

    assert "secret" not in revision
    assert revision == profile_credential_revision(_profile(), 3), "stable for one generation"
    assert revision != profile_credential_revision(_profile(auth_type="oauth"), 3), "auth switch"
    assert revision != profile_credential_revision(profile, 4), "key rotation"
    # STRENGTHENED for F3: the clock is no longer an input at all, so a profile whose
    # stamp moved on its own cannot masquerade as a new credential generation.
    moved_stamp = _profile(refreshed_at=datetime(2026, 8, 28, 12, 0, 1, tzinfo=UTC))
    assert revision == profile_credential_revision(moved_stamp, 3), "clock is not identity"


def test_a_profile_that_never_refreshed_still_has_a_revision() -> None:
    profile = _profile(refreshed_at=None)
    profile.last_refreshed_at = None

    assert profile_credential_revision(profile, 0)


@pytest.mark.asyncio
async def test_a_superseded_refresh_reports_itself_rather_than_a_bogus_failure(catalog) -> None:
    """A cancelled refresh is neither a snapshot nor an outage — say so honestly."""
    gate = asyncio.Event()
    plugin = _FakePlugin(gate=gate)
    profile = _profile()

    asking = asyncio.ensure_future(_ask(catalog, plugin, _FakeAuth(), profile))
    await asyncio.sleep(0)
    catalog.invalidate(account_id="acct-a", provider="fake", profile_name="work")

    snap = await asking

    assert (snap.status, snap.reason) == ("fallback", "refresh_superseded")
    gate.set()
