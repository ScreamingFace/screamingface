from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

from ..core.auth.middleware import CurrentAccount
from ..core.discovery_budget import user_wait_budget
from ..core.effective_credential import EffectiveCredential, resolve_effective_credential
from ..core.model_capabilities import model_row
from ..core.model_discovery_scope import DiscoveryScope, discovery_scope_of
from ..core.parameter_discovery import DiscoveryError
from .chat_credentials import _oauth_connection_store
from .private_cache import private_cache_route
from .profile_models import deferred_auth_provider

if TYPE_CHECKING:
    from ..core.plugin_base import ModelEntry

# INVARIANT (OME-1026 U3): every ``/v1/models`` response is account-scoped — the body
# may carry the caller's credential-derived rows — so the private cache policy rides
# the ROUTE CLASS, covering the 401/403 raised while dependencies are being solved
# exactly as it does for the explicit profile listing endpoint.
router = APIRouter(route_class=private_cache_route())


@router.get("/v1/models")
async def list_models(request: Request, current: CurrentAccount) -> dict:
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

    OME-1026 U3 (implicit effective credential): a PROFILE_CREDENTIAL provider's
    listing is the CALLER's own — resolved through the account's one effective
    credential (hosted: the Profile named ``default``; local: the sole active
    Connection) and served from the revision-keyed private catalog. Every
    non-resolving outcome keeps the compiled seeds with zero provider egress, and
    no credential-derived row ever enters a deployment-global cache or another
    account's response.
    """
    registry = request.app.state.providers
    plugins = list(registry.all())
    listings = await _all_listings(request, plugins, account_id=str(current.id))
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


async def _all_listings(
    request: Request, plugins: list[Any], *, account_id: str
) -> list[tuple[ModelEntry, ...] | None]:
    """Every plugin's listing (or ``None`` for seeds), public AND private, in one wait.

    # INVARIANT (deterministic order): results are reassembled positionally, so the
    # published row order still follows ``registry.all()`` and does not depend on
    # which scope or upstream answered first.
    # INVARIANT (one concurrent wave): the public composition and every private
    # snapshot are awaited in a single gather, so a credential-scoped provider joins
    # the same wait the public providers share instead of serializing after them.
    """
    app = request.app
    is_private = [
        discovery_scope_of(plugin) is DiscoveryScope.PROFILE_CREDENTIAL for plugin in plugins
    ]
    public_plugins = [p for p, private in zip(plugins, is_private, strict=True) if not private]
    private_plugins = [p for p, private in zip(plugins, is_private, strict=True) if private]
    public_results, private_outcomes = await asyncio.gather(
        _live_listings(
            public_plugins,
            catalog=app.state.model_catalog,
            runtime=app.state.discovery_runtime,
            refreshes=app.state.public_refreshes,
        ),
        asyncio.gather(
            *(
                _private_listing(request, plugin, account_id=account_id)
                for plugin in private_plugins
            ),
            return_exceptions=True,
        ),
    )
    private_results = _listings_from(private_outcomes)
    public_iter = iter(public_results)
    private_iter = iter(private_results)
    return [next(private_iter) if private else next(public_iter) for private in is_private]


async def _private_listing(
    request: Request, plugin: Any, *, account_id: str
) -> tuple[ModelEntry, ...] | None:
    """The CALLER's credential-scoped listing, or ``None`` for the compiled seeds.

    # INVARIANT (OME-1026): only an unambiguous, resolved effective credential funds
    # discovery. No credential, an ambiguous set of local Connections and an unknown
    # label all return ``None`` — seeds — with ZERO provider egress; the refusal
    # gates inside the private catalog (unauthenticated, unsupported auth type,
    # gated off) additionally decrypt nothing.
    # INVARIANT (isolation): the snapshot identity carries the account, the logical
    # profile name and the durable credential revision, so this listing can never
    # serve another account's rows nor a replaced credential's rows — and it is
    # composed into THIS response only, never into a deployment-global cache.
    """
    app = request.app
    catalog = getattr(app.state, "profile_model_catalog", None)
    runtime = app.state.discovery_runtime
    if catalog is None or runtime is None:
        return None
    resolution = await resolve_effective_credential(
        account_id=account_id,
        provider=plugin.custom_llm_provider,
        profile_index=app.state.profile_index,
        connections=_oauth_connection_store(request),
    )
    if not isinstance(resolution, EffectiveCredential):
        return None
    snapshot = await catalog.snapshot_for_target(
        plugin,
        account_id=account_id,
        target=resolution,
        client=runtime.client,
        limits=runtime.limits,
        auth_provider=deferred_auth_provider(
            app,
            plugin,
            credential_name=resolution.credential_name,
            auth_type=resolution.auth_type,
        ),
        # WHY the same clamped budget as the public wave: the caller's wait is ONE
        # dial, not one per scope; the refresh this request may abandon keeps
        # running and publishes for the next caller.
        wait_budget_s=user_wait_budget(runtime.limits.timeout_s),
    )
    return snapshot.entries


async def _live_listings(
    plugins: list[Any],
    *,
    catalog: Any,
    runtime: Any,
    refreshes: Any,
) -> list[tuple[ModelEntry, ...] | None]:
    """Each plugin's PUBLIC live listing (or ``None`` for seeds), fetched CONCURRENTLY.

    # WHY concurrently (OME-1026): awaiting each provider in turn makes this route's
    # worst-case latency the SUM of every provider's discovery timeout, so adding a
    # provider slows the listing for all the others. Cold caches are exactly when a
    # user is most likely to be waiting.
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
    return _listings_from(outcomes)


def _listings_from(outcomes: list[Any]) -> list[tuple[ModelEntry, ...] | None]:
    listings: list[tuple[ModelEntry, ...] | None] = []
    for outcome in outcomes:
        if isinstance(outcome, DiscoveryError):
            # Defense in depth only: the catalogs map refresh failures to None themselves.
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
