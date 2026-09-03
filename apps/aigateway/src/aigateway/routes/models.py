from __future__ import annotations

from fastapi import APIRouter, Request

from ..core.auth.middleware import CurrentAccount
from ..core.model_capabilities import model_row
from ..core.parameter_discovery import DiscoveryError

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
    data: list[dict] = []
    seen: set[str] = set()
    for plugin in registry.all():
        entries = None
        if catalog is not None and runtime is not None:
            try:
                entries = await catalog.entries_for(
                    plugin, client=runtime.client, limits=runtime.limits
                )
            except DiscoveryError:
                # Defense in depth only: the catalog maps refresh failures to
                # None itself. Anything else (AssertionError included) must
                # propagate — a swallowed programming error here would silently
                # pin the listing to seeds forever.
                entries = None
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
