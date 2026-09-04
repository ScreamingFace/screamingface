"""OME-1026 — the app-lifetime wiring and lifecycle of live model discovery.

FEATURE: one place that owns "what discovery objects does this process hold, when do
they start, and how do they stop". Three caches and a task manager are built here,
prewarmed here, and shut down here, so the application factory does not have to
carry that lifecycle alongside routing, auth modes and exception handlers.

INVARIANT (kill switch): ``AIGW_DISCOVERY_ENABLED=false`` must audit to ZERO
discovery egress of any kind. Every object below is built from the same flag, so
the audit is one grep in one module rather than four scattered constructions.

AIDEV-NOTE: this is APP-layer wiring, not core. It reads ``app.state``, which core
must never do — the primitives it composes (``ModelCatalog``,
``ProfileModelCatalog``, ``BackgroundRefreshManager``) live in ``core`` and know
nothing about FastAPI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .core.background_refresh import BackgroundRefreshManager
from .core.discovery_runtime import DiscoveryRuntime
from .core.model_catalog import build_model_catalog
from .core.parameter_discovery import DiscoveryLimits, HttpxDiscoveryClient
from .core.parameter_discovery_cache import CacheLimits, ObservationCache, SystemMonotonicClock
from .core.profile_model_catalog import build_profile_model_catalog

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .config import Settings

logger = logging.getLogger(__name__)


def build_discovery_runtime(settings: Settings) -> DiscoveryRuntime | None:
    """Construct the ONE bounded discovery runtime the detailed contract reads from.

    # WHY built once rather than per request: the cache is the whole point. A
    # runtime rebuilt per request would carry an empty cache, turning the TTL into
    # a no-op and re-dialling a public catalog on every contract read.
    # WHY ``None`` when disabled rather than an unbounded stub: the absence of a
    # runtime is the honest "no dynamic evidence", and it leaves no object that
    # could later be handed limits nobody configured.
    # AIDEV-NOTE: ``HttpxDiscoveryClient`` opens (and closes) its connection per
    # fetch, so there is nothing to shut down in the lifespan.
    """
    if not settings.discovery_enabled:
        return None
    return DiscoveryRuntime(
        client=HttpxDiscoveryClient(),
        cache=ObservationCache(
            clock=SystemMonotonicClock(),
            limits=CacheLimits(
                ttl_s=settings.discovery_cache_ttl_seconds,
                stale_ttl_s=settings.discovery_cache_stale_ttl_seconds,
                max_entries=settings.discovery_cache_max_entries,
                failure_ttl_s=settings.discovery_cache_failure_ttl_seconds,
            ),
        ),
        limits=DiscoveryLimits(
            timeout_s=settings.discovery_timeout_seconds,
            max_bytes=settings.discovery_max_bytes,
        ),
    )


def install_discovery(app: FastAPI, *, settings: Settings) -> None:
    """Attach every discovery object this process will use to ``app.state``.

    Requires ``app.state.providers`` to be populated already: the public refresh
    manager's capacity IS the provider count, which makes it a measured bound rather
    than an invented limit.
    """
    app.state.discovery_runtime = build_discovery_runtime(settings)
    # OME-972: the app-lifetime, process-local live model-listing catalog. It owns no
    # transport; the models route passes the runtime's client/limits per call.
    app.state.model_catalog = build_model_catalog(enabled=settings.discovery_enabled)
    # OME-1026: the app-lifetime PRIVATE catalog — one snapshot per authenticated
    # profile, fetched with that profile's own stored credential and served only to its
    # owner. It owns no transport either.
    app.state.profile_model_catalog = build_profile_model_catalog(settings=settings)
    # The PUBLIC catalog refreshes' home, shared by startup prewarm and every
    # ``GET /v1/models`` request. A manager rather than a bare ``create_task`` so each
    # task is strongly referenced (asyncio keeps only a weak one), deduplicated by
    # catalog identity, observable, and cancelled AND awaited at shutdown instead of
    # being destroyed while pending.
    app.state.public_refreshes = BackgroundRefreshManager[tuple[str, str, str]](
        max_inflight=max(1, len(tuple(app.state.providers.all()))),
        shutdown_timeout_s=settings.discovery_timeout_seconds,
    )


def start_public_prewarm(app: FastAPI) -> int:
    """Start one background refresh per PUBLIC provider catalog. Returns how many.

    # WHY it only STARTS and never awaits (OME-1026 F2): the refreshes it launches are
    # keyed exactly as ``GET /v1/models`` keys them, so a request arriving during
    # prewarm JOINS the running task and waits only its own budget. An outer coroutine
    # that awaited them all would add a second task layer that owns nothing, consume a
    # capacity slot, and make "startup never waits on an upstream catalog" a property of
    # the wrapper rather than of this function.
    # INVARIANT: a failure here is not an error. ``entries_for`` already maps a failed
    # refresh to "serve seeds", so prewarm's only job is to pay the first fetch's
    # latency before a user does.
    # INVARIANT (F6): a PROGRAMMING error is not absorbed either. Each task is owned by
    # the manager, whose ``_reap`` retains anything that is not a ``DiscoveryError``
    # until an explicit observation point — the suite asserts on that in teardown, so a
    # prewarm that reached the real internet fails the run instead of logging one line.
    # AIDEV-NOTE: PUBLIC providers only. Prewarming private catalogs would mean
    # enumerating and decrypting every tenant's credential at process startup, which is
    # forbidden: a private snapshot is fetched only when its own owner asks for it.
    # ``start_public_refresh`` refuses a PROFILE_CREDENTIAL provider structurally.
    """
    catalog = app.state.model_catalog
    runtime = app.state.discovery_runtime
    if catalog is None or runtime is None:
        return 0
    started = 0
    for plugin in app.state.providers.all():
        task = catalog.start_public_refresh(
            plugin,
            client=runtime.client,
            limits=runtime.limits,
            refreshes=app.state.public_refreshes,
        )
        if task is not None:
            started += 1
    logger.info("live model catalog prewarm started refreshes=%d", started)
    return started


async def shutdown_discovery(app: FastAPI) -> None:
    """Stop background discovery before the event loop goes away.

    # WHY cancel AND await: a cancelled-but-unawaited task emits "Task was destroyed
    # but it is pending!" and — worse — its own ``finally`` cleanup may never run, so
    # the discovery transport's socket would leak across a reload or a TestClient
    # lifecycle. Both managers bound their own wait, so this cannot hang shutdown.
    """
    await app.state.public_refreshes.aclose()
    if app.state.profile_model_catalog is not None:
        await app.state.profile_model_catalog.aclose()
