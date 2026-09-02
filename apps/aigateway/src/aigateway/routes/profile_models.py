"""OME-1026 — ``GET /v1/auth/{provider}/profiles/{name}/models``: one profile's own catalog.

FEATURE: the private model list. A profile owner asks what their OWN stored
credential can call and gets a live answer, labelled with how fresh it is, without
re-entering the key.

STORY: as an account owner who stored an Anthropic API key, I open my profile and
see the models that key may call — and no one else can see that list.

INVARIANT (ownership): the profile is resolved from ``CurrentAccount``, so the
account id in the lookup is the CALLER's. There is no code path here that reaches
another account's row — an admin or another tenant asking for the same profile
name gets its own answer or a 404, never these rows.

INVARIANT (never an outage): a credential the upstream rejects, a slow catalog and
a provider with no private discovery all answer 200 with the compiled seeds plus a
sanitized ``status``/``reason``. The endpoint's job is to DESCRIBE the listing; a
5xx here would make a polling UI look broken and would hide the catalog the owner
can still use.

AIDEV-NOTE: this lives outside ``routes/auth.py`` deliberately — that module is
already far past the repository's file-size limit, and this is an independent
responsibility. It reuses ``model_row`` so a private row is shaped exactly like a
public one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request

from ..core.auth.middleware import CurrentAccount
from ..core.model_capabilities import model_row
from ..core.model_discovery_scope import ProviderAuthContext
from ..core.profile_models import credential_name_for
from .private_cache import private_cache_route

if TYPE_CHECKING:
    from ..core.plugin_base import ModelEntry
    from ..core.profile_models import AuthType, Profile

# INVARIANT (F1): the private cache policy is installed as the ROUTE CLASS, so it
# covers every response this route can produce — including the 401/403 that
# ``CurrentAccount`` raises while FastAPI is SOLVING dependencies, which never reach
# the handler below. See ``routes/private_cache.py`` for why that boundary is the only
# one inside the app that sees both outcomes.
router = APIRouter(route_class=private_cache_route())


@router.get("/v1/auth/{provider}/profiles/{name}/models")
async def list_profile_models(
    provider: str, name: str, request: Request, current: CurrentAccount
) -> dict:
    """The models THIS profile's credential can call, plus how fresh that answer is.

    ``status`` is one of ``fresh`` (live), ``stale`` (last-good, refreshing behind
    this response), ``refreshing`` (no snapshot yet; one is being fetched) or
    ``fallback`` (no live listing — ``data`` is the provider's compiled catalog).
    ``reason`` is a sanitized code, never upstream text.

    The cache policy is the ROUTE CLASS's, not this function's; ``_listing`` does the
    work and may raise ``HTTPException`` freely.
    """
    return await _listing(request, provider=provider, name=name, account_id=str(current.id))


async def _listing(request: Request, *, provider: str, name: str, account_id: str) -> dict:
    """Resolve the profile and compose its listing, or raise ``HTTPException``."""
    plugin = request.app.state.providers.get(provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": provider}
        )
    # ONE index read for both values (OME-1026 F3): reading the index decrypts a
    # credential blob, and the cache identity needs the durable credential generation
    # alongside the profile itself.
    found = await request.app.state.profile_index.get_with_credential_generation(
        account_id, provider, name
    )
    if found is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "profile_not_found", "provider": provider, "name": name},
        )
    profile, credential_generation = found

    catalog = getattr(request.app.state, "profile_model_catalog", None)
    runtime = request.app.state.discovery_runtime
    if catalog is None or runtime is None:
        # The discovery kill switch. Reported as an ordinary refusal so one flag
        # audits to zero discovery egress without changing this contract's shape.
        return _payload(plugin, provider, name, "fallback", None, "discovery_disabled")

    snapshot = await catalog.snapshot_for(
        plugin,
        account_id=account_id,
        profile=profile,
        client=runtime.client,
        limits=runtime.limits,
        auth_provider=auth_provider_for(request.app, plugin, account_id, profile),
        credential_generation=credential_generation,
    )
    return _payload(plugin, provider, name, snapshot.status, snapshot.entries, snapshot.reason)


def _payload(
    plugin: Any,
    provider: str,
    name: str,
    status: str,
    entries: tuple[ModelEntry, ...] | None,
    reason: str | None,
) -> dict:
    # INVARIANT: ``entries is None`` means "no live listing" — the compiled seeds are
    # the honest answer, and they are what the owner can still use. Mirrors exactly
    # what /v1/models does for a degraded public provider.
    rows = entries if entries is not None else plugin.register_models()
    return {
        "object": "list",
        "provider": provider,
        "profile": name,
        "status": status,
        "reason": reason,
        "data": [model_row(plugin, entry) for entry in rows],
    }


def auth_provider_for(app: Any, plugin: Any, account_id: str, profile: Profile):
    """The deferred auth provider for a bare Profile (see ``deferred_auth_provider``)."""
    return deferred_auth_provider(
        app,
        plugin,
        credential_name=credential_name_for(account_id, profile.name),
        auth_type=profile.auth_type,
    )


def deferred_auth_provider(app: Any, plugin: Any, *, credential_name: str, auth_type: AuthType):
    """A callable the catalog invokes ONLY when a dial is actually about to happen.

    Public because the api-key publication path (``routes.auth``) and the implicit
    ``/v1/models`` composition (OME-1026 U3) start the same discovery, and one builder
    means one place where a credential is read. ``credential_name`` is the effective
    credential's blob slot — a Profile's composite name or a Connection's key — so
    hosted and local backings share this ONE decrypt path.

    # WHY a callable rather than a prepared header mapping: building it eagerly would
    # decrypt this credential on every request, including the ones answered from
    # cache and the ones refused outright. Deferring it means a warm cache, a
    # gated-off provider and an unsupported auth type all cost zero credential reads.
    """

    async def _build() -> ProviderAuthContext:
        strategy = plugin.discovery_credential_strategy_for(
            credential_name,
            credential_store=app.state.credential_store,
        )
        if strategy is None:
            # The provider declared private discovery but offers no credential path.
            # An empty context makes the catalog fail closed (``missing_credential``)
            # rather than dial unauthenticated.
            return ProviderAuthContext(headers={}, auth_type=auth_type)
        headers = await strategy.get_authorization_header()
        return ProviderAuthContext(headers=headers, auth_type=auth_type)

    return _build
