"""OME-972 U4 — the app-lifetime, process-local live model catalog.

INVARIANT: the catalog never fabricates a listing. Healthy refreshes are cached
fresh for one TTL; a failed refresh serves the last-good snapshot within the
stale window and degrades to ``None`` (seed fallback) beyond it; a port that
answers ``None`` under a declared source is an inconsistency treated as a
FAILED attempt — never cached fresh, never evicting last-good state.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

import pytest

from aigateway.core.model_catalog import ModelCatalog, build_model_catalog
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    RawResponse,
)
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry

_SOURCE = ModelDiscoverySource(
    key="stub:models:list",
    revision="stub:models:list-v1",
    ttl_s=60.0,
    stale_ttl_s=120.0,
    failure_ttl_s=30.0,
)

_ENTRIES = (ModelEntry(model_name="stubprov/a/x", litellm_params={"model": "stubprov/a/x"}),)
_ENTRIES_2 = (ModelEntry(model_name="stubprov/b/y", litellm_params={"model": "stubprov/b/y"}),)


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value


class _StubPlugin:
    """Duck-typed provider double: scripted port outcomes, call counting."""

    def __init__(
        self,
        *,
        provider: str = "stubprov",
        source: ModelDiscoverySource | None = _SOURCE,
        outcomes: list[object] | None = None,
    ) -> None:
        self.custom_llm_provider = provider
        self._source = source
        self._outcomes = list(outcomes or [])
        self.calls = 0

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return self._source

    async def discover_live_models(
        self, *, client: DiscoveryHttpClient, limits: DiscoveryLimits | None = None
    ) -> tuple[ModelEntry, ...] | None:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return cast("tuple[ModelEntry, ...] | None", outcome)


class _NullClient:
    """Protocol-shaped sentinel: the catalog forwards it opaquely to the port."""

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        raise AssertionError("stub port outcomes never dial the client")


_CLIENT = _NullClient()


async def _entries(catalog: ModelCatalog, plugin: _StubPlugin) -> tuple[ModelEntry, ...] | None:
    return await catalog.entries_for(plugin, client=_CLIENT, limits=None)


# ------------------------------------------------------------------ gating


@pytest.mark.asyncio
async def test_no_declared_source_returns_none_without_calling_the_port() -> None:
    plugin = _StubPlugin(source=None, outcomes=[_ENTRIES])
    catalog = ModelCatalog(clock=_Clock())
    assert await _entries(catalog, plugin) is None
    assert plugin.calls == 0


def test_build_model_catalog_follows_the_discovery_switch() -> None:
    # WHY: AIGW_DISCOVERY_ENABLED=false is the deployment-wide kill switch for
    # ALL discovery egress — the listing catalog obeys the same switch the
    # parameter-discovery runtime does.
    assert build_model_catalog(enabled=False) is None
    assert isinstance(build_model_catalog(enabled=True), ModelCatalog)


# ------------------------------------------------------------------ caching


@pytest.mark.asyncio
async def test_healthy_snapshot_is_cached_for_one_ttl() -> None:
    plugin = _StubPlugin(outcomes=[_ENTRIES, _ENTRIES_2])
    catalog = ModelCatalog(clock=_Clock())
    assert await _entries(catalog, plugin) == _ENTRIES
    assert await _entries(catalog, plugin) == _ENTRIES
    assert plugin.calls == 1


@pytest.mark.asyncio
async def test_ttl_expiry_triggers_one_refresh() -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[_ENTRIES, _ENTRIES_2])
    catalog = ModelCatalog(clock=clock)
    assert await _entries(catalog, plugin) == _ENTRIES
    clock.value += _SOURCE.ttl_s + 1.0
    assert await _entries(catalog, plugin) == _ENTRIES_2
    assert plugin.calls == 2


@pytest.mark.asyncio
async def test_failed_refresh_serves_the_stale_last_good_snapshot() -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[_ENTRIES, DiscoveryError("bad_status", status=500)])
    catalog = ModelCatalog(clock=clock)
    assert await _entries(catalog, plugin) == _ENTRIES
    clock.value += _SOURCE.ttl_s + 1.0
    # INVARIANT: an upstream outage never evicts the last good listing.
    assert await _entries(catalog, plugin) == _ENTRIES


@pytest.mark.asyncio
async def test_cold_failure_returns_none_for_seed_fallback() -> None:
    plugin = _StubPlugin(outcomes=[DiscoveryError("unreachable")])
    catalog = ModelCatalog(clock=_Clock())
    assert await _entries(catalog, plugin) is None


@pytest.mark.asyncio
async def test_stale_window_expiry_degrades_to_none() -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[_ENTRIES, DiscoveryError("timeout"), DiscoveryError("timeout")])
    catalog = ModelCatalog(clock=clock)
    assert await _entries(catalog, plugin) == _ENTRIES
    clock.value += _SOURCE.ttl_s + _SOURCE.stale_ttl_s + 1.0
    # WHY: beyond ttl+stale the snapshot is too old to trust — honest absence
    # (seed fallback) beats a listing that may be hours wrong.
    assert await _entries(catalog, plugin) is None


@pytest.mark.asyncio
async def test_failure_damping_suppresses_immediate_retries() -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[DiscoveryError("unreachable"), _ENTRIES])
    catalog = ModelCatalog(clock=clock)
    assert await _entries(catalog, plugin) is None
    clock.value += _SOURCE.failure_ttl_s / 2
    # INVARIANT: within failure_ttl the failed attempt is NOT retried — a dead
    # upstream costs one dial per damping window, not one per request.
    assert await _entries(catalog, plugin) is None
    assert plugin.calls == 1
    clock.value += _SOURCE.failure_ttl_s
    assert await _entries(catalog, plugin) == _ENTRIES
    assert plugin.calls == 2


# ------------------------------------------------------- port contract guards


@pytest.mark.asyncio
async def test_port_none_under_a_declared_source_is_a_failed_attempt() -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[_ENTRIES, None])
    catalog = ModelCatalog(clock=clock)
    assert await _entries(catalog, plugin) == _ENTRIES
    clock.value += _SOURCE.ttl_s + 1.0
    # INVARIANT: an inconsistent None is converted to a failed refresh — were it
    # stored as a successful value it would be cached FRESH and evict last-good.
    assert await _entries(catalog, plugin) == _ENTRIES


@pytest.mark.asyncio
async def test_cold_port_none_returns_none() -> None:
    plugin = _StubPlugin(outcomes=[None])
    catalog = ModelCatalog(clock=_Clock())
    assert await _entries(catalog, plugin) is None


@pytest.mark.asyncio
async def test_foreign_exception_is_wrapped_and_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plugin = _StubPlugin(outcomes=[ValueError("secret-token-xyz")])
    catalog = ModelCatalog(clock=_Clock())
    with caplog.at_level(logging.WARNING, logger="aigateway.core.model_catalog"):
        assert await _entries(catalog, plugin) is None
    text = caplog.text
    # INVARIANT (sanitized): the exception TYPE is observable, its message —
    # which can carry upstream content — never reaches a log line.
    assert "ValueError" in text
    assert "secret-token-xyz" not in text


@pytest.mark.asyncio
async def test_assertion_error_propagates_loudly() -> None:
    # INVARIANT: the test-suite no-egress tripwire raises AssertionError — the
    # catalog must NEVER absorb it into a quiet degraded outcome.
    plugin = _StubPlugin(outcomes=[AssertionError("test attempted real discovery egress")])
    catalog = ModelCatalog(clock=_Clock())
    with pytest.raises(AssertionError):
        await _entries(catalog, plugin)


# ------------------------------------------------------------- concurrency


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_refresh() -> None:
    class _SlowPlugin(_StubPlugin):
        async def discover_live_models(
            self, *, client: DiscoveryHttpClient, limits: DiscoveryLimits | None = None
        ) -> tuple[ModelEntry, ...] | None:
            self.calls += 1
            await asyncio.sleep(0.02)
            return _ENTRIES

    plugin = _SlowPlugin()
    catalog = ModelCatalog(clock=_Clock())
    results = await asyncio.gather(*(_entries(catalog, plugin) for _ in range(5)))
    assert all(result == _ENTRIES for result in results)
    assert plugin.calls == 1


@pytest.mark.asyncio
async def test_providers_are_cached_independently() -> None:
    source_b = ModelDiscoverySource(
        key="otherprov:models:list",
        revision="otherprov:models:list-v1",
        ttl_s=60.0,
        stale_ttl_s=120.0,
        failure_ttl_s=30.0,
    )
    plugin_a = _StubPlugin(outcomes=[_ENTRIES])
    plugin_b = _StubPlugin(provider="otherprov", source=source_b, outcomes=[_ENTRIES_2])
    catalog = ModelCatalog(clock=_Clock())
    assert await _entries(catalog, plugin_a) == _ENTRIES
    assert await _entries(catalog, plugin_b) == _ENTRIES_2
    assert plugin_a.calls == 1
    assert plugin_b.calls == 1


# ------------------------------------------------------------------- logging


@pytest.mark.asyncio
async def test_successful_refresh_logs_the_row_count_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plugin = _StubPlugin(outcomes=[_ENTRIES])
    catalog = ModelCatalog(clock=_Clock())
    with caplog.at_level(logging.INFO, logger="aigateway.core.model_catalog"):
        await _entries(catalog, plugin)
    assert "stubprov" in caplog.text
    assert "models=1" in caplog.text
    # INVARIANT: counts, never content — no model id appears in log output.
    assert "stubprov/a/x" not in caplog.text


@pytest.mark.asyncio
async def test_failed_refresh_logs_reason_and_status_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plugin = _StubPlugin(outcomes=[DiscoveryError("bad_status", status=401)])
    catalog = ModelCatalog(clock=_Clock())
    with caplog.at_level(logging.WARNING, logger="aigateway.core.model_catalog"):
        await _entries(catalog, plugin)
    assert "bad_status" in caplog.text
    assert "401" in caplog.text


@pytest.mark.asyncio
async def test_damped_window_produces_no_new_log_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[DiscoveryError("unreachable")])
    catalog = ModelCatalog(clock=clock)
    with caplog.at_level(logging.INFO, logger="aigateway.core.model_catalog"):
        await _entries(catalog, plugin)
        first_batch = len(caplog.records)
        clock.value += _SOURCE.failure_ttl_s / 2
        await _entries(catalog, plugin)
    # WHY: the damped path never re-runs the refresh thunk, so a dead upstream
    # cannot flood the log — at most one line per damping window.
    assert len(caplog.records) == first_batch


# --------------------------------------------------------------------- ids_for


@pytest.mark.asyncio
async def test_ids_for_projects_model_names() -> None:
    plugin = _StubPlugin(outcomes=[_ENTRIES])
    catalog = ModelCatalog(clock=_Clock())
    assert await catalog.ids_for(plugin, client=_CLIENT, limits=None) == frozenset({"stubprov/a/x"})


@pytest.mark.asyncio
async def test_ids_for_is_empty_when_no_source_or_degraded() -> None:
    catalog = ModelCatalog(clock=_Clock())
    no_source = _StubPlugin(source=None)
    assert await catalog.ids_for(no_source, client=_CLIENT, limits=None) == frozenset()
    failing = _StubPlugin(provider="coldprov", outcomes=[DiscoveryError("unreachable")])
    # WHY reusing a fresh key: per-provider caches — a cold failure yields no ids.
    source = ModelDiscoverySource(
        key="coldprov:models:list", revision="v1", ttl_s=60.0, stale_ttl_s=120.0, failure_ttl_s=0.0
    )
    failing._source = source
    assert await catalog.ids_for(failing, client=_CLIENT, limits=None) == frozenset()


# --- OME-972 correction pass ------------------------------------------------


@pytest.mark.asyncio
async def test_ids_for_canonicalizes_unprefixed_entries() -> None:
    # INVARIANT: the rescue set and the published listing must live in ONE
    # identity space. /v1/models publishes canonical (provider-prefixed) ids, so
    # a provider following the established unprefixed-``model_name`` convention
    # would otherwise publish an id that 404s on its own detail endpoint.
    bare = (ModelEntry(model_name="a/x", litellm_params={"model": "a/x"}),)
    plugin = _StubPlugin(outcomes=[bare])
    catalog = ModelCatalog(clock=_Clock())
    assert await catalog.ids_for(plugin, client=_CLIENT, limits=None) == frozenset({"stubprov/a/x"})


@pytest.mark.asyncio
async def test_already_canonical_entries_are_not_double_prefixed() -> None:
    plugin = _StubPlugin(outcomes=[_ENTRIES])
    catalog = ModelCatalog(clock=_Clock())
    assert await catalog.ids_for(plugin, client=_CLIENT, limits=None) == frozenset({"stubprov/a/x"})


@pytest.mark.asyncio
async def test_served_tier_transitions_are_logged_once_per_change(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[_ENTRIES, DiscoveryError("timeout"), DiscoveryError("timeout")])
    catalog = ModelCatalog(clock=clock)
    with caplog.at_level(logging.INFO, logger="aigateway.core.model_catalog"):
        assert await _entries(catalog, plugin) == _ENTRIES
        assert await _entries(catalog, plugin) == _ENTRIES  # cached: same tier, no new line
        fresh_lines = [r for r in caplog.records if "tier=fresh" in r.getMessage()]
        clock.value += _SOURCE.ttl_s + 1.0
        assert await _entries(catalog, plugin) == _ENTRIES  # failed refresh -> stale last-good
        clock.value += _SOURCE.stale_ttl_s + 1.0
        assert await _entries(catalog, plugin) is None  # past the window -> compiled seeds
    text = caplog.text
    # WHY: during an outage the per-attempt warnings look identical at minute 30
    # (users still see the full stale listing) and at hour 2 (users see only
    # seeds). The tier line is what tells those two states apart.
    assert len(fresh_lines) == 1, "an unchanged tier must not re-log"
    assert "tier=stale" in text
    assert "tier=seeds" in text
    assert "stubprov/a/x" not in text  # counts and tiers only, never content


@pytest.mark.asyncio
async def test_recovery_back_to_fresh_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()
    plugin = _StubPlugin(outcomes=[DiscoveryError("unreachable"), _ENTRIES])
    catalog = ModelCatalog(clock=clock)
    with caplog.at_level(logging.INFO, logger="aigateway.core.model_catalog"):
        assert await _entries(catalog, plugin) is None
        clock.value += _SOURCE.failure_ttl_s + 1.0
        assert await _entries(catalog, plugin) == _ENTRIES
    messages = [r.getMessage() for r in caplog.records if "tier=" in r.getMessage()]
    assert any("tier=seeds" in m for m in messages)
    assert any("tier=fresh" in m for m in messages)
