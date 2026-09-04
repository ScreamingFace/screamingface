"""OME-1026 remediation F6 — where an unexpected background failure must surface.

FEATURE: honest failure boundaries. A discovery outage degrades to seeds; a
programming error does not get to hide behind that same answer.

STORY: as an engineer, a bug in background discovery either fails my request or
fails my test run — it never disappears into a log line.

INVARIANT (two separate requirements, deliberately not conflated):
  * HTTP isolation — publishing a credential must NOT return 5xx because a
    background refresh happened to fail quickly. The credential is already durably
    stored; the listing is a convenience.
  * Observability — that same failure must still be retained so a test (or an
    operator) sees it. Silence is the outcome this file forbids.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import pytest_asyncio
from fastapi import FastAPI

from aigateway.core.background_error_sink import (
    assert_no_unexpected,
    take_unexpected,
)
from aigateway.core.background_refresh import (
    BackgroundRefreshManager,
)
from aigateway.core.model_discovery_scope import DiscoveryScope, ProviderAuthContext
from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry
from aigateway.core.profile_model_catalog import ProfileModelCatalog
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from tests.conftest import drain_private_catalog

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


@dataclass
class _FakePlugin:
    custom_llm_provider: str = "fake"
    raises: BaseException | None = None
    gate: asyncio.Event | None = None
    result: tuple[ModelEntry, ...] | None = None
    dials: int = field(default=0)

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
        if self.gate is not None:
            await self.gate.wait()
        if self.raises is not None:
            raise self.raises
        return self.result


async def _auth() -> ProviderAuthContext:
    return ProviderAuthContext(headers={"x-api-key": "value"}, auth_type="api_key")


def _profile() -> Profile:
    return Profile(
        id=profile_id_for("acct-a", "fake", "work"),
        account_id="acct-a",
        provider="fake",
        name="work",
        state=ProfileState.AUTHENTICATED,
        auth_type="api_key",
        last_refreshed_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )


@pytest_asyncio.fixture
async def catalog():
    cat = ProfileModelCatalog(max_identities=8, max_inflight_refreshes=4)
    take_unexpected()
    try:
        yield cat
    finally:
        await cat.aclose()
        take_unexpected()


async def _ask(catalog: ProfileModelCatalog, plugin: Any, *, budget: float | None):
    return await catalog.snapshot_for(
        plugin,
        account_id="acct-a",
        profile=_profile(),
        client=_NoClient(),
        limits=None,
        auth_provider=_auth,
        credential_generation=1,
        wait_budget_s=budget,
    )


# ── a zero budget STARTS work; it never observes the outcome ───────────────────


@pytest.mark.asyncio
async def test_a_zero_budget_never_raises_an_immediate_programming_error(catalog) -> None:
    """The post-commit publication path. A 5xx here would be a lie about the write.

    # WHY this was timing-dependent before: with a budget of zero the wait still gave
    # the task its first step, so a refresh that raised IMMEDIATELY was observed and
    # re-raised, while the same bug one loop pass later was not. The credential is
    # already committed at this point, so neither outcome may reach the client.
    """
    plugin = _FakePlugin(raises=AssertionError("test attempted real discovery egress"))

    snapshot = await _ask(catalog, plugin, budget=0.0)

    assert snapshot.status == "refreshing", snapshot
    assert snapshot.reason is None
    await catalog.drain()
    # ...but the bug is NOT lost: it is retained for the observation point.
    retained = take_unexpected()
    assert len(retained) == 1 and retained[0].type_name == "AssertionError", retained


@pytest.mark.asyncio
async def test_a_zero_budget_answers_identically_when_the_failure_is_delayed(catalog) -> None:
    """Determinism: the same bug must produce the same answer whenever it lands."""
    gate = asyncio.Event()
    plugin = _FakePlugin(raises=AssertionError("boom later"), gate=gate)

    snapshot = await _ask(catalog, plugin, budget=0.0)

    assert snapshot.status == "refreshing", snapshot
    gate.set()
    await catalog.drain()
    assert len(take_unexpected()) == 1


@pytest.mark.asyncio
async def test_an_awaited_budget_still_raises_a_programming_error(catalog) -> None:
    """The other side of the boundary: a caller who WAITED must not get seeds."""
    plugin = _FakePlugin(raises=AssertionError("caller waited for this"))

    with pytest.raises(AssertionError, match="caller waited"):
        await _ask(catalog, plugin, budget=5.0)

    # Already surfaced to the caller, so it must not ALSO be retained.
    assert take_unexpected() == ()


@pytest.mark.asyncio
async def test_a_discovery_failure_under_a_zero_budget_is_not_a_bug(catalog) -> None:
    plugin = _FakePlugin(raises=DiscoveryError("bad_status", status=401))

    snapshot = await _ask(catalog, plugin, budget=0.0)

    assert snapshot.status == "refreshing"
    await catalog.drain()
    assert take_unexpected() == ()


# ── the observation point itself ──────────────────────────────────────────────


def test_the_observation_point_fails_when_background_work_left_a_bug() -> None:
    """What test teardown calls. Without this, retention would be a log nobody reads."""
    take_unexpected()

    from aigateway.core.background_error_sink import _log_unexpected

    _log_unexpected("some-key", AssertionError("test attempted real discovery egress"))

    with pytest.raises(AssertionError, match="unexpected background"):
        assert_no_unexpected("unit under test")

    assert take_unexpected() == (), "the failing check must drain, not accumulate"


def test_the_observation_point_is_silent_when_nothing_went_wrong() -> None:
    take_unexpected()

    assert_no_unexpected("nothing to report")


# ── the public prewarm boundary ────────────────────────────────────────────────


# AIDEV-NOTE: ``start_public_prewarm`` is app-layer wiring and is annotated for the
# real ``FastAPI``; this stub deliberately duck-types only the ``state`` attributes it
# reads, so its call sites cast. Widening the production signature to ``Any`` to suit a
# test would give up the type that documents where this function belongs.
class _PrewarmApp:
    """The narrow slice of ``app.state`` that the prewarm starter touches."""

    class _State:
        model_catalog: Any
        discovery_runtime: Any
        providers: Any
        public_refreshes: Any

    def __init__(self, catalog: Any, providers: Any, refreshes: Any) -> None:
        self.state = self._State()
        self.state.model_catalog = catalog
        self.state.discovery_runtime = type("_R", (), {"client": None, "limits": None})()
        self.state.providers = providers
        self.state.public_refreshes = refreshes


class _Providers:
    def __init__(self, *plugins: Any) -> None:
        self._plugins = plugins

    def all(self):
        return self._plugins


class _PublicPlugin:
    """A PUBLIC provider with a declared source, so prewarm has work to start."""

    def __init__(self, name: str) -> None:
        self.custom_llm_provider = name

    def model_discovery_scope(self) -> DiscoveryScope:
        return DiscoveryScope.PUBLIC_GLOBAL

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return _SOURCE


@pytest.mark.asyncio
async def test_prewarm_does_not_swallow_a_programming_error() -> None:
    """INVARIANT: prewarm must not launder an ``AssertionError`` into a log line.

    # WHY it mattered: prewarm used to ``asyncio.gather(..., return_exceptions=True)``
    # and count the successes, so its own outer coroutine completed successfully and the
    # manager wrapping it never saw the failure — a test that reached the real internet
    # during startup prewarm produced one log line and a green run.
    # WHY the assertion is on RETENTION and not on a raise: prewarm now only STARTS the
    # refreshes (so startup cannot wait on an upstream), which means there is no awaiting
    # caller to raise to. The manager's retention sink is the observation point instead,
    # and it is strictly louder: it survives until test teardown asserts on it.
    """
    from aigateway.discovery_lifecycle import start_public_prewarm

    class _BuggyCatalog:
        def start_public_refresh(self, plugin: Any, *, client: Any, limits: Any, refreshes: Any):
            async def _boom() -> None:
                raise AssertionError("test attempted real discovery egress to https://x.invalid")

            return refreshes.start_or_join(("k", plugin.custom_llm_provider), _boom)

    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    app = _PrewarmApp(_BuggyCatalog(), _Providers(_PublicPlugin("a")), refreshes)
    try:
        started = start_public_prewarm(cast(FastAPI, app))
        assert started == 1, "prewarm must have started the refresh"
        await refreshes.drain()

        # Matched on the SANITIZED report (adversarial B3): the sink keeps the bug class
        # and the identity, never the exception text.
        with pytest.raises(AssertionError, match="AssertionError"):
            assert_no_unexpected("startup prewarm")
    finally:
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_prewarm_still_tolerates_an_ordinary_discovery_failure() -> None:
    """A cold upstream is not a bug: prewarm's whole job is to absorb that."""
    from aigateway.discovery_lifecycle import start_public_prewarm

    class _DegradedCatalog:
        def start_public_refresh(self, plugin: Any, *, client: Any, limits: Any, refreshes: Any):
            async def _degraded() -> None:
                raise DiscoveryError("unreachable")

            return refreshes.start_or_join(("k", plugin.custom_llm_provider), _degraded)

    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    app = _PrewarmApp(
        _DegradedCatalog(), _Providers(_PublicPlugin("a"), _PublicPlugin("b")), refreshes
    )
    try:
        assert start_public_prewarm(cast(FastAPI, app)) == 2
        await refreshes.drain()

        assert_no_unexpected("startup prewarm")  # must stay silent
    finally:
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_prewarm_never_waits_for_the_refreshes_it_starts() -> None:
    """INVARIANT (F2): startup must not block on an upstream catalog.

    A gated refresh proves it: the starter returns while the work is still parked, and
    the task it left behind is exactly the one a request would join.
    """
    from aigateway.discovery_lifecycle import start_public_prewarm

    gate = asyncio.Event()

    class _GatedCatalog:
        def start_public_refresh(self, plugin: Any, *, client: Any, limits: Any, refreshes: Any):
            async def _parked() -> None:
                await gate.wait()

            return refreshes.start_or_join(("k", plugin.custom_llm_provider), _parked)

    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    app = _PrewarmApp(_GatedCatalog(), _Providers(_PublicPlugin("a")), refreshes)
    try:
        assert start_public_prewarm(cast(FastAPI, app)) == 1

        # Returned WITHOUT the refresh finishing — the whole point of prewarm.
        assert refreshes.inflight == 1
        assert refreshes.tracked_keys() == (("k", "a"),)
    finally:
        gate.set()
        await refreshes.drain()
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_prewarm_starts_nothing_under_the_discovery_kill_switch() -> None:
    """``AIGW_DISCOVERY_ENABLED=false`` leaves the catalog ``None`` — zero egress."""
    from aigateway.discovery_lifecycle import start_public_prewarm

    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    app = _PrewarmApp(None, _Providers(_PublicPlugin("a")), refreshes)
    try:
        assert start_public_prewarm(cast(FastAPI, app)) == 0
        assert refreshes.inflight == 0
    finally:
        await refreshes.aclose()


