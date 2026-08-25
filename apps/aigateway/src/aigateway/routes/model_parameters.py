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

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..core.auth.middleware import CurrentAccount
from ..core.discovery_runtime import (
    AuthScopedDiscoverablePlugin,
    DiscoveryOutcome,
    DiscoveryRuntime,
    auth_scoped,
    static_discovery_outcome,
)
from ..core.model_capabilities import canonical_model_id
from ..core.model_parameter_contract import build_model_parameter_document
from ..core.registry import ProviderRegistry
from .chat_credentials import _credential_target_for_chat, resolved_auth_mode

if TYPE_CHECKING:
    from ..core.oauth.models import OAuthConnection
    from ..core.plugin_base import ProviderPluginBase
    from ..core.profile_models import AuthMode, Profile

router = APIRouter()


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


# INVARIANT: this policy belongs to the ROUTE, not to its happy path — EVERY
# response it produces, success or error, is per-account/profile and unshareable.
# WHY it must be applied twice: FastAPI merges the injected ``Response`` into the
# reply only on a NORMAL RETURN, while a raised ``HTTPException`` is rendered by
# ``http_exception_handler`` from the EXCEPTION's own headers. A policy set only on
# the injected response is therefore structurally invisible to every raise — and the
# raises are exactly the profile-dependent 401/404/409 whose bodies carry the
# requested profile name and a profile-specific reauth URL.
_PRIVATE_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "private, no-store",
    "Vary": "Authorization, X-Profile",
}


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
    (see ``_PRIVATE_CACHE_HEADERS``): every exit below — including the ones raised
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
    if model not in known and model not in request.app.state.admitted_models:
        # OME-972: an id published from a healthy live snapshot must resolve on
        # its own contract endpoint. Lazy by construction — a known-set hit
        # above never pays for a listing read — and served from the same
        # process-local cache the /v1/models route fills.
        if model not in await _live_catalog_ids(request, plugin):
            raise HTTPException(
                status_code=404,
                detail={"code": "model_not_found", "provider": provider, "model": model},
            )

    profile_name = (request.headers.get("X-Profile") or "default").strip() or "default"
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

    return build_model_parameter_document(
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


@router.get("/v1/model-parameters")
async def model_parameters(
    request: Request,
    response: Response,
    current: CurrentAccount,
    model: Annotated[str, Query()],
) -> dict[str, Any]:
    # Success path: the injected response is merged into the reply on return.
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    try:
        return await _contract_document(request, account_id=str(current.id), model=model)
    except HTTPException as exc:
        # AIDEV-NOTE: policy LAST in the merge. A raiser's own headers (a future
        # WWW-Authenticate / Retry-After) survive, but this route's cache policy wins
        # on the keys it owns — an error can never be emitted with a weaker cache
        # directive than the success response. Do not "simplify" this boundary away:
        # exc.headers is the ONLY channel that reaches an HTTPException response.
        exc.headers = {**(exc.headers or {}), **_PRIVATE_CACHE_HEADERS}
        raise
