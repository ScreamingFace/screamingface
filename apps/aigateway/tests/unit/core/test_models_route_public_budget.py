"""OME-1026 remediation F2 — the global listing's user-facing budget.

FEATURE: a bounded ``GET /v1/models``. The published listing is a convenience view
over provider catalogs; no caller may be held for an upstream provider's own
refresh deadline to receive it.

STORY: as an API consumer I get the model list promptly on a cold gateway — seeds
if that is all the gateway has yet — and my next call shows the live catalog.

INVARIANT (why the wait and the work must be separate objects): the public refresh
runs inside ``ObservationCache.get_or_refresh``, which awaits its refresh callable
while HOLDING the single-flight lock. Bounding that with ``asyncio.wait_for`` would
CANCEL the winner mid-flight, record no failure, release the lock, and turn one
upstream attempt into N — exactly the failure the background task manager exists to
prevent. So the route waits on a task it does not own, and lets it run on.

INVARIANT (concurrency and order are both preserved): providers still refresh
concurrently, and the listing's row order still follows ``registry.all()`` — it is
positional, never "whoever answered first".
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.background_error_sink import take_unexpected
from aigateway.core.background_refresh import BackgroundRefreshManager
from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.model_discovery_scope import DiscoveryScope
from aigateway.core.parameter_discovery import DiscoveryError, DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry
from aigateway.plugins.openrouter_provider import plugin as plugin_module
from aigateway.plugins.openrouter_provider.live_models import LIVE_MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from aigateway.routes.models import _live_listings

_SOURCE = ModelDiscoverySource(
    key="fake:models:list",
    revision="fake-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _Runtime:
    """The two things the listing route reads off the discovery runtime."""

    def __init__(self, *, budget_s: float) -> None:
        self.client = object()
        self.limits = DiscoveryLimits(timeout_s=budget_s)


def _entries(*names: str) -> tuple[ModelEntry, ...]:
    return tuple(
        ModelEntry(model_name=name, litellm_params={"model": f"fake/{name}"}) for name in names
    )


@dataclass
class _GatedProvider:
    """A PUBLIC provider whose refresh finishes only when its gate is opened.

    # WHY a gate rather than a sleep: the budget is proven by a refresh that has NOT
    # finished, and an event makes that a fact of the schedule instead of a race
    # against a wall clock. ``entered`` lets a test wait for the dial to really start.
    """

    custom_llm_provider: str = "slow"
    result: tuple[ModelEntry, ...] = field(default_factory=lambda: _entries("live-model"))
    raises: BaseException | None = None
    gate: asyncio.Event = field(default_factory=asyncio.Event)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    dials: int = 0

    def model_discovery_scope(self) -> DiscoveryScope:
        return DiscoveryScope.PUBLIC_GLOBAL

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return _SOURCE

    async def discover_live_models(
        self, *, client: Any, limits: Any = None
    ) -> tuple[ModelEntry, ...] | None:
        self.dials += 1
        self.entered.set()
        await self.gate.wait()
        if self.raises is not None:
            raise self.raises
        return self.result


@dataclass
class _FastProvider:
    custom_llm_provider: str = "fast"
    result: tuple[ModelEntry, ...] = field(default_factory=lambda: _entries("fast-model"))
    dials: int = 0

    def model_discovery_scope(self) -> DiscoveryScope:
        return DiscoveryScope.PUBLIC_GLOBAL

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return ModelDiscoverySource(
            key="fast:models:list",
            revision="fast-v1",
            ttl_s=300.0,
            stale_ttl_s=3600.0,
            failure_ttl_s=30.0,
        )

    async def discover_live_models(
        self, *, client: Any, limits: Any = None
    ) -> tuple[ModelEntry, ...] | None:
        self.dials += 1
        return self.result


@pytest.fixture(autouse=True)
def _drain_sink():
    take_unexpected()
    yield
    take_unexpected()


async def _ask(
    plugins: list[Any],
    *,
    catalog: ModelCatalog,
    refreshes: BackgroundRefreshManager,
    budget_s: float,
) -> list[tuple[ModelEntry, ...] | None]:
    return await _live_listings(
        plugins,
        catalog=catalog,
        runtime=_Runtime(budget_s=budget_s),
        refreshes=refreshes,
    )


# ── the reported schedule: a slow public provider must not hold the listing ─────


@pytest.mark.asyncio
async def test_a_slow_public_provider_yields_seeds_within_the_budget() -> None:
    """The exact reported case, minus the wall clock.

    OpenRouter keeps a 10-second AGGREGATE refresh deadline of its own. A caller
    that joined that refresh used to wait it out; now the caller waits only its own
    budget and the refresh keeps going.
    """
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    slow = _GatedProvider()
    try:
        listings = await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=0.01)

        # None == "fall back to this provider's compiled seeds" — the baseline answer.
        assert listings == [None], listings
        assert slow.dials == 1, "the refresh must have STARTED, not been skipped"
        # INVARIANT: the wait expiring must not cancel the work. A cancelled winner
        # would leave no failure recorded and the next arrival would dial again.
        # ``inflight`` counts only NOT-done tasks, and a cancelled task becomes done,
        # so a non-zero gauge here is the assertion that the refresh survived.
        assert refreshes.inflight == 1, "the shared refresh must still be alive"
        assert refreshes.tracked_keys() != (), "and it must still be joinable by key"
    finally:
        slow.gate.set()
        await refreshes.drain()
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_a_later_request_sees_the_completed_public_snapshot() -> None:
    """The other half of stale-while-revalidate: the refresh has to pay off."""
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    slow = _GatedProvider()
    try:
        first = await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=0.01)
        assert first == [None]

        slow.gate.set()
        await refreshes.drain()
        second = await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=5.0)

        assert second == [slow.result], second
        # INVARIANT: ONE upstream attempt across both requests. The second request
        # joined nothing and dialed nothing — it read the snapshot the first paid for.
        assert slow.dials == 1, f"the snapshot was re-fetched: {slow.dials} dials"
    finally:
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_a_second_caller_joins_the_live_refresh_instead_of_dialing() -> None:
    """Single-flight survives the budget: joining is what keeps one attempt at one."""
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    slow = _GatedProvider()
    try:
        assert await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=0.01) == [None]
        assert await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=0.01) == [None]

        assert slow.dials == 1, "the second caller started a competing dial"
        assert refreshes.inflight == 1
    finally:
        slow.gate.set()
        await refreshes.drain()
        await refreshes.aclose()


# ── concurrency and order, which the budget must not cost ──────────────────────


@pytest.mark.asyncio
async def test_a_slow_provider_does_not_delay_or_reorder_a_fast_one() -> None:
    """One slow catalog degrades ITS row set only, and the order stays positional."""
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    slow = _GatedProvider()
    fast = _FastProvider()
    try:
        # Registry order deliberately puts the slow provider FIRST: a route that
        # returned results in completion order would swap these two.
        listings = await _ask([slow, fast], catalog=catalog, refreshes=refreshes, budget_s=0.01)

        assert listings == [None, fast.result], listings
        assert slow.dials == 1 and fast.dials == 1, "both providers must refresh"
        # INVARIANT: concurrent, not sequential — the fast provider answered while the
        # slow one was still inside its own refresh.
        assert refreshes.inflight == 1
    finally:
        slow.gate.set()
        await refreshes.drain()
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_a_failing_slow_provider_is_still_only_a_seed_fallback() -> None:
    """A refresh that fails AFTER the budget expired is an ordinary degraded outcome."""
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    slow = _GatedProvider(raises=DiscoveryError("unreachable"))
    try:
        assert await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=0.01) == [None]
        slow.gate.set()
        await refreshes.drain()

        assert take_unexpected() == (), "a DiscoveryError is not a bug report"
    finally:
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_a_programming_error_inside_the_budget_still_propagates() -> None:
    """INVARIANT: the no-egress tripwire stays loud for a caller who WAITED."""
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    slow = _GatedProvider(raises=AssertionError("test attempted real discovery egress"))
    slow.gate.set()  # fails immediately, inside the caller's budget
    try:
        with pytest.raises(AssertionError, match="real discovery egress"):
            await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=5.0)

        # Already surfaced to the caller, so it must not ALSO be retained.
        assert take_unexpected() == ()
    finally:
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_a_programming_error_after_the_budget_is_retained_not_lost() -> None:
    """The same bug landing late: nobody is left to raise to, so the sink holds it."""
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=4)
    slow = _GatedProvider(raises=AssertionError("test attempted real discovery egress"))
    try:
        assert await _ask([slow], catalog=catalog, refreshes=refreshes, budget_s=0.01) == [None]
        slow.gate.set()
        await refreshes.drain()

        retained = take_unexpected()
        assert len(retained) == 1 and retained[0].type_name == "AssertionError", retained
    finally:
        await refreshes.aclose()


@pytest.mark.asyncio
async def test_capacity_refusal_is_a_seed_fallback_not_an_error() -> None:
    """At capacity the honest answer is seeds — the documented degraded outcome."""
    catalog = ModelCatalog(clock=_Clock())
    refreshes = BackgroundRefreshManager[Any](max_inflight=1)
    first = _GatedProvider(custom_llm_provider="slow-a")
    second = _GatedProvider(custom_llm_provider="slow-b")
    try:
        listings = await _ask([first, second], catalog=catalog, refreshes=refreshes, budget_s=0.01)

        assert listings == [None, None]
        assert first.dials == 1 and second.dials == 0, "capacity must refuse, not queue"
    finally:
        first.gate.set()
        second.gate.set()
        await refreshes.drain()
        await refreshes.aclose()


# ── end to end through the real route and a real provider ─────────────────────


class _SlowCatalogClient:
    """A canned OpenRouter catalog that answers slower than the route's budget."""

    def __init__(self, ids: list[str], *, delay_s: float) -> None:
        self._body = json.dumps(
            {"data": [{"id": i} for i in ids], "links": {"next": None}, "total_count": len(ids)}
        )
        self._delay_s = delay_s
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        await asyncio.sleep(self._delay_s)
        return RawResponse(status=200, content_type="application/json", body=self._body)


