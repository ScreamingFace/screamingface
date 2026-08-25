"""OME-972 — the deployment-wide live model-listing catalog.

FEATURE: live model discovery — ``GET /v1/models`` consults this catalog per
provider and lists the cached live snapshot when one is healthy, falling back
to the provider's compiled ``register_models()`` seeds when the catalog is
cold or degraded (snapshot-or-fallback).

INVARIANT (hexagonal): core consults only the ``model_discovery_source`` /
``discover_live_models`` port pair — it never learns provider URLs, parsers,
or which entries were seeds. The provider returns FINISHED rows.

INVARIANT: live data changes what is LISTED, never what is dispatchable —
nothing here touches admission, dispatch, or credentials, and the catalog is
consulted off the chat critical path only.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, cast

from .model_capabilities import canonical_model_id
from .parameter_discovery import DiscoveryError
from .parameter_discovery_cache import (
    CacheLimits,
    MonotonicClock,
    ObservationCache,
    SystemMonotonicClock,
)

if TYPE_CHECKING:
    from .parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from .plugin_base import ModelDiscoverySource, ModelEntry

logger = logging.getLogger(__name__)

# WHY 4: each provider cache holds ONE listing key; the headroom exists only so
# a source-revision bump does not evict the key it replaces mid-transition.
_CACHE_MAX_ENTRIES = 4


class ModelListingProvider(Protocol):
    """The minimal provider surface the catalog consumes (hexagonal port).

    # WHY a Protocol and not ``ProviderPluginBase``: the catalog needs exactly
    # these three members — depending on the full plugin contract would couple
    # the deployment-wide cache to every unrelated provider hook and force test
    # doubles to carry the whole base class.
    """

    custom_llm_provider: str

    def model_discovery_source(self) -> ModelDiscoverySource | None: ...

    async def discover_live_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
    ) -> tuple[ModelEntry, ...] | None: ...


class ModelCatalog:
    """Per-provider cached live listings behind single-flight refresh.

    # AIDEV-NOTE: the catalog owns NO transport — callers pass the discovery
    # runtime's client/limits per call (the admission-route precedent), so the
    # test suite's transport seams govern every dial this class can cause.
    """

    def __init__(self, *, clock: MonotonicClock | None = None) -> None:
        self._clock = clock if clock is not None else SystemMonotonicClock()
        self._caches: dict[str, ObservationCache] = {}
        # OME-972: the tier each provider was last SERVED at, so a change is
        # logged once instead of every request. Per-attempt warnings cannot
        # answer "are users still seeing live models?" — they look identical
        # while a stale snapshot still serves and after it collapses to seeds.
        self._served_tier: dict[str, str] = {}

    async def entries_for(
        self,
        plugin: ModelListingProvider,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
    ) -> tuple[ModelEntry, ...] | None:
        """The provider's live listing, or ``None`` meaning "fall back to seeds".

        ``None`` covers: no declared source, a cold failure, and a snapshot
        older than the stale window. A stale-but-trusted snapshot is returned
        as entries — the caller cannot (and must not) tell it from fresh.
        """
        source = plugin.model_discovery_source()
        if source is None:
            return None
        provider = plugin.custom_llm_provider
        cache = self._cache_for(provider, source)

        async def _refresh() -> tuple[ModelEntry, ...]:
            try:
                entries = await plugin.discover_live_models(client=client, limits=limits)
            except AssertionError:
                # INVARIANT: the test suite's no-egress tripwire raises
                # AssertionError — absorbing it would turn a forbidden real
                # dial into a quiet degraded outcome. Stay loud.
                raise
            except DiscoveryError as error:
                self._log_failure(provider, error)
                raise
            except Exception as error:
                # Sanitized: the TYPE names the bug class for operators; the
                # message may carry upstream content and is dropped, and the
                # cause chain is cut so it cannot resurface downstream.
                logger.warning(
                    "live model listing refresh failed provider=%s reason=internal_error type=%s",
                    provider,
                    type(error).__name__,
                )
                raise DiscoveryError("internal_error") from None
            if entries is None:
                # AIDEV-NOTE: a None under a DECLARED source would be stored as
                # a successful fresh value and evict the last good listing —
                # convert the inconsistency to a failed attempt instead (the
                # same rule DiscoveryRuntime.observe enforces as no_snapshot).
                error = DiscoveryError("no_snapshot")
                self._log_failure(provider, error)
                raise error
            logger.info(
                "live model listing refreshed provider=%s models=%d", provider, len(entries)
            )
            return entries

        outcome = await cache.get_or_refresh(source.key, revision=source.revision, refresh=_refresh)
        if outcome.value is None:
            self._log_tier(provider, "seeds")
            return None
        self._log_tier(provider, outcome.freshness)
        return cast("tuple[ModelEntry, ...]", outcome.value)

    async def ids_for(
        self,
        plugin: ModelListingProvider,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
    ) -> frozenset[str]:
        """The gateway model ids of the live listing; empty when degraded/absent."""
        entries = await self.entries_for(plugin, client=client, limits=limits)
        if entries is None:
            return frozenset()
        # INVARIANT: canonical ids, matching exactly what ``/v1/models`` publishes
        # (``model_row`` canonicalizes too). A provider using the established
        # unprefixed ``model_name`` convention would otherwise publish an id this
        # set never matches — and the detail route would 404 its own listing.
        return frozenset(
            canonical_model_id(
                custom_llm_provider=plugin.custom_llm_provider, model_name=entry.model_name
            )
            for entry in entries
        )

    def _cache_for(self, provider: str, source: ModelDiscoverySource) -> ObservationCache:
        # WHY per provider: the cache policy (TTL/stale/damping) rides on each
        # provider's declared source — one shared cache would force one policy
        # on catalogs with very different upstream freshness guarantees.
        cache = self._caches.get(provider)
        if cache is None:
            cache = ObservationCache(
                clock=self._clock,
                limits=CacheLimits(
                    ttl_s=source.ttl_s,
                    stale_ttl_s=source.stale_ttl_s,
                    max_entries=_CACHE_MAX_ENTRIES,
                    failure_ttl_s=source.failure_ttl_s,
                ),
            )
            self._caches[provider] = cache
        return cache

    def _log_tier(self, provider: str, tier: str) -> None:
        """Log the SERVED tier once per change (fresh / stale / seeds)."""
        if self._served_tier.get(provider) == tier:
            return
        self._served_tier[provider] = tier
        if tier == "fresh":
            logger.info("live model listing serving provider=%s tier=fresh", provider)
        else:
            logger.warning("live model listing degraded provider=%s tier=%s", provider, tier)

    @staticmethod
    def _log_failure(provider: str, error: DiscoveryError) -> None:
        # WHY the status rides along: reason stays the closed vocabulary, but
        # 401 (auth onset) and 5xx (outage) need different operator responses.
        if error.status is not None:
            logger.warning(
                "live model listing refresh failed provider=%s reason=%s status=%d",
                provider,
                error.reason,
                error.status,
            )
        else:
            logger.warning(
                "live model listing refresh failed provider=%s reason=%s",
                provider,
                error.reason,
            )


def build_model_catalog(*, enabled: bool) -> ModelCatalog | None:
    """The app-lifetime catalog, or ``None`` under the discovery kill switch.

    INVARIANT: ``AIGW_DISCOVERY_ENABLED=false`` silences ALL discovery egress —
    the listing catalog obeys the same switch as the parameter-discovery
    runtime, so one flag audits to zero catalog traffic.
    """
    if not enabled:
        return None
    return ModelCatalog()
