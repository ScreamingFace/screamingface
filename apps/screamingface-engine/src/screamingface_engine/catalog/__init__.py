"""Public surface and production wiring for Engine model discovery.

Re-exports the hexagonal port (``catalog/port.py``), the aigateway adapter
(``catalog/aigateway.py``), and the caching layer (``catalog/cache.py``), and
provides composition builders that retain one Gateway client while projecting model discovery
and profile-bound details onto the Engine's declared executable routes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

import httpx

from screamingface_engine.catalog.admission import AdmittedModels, ModelAdmissionSource
from screamingface_engine.catalog.aigateway import AigatewayCatalogSource
from screamingface_engine.catalog.cache import CacheCounters, CachedCatalog, CatalogService
from screamingface_engine.catalog.executable import (
    ExecutableCatalog,
    ExecutableModelParameterSource,
)
from screamingface_engine.catalog.port import (
    CatalogBadResponse,
    CatalogError,
    CatalogRejected,
    CatalogSource,
    CatalogUnavailable,
    Credential,
    ModelCatalog,
    ModelNotInstalled,
    ModelParameterBadResponse,
    ModelParameterResponse,
    ModelParameterSource,
    compute_etag,
)
from screamingface_engine.config import Settings
from screamingface_engine.world_config import WorldConfigError, declared_model_ids

logger = logging.getLogger(__name__)

# WHY 30s (OME-1170): a COLD gateway composes a model's parameter datasheet in 3–11.8s per
# model (measured 2026-09-10 across six models; warm repeats ~0.002s). The previous 10.0s
# budget sat inside that range, so the first fetch after a stack start deterministically
# timed out for the slower models and surfaced as HTTP 504. Do not lower this below the
# measured cold ceiling; the warm path never comes near it.
_UPSTREAM_TIMEOUT_S = 30.0


def _default_client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=_UPSTREAM_TIMEOUT_S)


def build_catalog_service(
    settings: Settings,
    *,
    client_factory: Callable[[str], httpx.AsyncClient] = _default_client,
) -> CachedCatalog | None:
    """Wire the aigateway-backed, cached catalog service from ``settings``.

    Returns None when no aigateway base URL is configured, matching the 503
    "not configured" response `rest/catalog.py` raises for that case.
    """
    base_url = settings.aigateway_base_url
    if not base_url:
        return None
    client = client_factory(base_url)
    source = AigatewayCatalogSource(client)
    return CachedCatalog(
        source,
        parameter_source=source,
        ttl_s=settings.models_cache_ttl_s,
        stale_max_s=settings.models_cache_stale_max_s,
        error_backoff_s=settings.models_cache_error_backoff_s,
        max_entries=settings.models_cache_max_entries,
        upstream_concurrency=settings.models_upstream_concurrency,
        source_aclose=client.aclose,
    )


def build_executable_catalog_service(
    settings: Settings,
    env: Mapping[str, str],
    *,
    client_factory: Callable[[str], httpx.AsyncClient] = _default_client,
) -> ExecutableCatalog | None:
    """Wire Gateway discovery through the Engine routes, validating them when configured.

    Returns None — the same "not configured" signal :func:`build_catalog_service` gives, which
    ``rest/catalog.py`` answers with 503 — when there is no Gateway base URL, or when the
    declared world is unusable.

    WHY an unusable world DEGRADES rather than raising: this runs inside the App's composition
    root, so a raise here takes down run submission, streaming, connections and health along
    with discovery — for a file whose only reader used to be the Runner. The failure is still
    loud (an ERROR log naming the cause, and 503 on both catalog routes, never a silently empty
    catalog), and it is still fail-FAST for execution: the Runner validates the same world at
    Job start, where a bad route actually changes what runs. This mirrors the reasoning at
    ``runner/main.py``'s ``_world`` — a bad config surfaces as a scoped failure, not as a
    process that dies before it can report anything.
    """

    if not settings.aigateway_base_url:
        return None
    try:
        model_ids = declared_model_ids(env)
    except WorldConfigError:
        # The cause is logged, not raised: `rest/catalog.py` turns None into the generic 503, so
        # an unauthenticated caller never learns why this deployment's world is unusable.
        logger.error("model discovery disabled: the declared world is unusable", exc_info=True)
        return None
    logger.info("model discovery projects onto %d declared route(s)", len(model_ids))
    source = build_catalog_service(settings, client_factory=client_factory)
    # OME-880: dynamic admission wiring. The gateway adapter doubles as the admission source
    # (structural check, so a future parameter-only source simply gets no dynamic admission);
    # a grant invalidates the cached catalog so `GET /v1/models` re-reads upstream.
    parameter_source = None if source is None else source.model_parameter_source
    admission_source = (
        parameter_source if isinstance(parameter_source, ModelAdmissionSource) else None
    )
    # `source is None` cannot happen — it guards on the same base URL checked above — but the
    # narrowing is expressed rather than asserted, so the two guards drifting apart degrades
    # exactly like an unconfigured deployment instead of raising at import time under `-O`.
    return (
        None
        if source is None
        else ExecutableCatalog(
            source,
            model_ids,
            admitted=AdmittedModels(),
            admission_source=admission_source,
            on_admitted=source.invalidate,
        )
    )


__all__ = [
    "AigatewayCatalogSource",
    "CacheCounters",
    "CachedCatalog",
    "CatalogBadResponse",
    "CatalogError",
    "CatalogRejected",
    "CatalogService",
    "CatalogSource",
    "CatalogUnavailable",
    "Credential",
    "ExecutableCatalog",
    "ExecutableModelParameterSource",
    "ModelCatalog",
    "ModelNotInstalled",
    "ModelParameterBadResponse",
    "ModelParameterResponse",
    "ModelParameterSource",
    "build_catalog_service",
    "build_executable_catalog_service",
    "compute_etag",
]