def test_the_route_answers_seeds_fast_then_the_live_catalog(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole stack: a cold listing against a slow upstream, then the payoff.

    # WHY a sleep here and a gate above: this case has to cross the TestClient's
    # thread boundary, where the request's loop is not the test's. The delay is 20x
    # the route budget, so the ordering it asserts is not a close call.
    """
    settings = OpenRouterPluginSettings(enabled=True)
    monkeypatch.setattr(plugin_module.PLUGIN, "settings", settings)
    http = _SlowCatalogClient(["openai/gpt-5"], delay_s=0.2)
    app = cast(FastAPI, authenticated_client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        # The user-facing budget: the route reads it off the SAME limits object the
        # discovery client uses, so there is one operator knob, not two.
        limits=DiscoveryLimits(timeout_s=0.01),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())

    cold = authenticated_client.get("/v1/models")

    assert cold.status_code == 200
    cold_ids = [row["id"] for row in cold.json()["data"] if row["owned_by"] == "openrouter"]
    # INVARIANT: the compiled seed listing, byte-identical to static behavior — the
    # route did NOT wait out the provider's own refresh.
    assert cold_ids == list(settings.default_models)
    assert http.dialed == [LIVE_MODELS_URL], "the refresh must have started anyway"

    # Let the background refresh finish in the app's own loop.
    time.sleep(0.5)
    warm = authenticated_client.get("/v1/models")

    warm_ids = [row["id"] for row in warm.json()["data"] if row["owned_by"] == "openrouter"]
    assert warm_ids == ["openrouter/openai/gpt-5"], warm_ids
    # INVARIANT: one upstream fetch chain served both requests.
    assert http.dialed == [LIVE_MODELS_URL]
