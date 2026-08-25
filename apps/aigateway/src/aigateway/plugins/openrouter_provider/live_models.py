"""OME-972 — live discovery of the OpenRouter public model catalog.

FEATURE: automatic model discovery — ``GET /v1/models`` lists what OpenRouter
actually serves now (plain ids only), refreshed through a deployment-wide
cached snapshot instead of compiled seeds frozen at deploy time.

INVARIANT (fail-closed, all-or-nothing): a catalog read that is incomplete,
malformed, empty, over a cap, or paginated off-policy raises a sanitized
``DiscoveryError`` and is NEVER partially returned — the cache keeps serving
the last good snapshot instead. Live data changes what is LISTED, never what
is dispatchable: dispatch admission (``admission.py``) is untouched.

INVARIANT (auto-publish shape): only plain ``vendor/model`` ids pass — the
same ``_admissible_upstream_id`` predicate the admission route enforces.
Colon variants and tilde aliases stay reachable via explicit operator config
(``AIGW_OPENROUTER_DEFAULT_MODELS``) or direct dispatch, never via listing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    fetch_discovery_json,
)
from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry

from .admission import _admissible_upstream_id
from .discovery import _MAX_CATALOG_MODELS, ALLOWED_ORIGINS, MODELS_URL
from .settings import GATEWAY_MODEL_PREFIX, OpenRouterPluginSettings

# WHY 250 (not the API maximum): each page must clear the §5.2 envelope's
# 1 MB byte cap and 50k node cap with >2x headroom — a fatter page that
# drifts over either cap would fail EVERY refresh at once, deployment-wide.
_PAGE_LIMIT = 250
# WHY: 40 pages x 250 = the same 10_000-model bound the admission catalog
# already enforces on the single-page read; more pages means a runaway or
# looping chain, not a bigger catalog.
_MAX_PAGES = _MAX_CATALOG_MODELS // _PAGE_LIMIT
_MAX_PUBLISHED_MODELS = 5_000
_MAX_ID_LENGTH = 256
# INVARIANT: single-flight dedupes the DIAL, not the wait — every concurrent
# lister queues on one refresh, so the WHOLE pagination chain gets one
# aggregate wall-clock deadline on top of the per-page timeout.
_AGGREGATE_TIMEOUT_S = 10.0

_ORIGIN = "https://openrouter.ai"
_MODELS_PATH = "/api/v1/models"
# INVARIANT: the pinned query policy. output_modalities=text keeps the
# catalog to chat-servable models; every followed ``links.next`` must carry
# EXACTLY these params plus the one expected offset — nothing else.
_PINNED_QUERY = {"output_modalities": "text", "limit": str(_PAGE_LIMIT)}
LIVE_MODELS_URL = f"{MODELS_URL}?output_modalities=text&limit={_PAGE_LIMIT}"

# INVARIANT: identity + cache policy declared BEFORE any fetch (§5.3) — the
# deployment-wide catalog judges a stored snapshot by this revision without
# dialing. Bumping the revision (e.g. on a parser change) invalidates every
# stored snapshot at once.
LIVE_MODELS_DISCOVERY_SOURCE = ModelDiscoverySource(
    key="openrouter:models:list",
    revision="openrouter:models:list-v1",
    ttl_s=300.0,
    stale_ttl_s=3600.0,
    failure_ttl_s=30.0,
)


def parse_catalog_page(payload: Any) -> tuple[tuple[str, ...], str | None, int]:
    """One page of the catalog -> (ids in page order, next link, total_count).

    STRICT by construction: the envelope must be a dict carrying a ``data``
    list, a ``links`` mapping with an explicit ``next`` (string or null), and a
    non-negative integer ``total_count``; every row must be an object with a
    string ``id``. Anything else raises ``malformed_json``.

    INVARIANT: nothing is skipped and salvaged. A page whose rows or
    completeness metadata cannot be parsed is not a trustworthy census of what
    upstream serves, so it can never be cached as a fresh, complete catalog —
    tolerating a bad row would publish a listing that silently omits models,
    which is indistinguishable from upstream having retired them.

    # WHY the metadata is REQUIRED rather than advisory: without ``links.next``
    # and ``total_count`` a page cannot be told apart from a truncated read, and
    # the live envelope always carries both (probed 2026-08-24 — the final page
    # says ``links.next = null``, it does not omit the key).
    """
    if not isinstance(payload, dict):
        raise DiscoveryError("malformed_json")
    data = payload.get("data")
    if not isinstance(data, list):
        raise DiscoveryError("malformed_json")
    ids: list[str] = []
    for row in data:
        if not isinstance(row, dict):
            raise DiscoveryError("malformed_json")
        model_id = row.get("id")
        if not isinstance(model_id, str):
            raise DiscoveryError("malformed_json")
        ids.append(model_id)
    links = payload.get("links")
    if not isinstance(links, dict) or "next" not in links:
        raise DiscoveryError("malformed_json")
    next_url = links["next"]
    if next_url is not None and not isinstance(next_url, str):
        raise DiscoveryError("malformed_json")
    total_count = payload.get("total_count")
    # bool is an int subclass in Python: ``total_count: true`` must not read as 1.
    if not isinstance(total_count, int) or isinstance(total_count, bool) or total_count < 0:
        raise DiscoveryError("malformed_json")
    return tuple(ids), next_url, total_count


def validate_next_url(next_url: str, *, expected_offset: int) -> str:
    """Resolve + strictly validate a ``links.next`` BEFORE it is ever dialed.

    INVARIANT: exact https origin, exact ``/api/v1/models`` path, exactly the
    pinned query plus the one expected numeric offset, no fragment, no
    duplicates, no extras. Any deviation is ``model_catalog_truncated`` — the
    whole refresh fails and nothing partial is returned or cached.
    """
    absolute = urljoin(_ORIGIN, next_url)
    parts = urlsplit(absolute)
    origin = f"{parts.scheme}://{parts.netloc}"
    if parts.scheme != "https" or origin not in ALLOWED_ORIGINS or parts.path != _MODELS_PATH:
        raise DiscoveryError("model_catalog_truncated")
    if parts.fragment:
        raise DiscoveryError("model_catalog_truncated")
    # WHY exact-dict comparison of parse_qs output: it refuses unexpected and
    # duplicated parameters in the same check — a duplicated offset parses to a
    # two-element list and no longer equals the expected one-element value.
    expected = {key: [value] for key, value in _PINNED_QUERY.items()}
    expected["offset"] = [str(expected_offset)]
    if parse_qs(parts.query, keep_blank_values=True) != expected:
        raise DiscoveryError("model_catalog_truncated")
    return absolute


def publishable_upstream_ids(ids: Iterable[str]) -> tuple[str, ...]:
    """The deduplicated, sorted, auto-publishable subset of raw catalog ids.

    INVARIANT: zero survivors fail closed (an empty catalog is
    indistinguishable from a broken read and must not evict the last good
    snapshot); over the publish cap fails closed (never truncate-and-cache).
    """
    unique = {
        upstream
        for upstream in ids
        if len(upstream) <= _MAX_ID_LENGTH and _admissible_upstream_id(upstream)
    }
    if not unique:
        raise DiscoveryError("model_catalog_empty")
    if len(unique) > _MAX_PUBLISHED_MODELS:
        raise DiscoveryError("model_catalog_too_large")
    return tuple(sorted(unique))


def explicit_operator_entries(settings: OpenRouterPluginSettings) -> tuple[ModelEntry, ...]:
    """Operator-configured model entries, or none when config is compiled defaults.

    WHY ``model_fields_set``: pydantic records a field there only when a value
    arrived from the constructor or the environment — a ``default_factory``
    fill does not register. That is the exact line between "the operator asked
    for these models" (survive every healthy snapshot, colon variants included)
    and "compiled fallback seeds" (replaced entirely by a healthy snapshot).
    """
    if "default_models" not in settings.model_fields_set:
        return ()
    return tuple(
        ModelEntry(model_name=slug, litellm_params={"model": slug})
        for slug in settings.default_models
    )


def live_listing_entries(
    settings: OpenRouterPluginSettings, upstream_ids: tuple[str, ...]
) -> tuple[ModelEntry, ...]:
    """The finished healthy-snapshot listing: operator entries first, then discovered.

    INVARIANT: the provider owns this merge — core receives finished rows and
    never learns which entries were seeds, so seed provenance cannot leak into
    route logic. Operator entries keep configured order; discovered ids arrive
    sorted from ``publishable_upstream_ids`` and dedupe against operator rows.
    """
    operator = explicit_operator_entries(settings)
    seen = {entry.model_name for entry in operator}
    discovered = tuple(
        ModelEntry(model_name=gateway_id, litellm_params={"model": gateway_id})
        for upstream in upstream_ids
        if (gateway_id := f"{GATEWAY_MODEL_PREFIX}{upstream}") not in seen
    )
    return operator + discovered


async def fetch_live_model_ids(
    *, client: DiscoveryHttpClient, limits: DiscoveryLimits | None = None
) -> tuple[str, ...]:
    """Every raw model id in the catalog, or a sanitized ``DiscoveryError``.

    Walks the pinned first page plus every strictly validated ``links.next``
    under ONE aggregate wall-clock deadline (on top of the per-page envelope
    timeout). All-or-nothing: a failure on any page discards everything —
    pages already collected are never returned, so the caller's cache can
    never store a partial catalog as fresh.
    """
    bounds = limits if limits is not None else DiscoveryLimits()
    collected: list[str] = []
    total_count: int | None = None
    try:
        async with asyncio.timeout(_AGGREGATE_TIMEOUT_S):
            url = LIVE_MODELS_URL
            pages = 0
            while True:
                # INVARIANT: the page cap refuses BEFORE dialing page N+1 — a
                # looping or runaway next-chain costs at most _MAX_PAGES dials.
                if pages >= _MAX_PAGES:
                    raise DiscoveryError("model_catalog_truncated")
                pages += 1
                payload = await fetch_discovery_json(
                    url, allowed_origins=ALLOWED_ORIGINS, client=client, limits=bounds
                )
                ids, next_url, page_total = parse_catalog_page(payload)
                # INVARIANT: the census must hold STILL for the whole walk. A
                # total that moves between pages means the catalog changed under
                # us (or a page answers a different query), so the rows we hold
                # are not one coherent snapshot.
                if total_count is None:
                    total_count = page_total
                elif page_total != total_count:
                    raise DiscoveryError("model_catalog_truncated")
                collected.extend(ids)
                if len(collected) > _MAX_CATALOG_MODELS:
                    raise DiscoveryError("model_catalog_too_large")
                if next_url is None:
                    break
                url = validate_next_url(next_url, expected_offset=pages * _PAGE_LIMIT)
    except TimeoutError:
        # sanitized: the aggregate deadline expiry, same token the per-page
        # envelope uses — callers need one vocabulary, not two.
        raise DiscoveryError("timeout") from None
    # WHY reconciliation LAST: a claimed count differing from what the finished
    # chain delivered means a page went missing silently, which is truncation
    # even though every dial succeeded. ``total_count`` is never None here —
    # the strict parser required it on every page, including the first.
    if total_count != len(collected):
        raise DiscoveryError("model_catalog_truncated")
    return tuple(collected)