# ── the post-commit credential-publication path, end to end ───────────────────


def test_publishing_a_credential_never_5xxs_but_the_tripwire_is_still_reported(
    authenticated_client: Any, monkeypatch: Any
) -> None:
    """Both halves of F6 on the one path that has to satisfy both.

    The api-key route commits the credential and then starts this profile's private
    discovery with a zero budget. The app's default wiring is the real discovery
    client with NO transport, so that refresh trips the suite's no-egress tripwire in
    the background — the exact schedule the finding describes.

    INVARIANT (HTTP isolation): the write already committed, so the response is 200.
    INVARIANT (observability): the tripwire is nonetheless RETAINED, so this explicit
    hook fails. Before the fix it was logged and forgotten, and this test could not
    have been written at all.
    """
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService
    from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
    from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )
    take_unexpected()

    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/post-commit/api-key",
        json={"api_key": "sk-ant-post-commit-observability"},
    )

    assert stored.status_code == 200, stored.text

    # A real barrier, not a sleep: drain the private catalog INSIDE the app's own loop
    # through the TestClient's blocking portal, so the background refresh has finished
    # before the sink is inspected.
    drain_private_catalog(authenticated_client)

    # Matched on the SANITIZED report (adversarial B3): the sink keeps the bug class
    # and the identity, never the exception text.
    with pytest.raises(AssertionError, match="AssertionError"):
        assert_no_unexpected("post-commit private discovery")
