"""GET /v1/model-parameters — profile-bound detailed parameter contract (OME-479).

The client sends the same gateway auth + ``X-Profile`` it will use for chat. This
route REUSES the chat credential-target resolution and derives the auth mode from
the stored profile/connection; it never accepts a caller-declared auth type,
credential, or provider origin. The provider is selected by the canonical model
prefix (a unique registry key), and the response is per-account/profile —
``private, no-store`` and varying by authorization + profile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..core.auth.middleware import CurrentAccount
from ..core.discovery_runtime import (
    AuthScopedDiscoverablePlugin,
    DiscoveryOutcome,
    DiscoveryRuntime,
    auth_scoped,
    static_discovery_outcome,
)
from ..core.model_capabilities import canonical_ids, canonical_model_id
from ..core.model_discovery_scope import DiscoveryScope, discovery_scope_of
from ..core.model_parameter_contract import build_model_parameter_document
from ..core.registry import ProviderRegistry
from .chat_credentials import _credential_target_for_chat, resolved_auth_mode
from .private_cache import private_cache_route
from .profile_models import auth_provider_for as profile_models_auth_provider

if TYPE_CHECKING:
    from ..core.oauth.models import OAuthConnection
    from ..core.plugin_base import ProviderPluginBase
    from ..core.profile_models import AuthMode, Profile

# INVARIANT (F1): the private cache policy is the ROUTE CLASS's, so it covers every
# response this route can produce — the profile-dependent 401/404/409 whose bodies
# carry the requested profile name and a profile-specific reauth URL, AND the 401/403
# that ``CurrentAccount`` raises during dependency resolution, which never reach the
# handler at all. ``X-Profile`` is named because this route's body additionally varies
# by the caller-selected profile at one unchanged URL.
router = APIRouter(route_class=private_cache_route("X-Profile"))


async def _discovery_outcome(
    request: Request,
    plugin: AuthScopedDiscoverablePlugin,
    *,
    model: str,
    auth_mode: AuthMode,
) -> DiscoveryOutcome:
    """Observe this provider's public evidence for ``model``, or report static-only.

    # INVARIANT: the runtime's transport also serves model admission (OME-879)
    # and the live model catalog (OME-972), but this helper remains the only
    # per-model OBSERVATION path. The model reaching it has already been
    # validated against the canonical inventory, so a caller cannot steer
    # discovery at an arbitrary target — and no credential is in scope: the
    # runtime reads PUBLIC catalogs only.
    # OME-632: the RESOLVED auth mode is bound here, never caller-declared. A
    # provider whose modes reach different upstreams may publish a source for one
    # and none for the other; binding at this boundary keeps that decision with the
    # provider while the runtime's own port stays auth-free.
    """
    runtime: DiscoveryRuntime | None = request.app.state.discovery_runtime
    if runtime is None:
        return static_discovery_outcome()
    return await runtime.observe(auth_scoped(plugin, auth_mode), model=model)


def _context_identity(
    account_id: str,
    profile: Profile | None,
    connection: OAuthConnection | None,
) -> str:
    """Opaque, NON-secret digest input: account + selected target + its state.

    Folded into the one-way contract/context digests so the ids change when the
    selected profile/connection or its generation/state changes. Never echoed.
    """
    if connection is not None:
        target = f"conn:{connection.id}:{connection.status}:{connection.last_refreshed_at or '-'}"
    elif profile is not None:
        target = f"prof:{profile.id}:{profile.state.value}:{profile.last_refreshed_at or '-'}"
    else:
        target = "anon"
    return f"acct:{account_id}|{target}"


async def _contract_document(request: Request, *, account_id: str, model: str) -> dict[str, Any]:
    """Resolve provider + profile and compose the contract, or raise ``HTTPException``.

    Split from the route handler so the handler is purely the HTTP policy boundary
    (``routes/private_cache.py``): every exit below — including the ones raised
    inside the shared chat credential resolution — passes through that one boundary.
    """
    provider = model.split("/", 1)[0] if "/" in model else None
    if not provider:
        raise HTTPException(status_code=400, detail="model must be provider-prefixed")

    registry: ProviderRegistry = request.app.state.providers
    plugin = registry.get(provider)
    if plugin is None:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")

    # Canonical-id lookup BEFORE any profile work: reject unknown/cross-provider
    # ids (an id owned by another plugin is simply not in this plugin's set).
    # Seeded and admitted ids resolve OFFLINE; the live catalog is consulted
    # lazily, only to rescue a would-be 404 (OME-972).
    known = {
        canonical_model_id(custom_llm_provider=provider, model_name=entry.model_name)
        for entry in plugin.register_models()
    }
    # OME-879: dynamically admitted ids resolve like seeded ones — a model the
    # gateway agreed to serve must not 404 on its own contract endpoint.
    profile_name = (request.headers.get("X-Profile") or "default").strip() or "default"
    # OME-1026 F4: set only when this request admitted the id from the caller's PRIVATE
    # snapshot, and then it is the generation that snapshot was fetched under. ``None``
    # means no private catalog was consulted, so there is no generation to mix.
    private_generation: int | None = None
    if model not in known and model not in request.app.state.admitted_models:
        # OME-972: an id published from a healthy live snapshot must resolve on
        # its own contract endpoint. Lazy by construction — a known-set hit
        # above never pays for a listing read — and served from the same
        # process-local cache the /v1/models route fills.
        # OME-1026 F4: the same promise for a PRIVATE id. The profile listing publishes
        # a ``parameter_contract_url`` on every row, so an id that exists only in this
        # caller's own credentialed snapshot must resolve here too — otherwise the
        # listing advertises a URL that 404s. Consulted SECOND: the public catalog
        # refuses a private provider outright and costs nothing for it, and a public
        # provider never reaches the private read at all.
        if model not in await _live_catalog_ids(request, plugin):
            private_ids, private_generation = await _private_catalog_ids(
                request, plugin, account_id=account_id, profile_name=profile_name
            )
            if model not in private_ids:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "model_not_found", "provider": provider, "model": model},
                )

    # Reuse the chat resolution verbatim (raises the same 404/409 on a missing/
    # pending/errored profile) so summary, detail, and dispatch agree on context.
    profile, connection, _defaults = await _credential_target_for_chat(
        request,
        account_id=account_id,
        provider=provider,
        profile_name=profile_name,
        plugin=plugin,
    )
    auth_mode = resolved_auth_mode(profile, connection, plugin=plugin)

    # Observed LAST: a request that fails profile resolution must not have spent a
    # fetch on a contract it will never serve. (The lazy catalog consult above is
    # the one earlier read, and only a would-be 404 pays for it.)
    discovered = await _discovery_outcome(request, plugin, model=model, auth_mode=auth_mode)

    # OME-629: the observed snapshot reaches the EVIDENCE argument and nothing else.
    # `rules` above is computed independently of `discovered`, so gateway.status,
    # the /v1/models summary and dispatch are identical whether this read hit a warm
    # cache, a cold one, or a degraded source — only the reported provider evidence
    # and its freshness move.
    observations = plugin.overlay_discovered_observations(
        plugin.chat_parameter_observations(model=model, auth_type=auth_mode),
        discovered.snapshot,
        stale=bool(discovered.freshness.get("stale")),
    )
    # OME-631: the SAME snapshot reaches the tools section. A tool type is named in
    # both places, so folding the evidence into only one would publish a document
    # that contradicts itself. This moves provider_support only — gateway_status,
    # and therefore the /v1/models supported_tools summary, is untouched.
    tools = plugin.overlay_discovered_tools(
        plugin.chat_parameter_tools(model=model, auth_type=auth_mode),
        discovered.snapshot,
    )

    document = build_model_parameter_document(
        canonical_id=model,
        gateway_provider=provider,
        auth_mode=auth_mode,
        scope="account_profile",
        context_identity=_context_identity(account_id, profile, connection),
        rules=plugin.chat_parameter_rules(model=model, auth_type=auth_mode),
        observations=observations,
        tools=tools,
        transport=plugin.chat_transport_capabilities(model=model, auth_type=auth_mode),
        freshness=discovered.freshness,
        # OME-647: which documents this evidence was read from, and under which
        # reading, is part of the contract's IDENTITY — so a client that pinned a
        # contract_id is not silently handed evidence with a different provenance.
        source_revision=discovered.snapshot.source_revision if discovered.snapshot else None,
    )
    if private_generation is not None:
        await _refuse_mixed_generation(
            request,
            plugin,
            account_id=account_id,
            profile_name=profile_name,
            validated_generation=private_generation,
        )
    return document


async def _refuse_mixed_generation(
    request: Request,
    plugin: ProviderPluginBase[Any],
    *,
    account_id: str,
    profile_name: str,
    validated_generation: int,
) -> None:
    """Refuse if the durable credential generation moved during THIS request.

    INVARIANT (OME-1026 F4): one request answers under ONE credential context. The id
    was admitted from a snapshot fetched under ``validated_generation``; the document
    above was built from a SECOND index read. A credential replacement committing
    between them would otherwise produce a 200 that mixed the two — admitted under the
    revoked credential, described under its replacement.

    # WHY a recheck rather than threading one resolved context through: the contract
    # path deliberately reuses the chat credential resolution verbatim, so summary,
    # detail and dispatch cannot drift. Passing a pre-resolved profile into it would
    # fork that shared path — the very drift the reuse exists to prevent — while this
    # adds one index read on the RESCUE path only, for PROFILE_CREDENTIAL providers
    # only. A seeded or admitted id pays nothing.
    # WHY 409 and not a silent retry here: the retry would need its own bound and could
    # be defeated by a caller rotating in a loop. A refusal names the condition, is
    # safe to repeat, and leaves the choice with the client.
    # INVARIANT (sanitized): a code plus the caller's OWN provider/profile names. Never
    # key material, a generation number, or upstream text.
    """
    found = await request.app.state.profile_index.get_with_credential_generation(
        account_id, plugin.custom_llm_provider, profile_name
    )
    if found is not None and found[1] == validated_generation:
        return
    # ``found is None`` lands here too: a profile deleted mid-request has no generation
    # at all, and a document validated against its snapshot is exactly as wrong as one
    # validated against a replaced credential.
    raise HTTPException(
        status_code=409,
        detail={
            "code": "credential_generation_changed",
            "provider": plugin.custom_llm_provider,
            "profile": profile_name,
        },
    )


async def _live_catalog_ids(request: Request, plugin: ProviderPluginBase[Any]) -> frozenset[str]:
    """Gateway ids in the provider's live listing snapshot; empty when absent.

    # WHY empty over raising: a degraded catalog must leave the 404 verdict to
    # the offline inventory — this helper widens the known set, never gates it.
    """
    catalog = request.app.state.model_catalog
    runtime: DiscoveryRuntime | None = request.app.state.discovery_runtime
    if catalog is None or runtime is None:
        return frozenset()
    return await catalog.ids_for(plugin, client=runtime.client, limits=runtime.limits)


async def _private_catalog_ids(
    request: Request,
    plugin: ProviderPluginBase[Any],
    *,
    account_id: str,
    profile_name: str,
) -> tuple[frozenset[str], int | None]:
    """Gateway ids in the CALLER'S OWN private snapshot, and the generation used.

    The second element is the durable credential generation the snapshot was fetched
    under, or ``None`` when no private catalog was consulted. The caller fences the
    finished document on it (OME-1026 F4) so one request cannot mix two generations.

    INVARIANT (the isolation this must not break): every input is the authenticated
    caller's — ``account_id`` comes from ``CurrentAccount`` and ``profile_name`` from
    the same ``X-Profile`` header that will select the credential for dispatch. There
    is no code path here that reads another account's row or a sibling profile's
    snapshot, so a private id resolves in exactly the context that discovered it and
    is ``model_not_found`` everywhere else.

    # WHY the same ``snapshot_for`` the listing route uses, rather than a read-only
    # peek at whatever this worker happens to have cached: a cached-only lookup would
    # make the advertised URL work on the replica that served the listing and 404 on
    # its siblings, since a private snapshot is deliberately process-local. Reusing the
    # catalog keeps ONE implementation of the refusal gates, the cache identity, the
    # single-flight dedup and the capacity bound — and adds no capability: it is the
    # caller's own already-stored credential, on the path that already publishes it.
    # WHY empty over raising: like ``_live_catalog_ids``, this WIDENS the known-id set.
    # A degraded private catalog must leave the 404 verdict to the offline inventory.
    """
    catalog = getattr(request.app.state, "profile_model_catalog", None)
    runtime: DiscoveryRuntime | None = request.app.state.discovery_runtime
    if catalog is None or runtime is None:
        return frozenset(), None
    # Cheapest refusal first: a PUBLIC provider has no private catalog, and asking
    # would cost an index read that decrypts a credential blob for nothing.
    if discovery_scope_of(plugin) is not DiscoveryScope.PROFILE_CREDENTIAL:
        return frozenset(), None
    found = await request.app.state.profile_index.get_with_credential_generation(
        account_id, plugin.custom_llm_provider, profile_name
    )
    if found is None:
        # No such profile for this caller. The shared chat resolution below raises the
        # canonical 404/409 for that; this helper only declines to widen.
        return frozenset(), None
    profile, credential_generation = found
    snapshot = await catalog.snapshot_for(
        plugin,
        account_id=account_id,
        profile=profile,
        client=runtime.client,
        limits=runtime.limits,
        auth_provider=profile_models_auth_provider(request.app, plugin, account_id, profile),
        credential_generation=credential_generation,
    )
    return canonical_ids(plugin, snapshot.entries), credential_generation


@router.get("/v1/model-parameters")
async def model_parameters(
    request: Request,
    current: CurrentAccount,
    model: Annotated[str, Query()],
) -> dict[str, Any]:
    """The profile-bound detailed contract for ONE model.

    The cache policy is the ROUTE CLASS's; ``_contract_document`` does the work and
    may raise ``HTTPException`` freely.
    """
    return await _contract_document(request, account_id=str(current.id), model=model)
