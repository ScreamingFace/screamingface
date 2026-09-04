"""OME-972 — the app-lifetime, process-local live model-listing catalog.

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

INVARIANT (OME-1026 scope): this catalog serves ``PUBLIC_GLOBAL`` providers ONLY.
One snapshot per provider is shared with every account, so a credential-derived
(``PROFILE_CREDENTIAL``) listing is refused outright — see ``_public_source``. Private
per-credential snapshots live in ``profile_model_catalog`` and never pass through
here; ``GET /v1/models`` composes them per CALLER (OME-1026 U3), so "no account's
models can enter a cache another account reads" stays structural rather than a
rule each caller must remember.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, cast

from .background_error_sink import mark_observed
from .model_capabilities import canonical_ids
from .model_discovery_scope import DiscoveryScope, discovery_scope_of
from .parameter_discovery import DiscoveryError
from .parameter_discovery_cache import (
    CacheLimits,
    MonotonicClock,
    ObservationCache,
    SystemMonotonicClock,
)

if TYPE_CHECKING:
    import asyncio

    from .background_refresh import BackgroundRefreshManager
    from .parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from .plugin_base import ModelDiscoverySource, ModelEntry

# The identity one public refresh runs under. A TUPLE, matching the private catalog's
# convention: a joined string would let a provider name alias a sibling identity
# through the separator, and it would turn "cancel this provider" into prefix
# matching. The REVISION rides along so a source-revision bump starts a new refresh
# instead of joining one that is still computing the superseded revision.
type PublicRefreshKey = tuple[str, str, str]

logger = logging.getLogger(__name__)

# WHY 4: each provider cache holds ONE listing key; the headroom exists only so
# a source-revision bump does not evict the key it replaces mid-transition.
_CACHE_MAX_ENTRIES = 4


def _public_source(plugin: object) -> ModelDiscoverySource | None:
    """The provider's declared source, but ONLY when it is safe to share globally.

    ``None`` means "this provider has no place in the shared catalog" — no declared
    source, or a ``PROFILE_CREDENTIAL`` scope whose listing belongs to one account.
    Both are normal answers whose correct global result is the compiled seeds.

    # WHY it is a function and not inlined twice: the same two questions decide
    # whether a refresh may be STARTED (``start_public_refresh``) and whether one may
    # be CONSULTED (``entries_for``). Asking them in one place is what keeps a future
    # caller from acquiring a task slot — or a dial — for a private provider.
    """
    scope = discovery_scope_of(plugin)
    if scope is not DiscoveryScope.PUBLIC_GLOBAL:
        return None
    declare = getattr(plugin, "model_discovery_source", None)
    if declare is None:  # pragma: no cover - the Protocol requires it
        return None
    return declare()


class ModelListingProvider(Protocol):
    """The minimal provider surface the catalog consumes (hexagonal port).

    # WHY a Protocol and not ``ProviderPluginBase``: the catalog needs exactly
    # these three members — depending on the full plugin contract would couple
    # the app-lifetime cache to every unrelated provider hook and force test
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
        # INVARIANT (OME-1026, the load-bearing one): this catalog is SHARED — one
        # snapshot per provider, served to every account through GET /v1/models. A
        # PROFILE_CREDENTIAL provider's listing is derived from ONE account's
        # credential, so admitting it here would publish that account's
        # entitlements deployment-wide. Refuse the scope outright, BEFORE consulting
        # the source, so no cache slot is opened and no dial can happen.
        # WHY here rather than only in the route: the route is one caller. Enforcing
        # it at the shared cache means no future consumer — a prewarm task, an
        # admission path, a new endpoint — can reintroduce the leak by forgetting.
        # AIDEV-NOTE: deliberately NOT an error. A provider legitimately declares a
        # private scope; "not for the global listing" is a normal answer, and the
        # caller's seed fallback is the correct global result.
        source = _public_source(plugin)
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

    def start_public_refresh(
        self,
        plugin: ModelListingProvider,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
        refreshes: BackgroundRefreshManager[PublicRefreshKey],
    ) -> asyncio.Task[Any] | None:
        """Start — or join — the background refresh of one PUBLIC provider's listing.

        Returns the task doing the work, or ``None`` when there is no work to do (a
        private or source-less provider) and when the manager refuses it (closed, or
        at capacity). Every ``None`` means the same thing to a caller: serve seeds.

        # WHY this primitive is shared by startup prewarm AND the listing route: they
        # must use the SAME key, or a request arriving during prewarm starts a second
        # refresh of the identical catalog instead of joining the one already running —
        # which is precisely how a cold request came to wait out the provider's own
        # 10-second aggregate deadline (OME-1026 F2).
        """
        source = _public_source(plugin)
        if source is None:
            return None
        key: PublicRefreshKey = (plugin.custom_llm_provider, source.key, source.revision)
        return refreshes.start_or_join(
            key, lambda: self.entries_for(plugin, client=client, limits=limits)
        )

    async def entries_within(
        self,
        plugin: ModelListingProvider,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
        refreshes: BackgroundRefreshManager[PublicRefreshKey],
        budget_s: float,
    ) -> tuple[ModelEntry, ...] | None:
        """``entries_for``, but the CALLER waits at most ``budget_s`` for it.

        INVARIANT (F2): the answer arrives within the budget; the refresh is NOT
        bounded by it. On expiry this returns ``None`` — "serve seeds" — while the
        shared refresh runs on, so the next request reads a real snapshot.

        # WHY the budget cannot simply wrap ``entries_for``: the refresh runs inside
        # ``ObservationCache.get_or_refresh``, which awaits it while HOLDING the
        # single-flight lock. ``asyncio.wait_for`` would cancel the winner mid-flight —
        # no failure recorded, lock released, next arrival dialing again. One upstream
        # attempt would become N under exactly the slow-upstream conditions that caused
        # the timeout. So the work lives in a task this method does not own, and
        # ``wait_up_to`` (built on ``asyncio.wait``) never cancels what it waits on.
        # AIDEV-NOTE: the honest trade-off. A snapshot that is expired but still inside
        # its stale window is served by ``entries_for`` only AFTER the refresh fails, so
        # a budget expiry answers seeds rather than that stale snapshot. Seeds within
        # the budget is the owner-approved answer; the stale row set returns on the next
        # request. Serving stale here would require a non-refreshing read of the cache.
        """
        task = self.start_public_refresh(plugin, client=client, limits=limits, refreshes=refreshes)
        if task is None:
            return None
        if not await refreshes.wait_up_to(task, timeout=budget_s):
            return None
        if task.cancelled():
            # Superseded or shut down while we waited. Not this caller's failure.
            return None
        error = task.exception()
        if error is None:
            return cast("tuple[ModelEntry, ...] | None", task.result())
        if isinstance(error, DiscoveryError):
            return None
        # INVARIANT (F6): anything else is a programming error — the suite's no-egress
        # tripwire above all. Raise it to the caller who waited, and mark it observed so
        # the manager's retention sink does not report the same bug a second time.
        mark_observed(error)
        raise error

    async def ids_for(
        self,
        plugin: ModelListingProvider,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
    ) -> frozenset[str]:
        """The gateway model ids of the live listing; empty when degraded/absent."""
        return canonical_ids(
            cast("Any", plugin), await self.entries_for(plugin, client=client, limits=limits)
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
