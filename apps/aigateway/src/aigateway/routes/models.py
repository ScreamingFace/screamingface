from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

from ..core.auth.middleware import CurrentAccount
from ..core.discovery_budget import user_wait_budget
from ..core.model_capabilities import model_row
from ..core.parameter_discovery import DiscoveryError

if TYPE_CHECKING:
    from ..core.plugin_base import ModelEntry

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request, _current: CurrentAccount) -> dict:
    """OpenAI-compatible model listing, aggregated from all loaded provider plugins.

    Each row carries the OME-479 locked hybrid summary (canonical dispatchable
    ``id`` + effective ``supported_parameters``/``supported_tools`` + literal
    ``reject`` + a same-origin detail URL), composed from each plugin's own
    provider-local rule set.

    OME-972 (snapshot-or-fallback): a provider with a healthy live-catalog
    snapshot lists that snapshot's rows verbatim — the provider owns the merge
    of operator-explicit and discovered entries, so core never learns seed
    provenance. A cold or degraded catalog falls back to the provider's
    compiled ``register_models()`` seeds, byte-identical to static behavior.
    """
    registry = request.app.state.providers
    catalog = request.app.state.model_catalog
    runtime = request.app.state.discovery_runtime
    plugins = list(registry.all())
    listings = await _live_listings(
        plugins,
        catalog=catalog,
        runtime=runtime,
        refreshes=request.app.state.public_refreshes,
    )
    data: list[dict] = []
    seen: set[str] = set()
    for plugin, entries in zip(plugins, listings, strict=True):
        if entries is None:
            entries = plugin.register_models()
        for entry in entries:
            row = model_row(plugin, entry)
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            data.append(row)
    # OME-879: dynamically admitted models (deployment-lifetime, app.state only)
    # join the listing after the catalog/seed rows. An admitted id can now ALSO
    # arrive from a live snapshot (OME-972), so the join deduplicates on the
    # canonical id instead of assuming disjoint sources.
    for model_id, entry in request.app.state.admitted_models.items():
        plugin = registry.get(model_id.split("/", 1)[0])
        if plugin is not None and model_id not in seen:
            seen.add(model_id)
            data.append(model_row(plugin, entry))
    return {"object": "list", "data": data}


async def _live_listings(
    plugins: list[Any],
    *,
    catalog: Any,
    runtime: Any,
    refreshes: Any,
) -> list[tuple[ModelEntry, ...] | None]:
    """Each plugin's live listing (or ``None`` for seeds), fetched CONCURRENTLY.

    # WHY concurrently (OME-1026): awaiting each provider in turn makes this route's
    # worst-case latency the SUM of every provider's discovery timeout, so adding a
    # provider slows the listing for all the others. Cold caches are exactly when a
    # user is most likely to be waiting.
    # INVARIANT (deterministic order): results are returned positionally, so the
    # published row order still follows ``registry.all()`` and does not depend on which
    # upstream answered first.
    # INVARIANT (OME-1026 F2, user-facing budget): concurrency removed
    # ``N * timeout`` but a cold request still waited for the SLOWEST provider — and a
    # provider's own aggregate refresh deadline (OpenRouter's is 10 s) is not this
    # route's budget. Each provider is now waited for at most ``budget_s``, after which
    # its refresh keeps running in the background and this listing serves seeds.
    """
    if catalog is None or runtime is None or refreshes is None:
        return [None] * len(plugins)
    # WHY the configured dial timeout is CLAMPED and not read raw (F2):
    # ``AIGW_DISCOVERY_TIMEOUT_SECONDS`` is the operator's per-dial deadline and accepts
    # any positive value, so reading it directly made the 3-second user-facing budget
    # merely its DEFAULT — an operator who raised it to 30 for a paginating provider
    # would let every listing hang for 30 s. ``user_wait_budget`` keeps the single knob
    # and makes 3 s a ceiling.
    # INVARIANT: the clamp bounds the WAIT, never the WORK. ``runtime.limits`` is passed
    # through untouched, so the refresh this request may abandon still dials with the
    # operator's full configured timeout and publishes for the next caller.
    budget_s = user_wait_budget(runtime.limits.timeout_s)
    outcomes = await asyncio.gather(
        *(
            catalog.entries_within(
                plugin,
                client=runtime.client,
                limits=runtime.limits,
                refreshes=refreshes,
                budget_s=budget_s,
            )
            for plugin in plugins
        ),
        return_exceptions=True,
    )
    listings: list[tuple[ModelEntry, ...] | None] = []
    for outcome in outcomes:
        if isinstance(outcome, DiscoveryError):
            # Defense in depth only: the catalog maps refresh failures to None itself.
            listings.append(None)
        elif isinstance(outcome, BaseException):
            # INVARIANT: anything else — AssertionError from the suite's no-egress
            # tripwire above all — must PROPAGATE. Swallowing a programming error here
            # would silently pin the listing to seeds forever and let a test that
            # really reached the internet pass green.
            raise outcome
        else:
            listings.append(outcome)
    return listings
