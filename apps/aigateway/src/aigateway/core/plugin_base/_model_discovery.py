"""OME-1026 — the provider-side MODEL-LIST discovery contract.

FEATURE: live model discovery, declared by the provider. Six hooks answer "is there
a live listing, who may see it, how fresh must it be, how is it fetched, and with
whose credential" — the whole provider-owned half of ``GET /v1/models`` and of a
profile's private listing.

INVARIANT (declare before dialing): scope, source and the unsupported-auth-type
reason are all answered with NO credential read and NO egress, so core can decide
which machinery runs — and refuse — before anything is spent.

INVARIANT (public means no credential was used): a ``PUBLIC_GLOBAL`` snapshot is
shared by every account, so the public hook receives no credential of any kind. A
catalog that needs authentication belongs in ``PROFILE_CREDENTIAL`` scope, whose
snapshot is cached per profile and served only to its owner.

AIDEV-NOTE: a MIXIN here, unlike the chat-parameter contract, which is a subclass of
``ProviderPluginCore`` because its defaults read sibling capability declarations
(see ``._provider``). Every default below is self-contained — ``None`` or
``DiscoveryScope.NONE`` — so nothing has to be redeclared and there is no pair of
definitions that could drift. Splitting this out keeps ``._contract`` within the
repository's 450-line limit by RESPONSIBILITY rather than by line count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

# Runtime import: ``DiscoveryScope.NONE`` is RETURNED by the default
# ``model_discovery_scope`` below, not merely annotated. Safe — the scope module is
# leaf vocabulary (dataclass + enum) and imports nothing that reaches plugin_base.
from ..model_discovery_scope import DiscoveryScope

if TYPE_CHECKING:
    from ..credential_blob.store import CredentialBlobStore
    from ..model_discovery_scope import ProviderAuthContext
    from ..parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from ..profile_models import AuthType
    from ._ports import CredentialStrategy, ModelEntry


@dataclass(frozen=True)
class ModelDiscoverySource:
    """Identity + cache policy of a provider's live MODEL-LIST source (OME-972).

    # WHY a separate type from ``DiscoverySourceRef``: the model list is one
    # process-local cached document per provider, shared across accounts, so
    # its policy (how fresh the LISTING must be) is provider knowledge and rides
    # on the declaration —
    # parameter evidence keys per model and takes its policy from app settings.
    # INVARIANT: declared BEFORE any fetch, like every discovery source ref —
    # the cache judges a stored snapshot by this ``revision`` without dialing.
    """

    key: str
    revision: str
    ttl_s: float
    stale_ttl_s: float
    failure_ttl_s: float


class ModelDiscoveryContract:
    """The provider hooks that describe and fetch a live model LISTING.

    Mixed into ``ProviderPluginBase``; every default declines discovery, so a
    provider opts in by overriding, never by remembering to opt out.
    """

    def model_discovery_scope(self) -> DiscoveryScope:
        """WHO this provider's live listing may be shown to (OME-1026).

        Declared before any fetch, and it decides which machinery runs:

        - ``PUBLIC_GLOBAL`` — ``ModelCatalog`` caches ONE snapshot per provider and
          ``GET /v1/models`` publishes it to every account. The fetch carries no
          credential. Implement ``discover_live_models``.
        - ``PROFILE_CREDENTIAL`` — ``ProfileModelCatalog`` caches one PRIVATE
          snapshot per authenticated profile, fetched with that profile's own
          stored credential and served only to its owner. Implement
          ``discover_profile_models``.
        - ``NONE`` (default) — ``register_models()`` seeds are the whole listing.

        INVARIANT: a ``PROFILE_CREDENTIAL`` provider is REFUSED by the global
        catalog even if it also declares a ``model_discovery_source``. One
        account's entitlements must never become the deployment's listing.

        AIDEV-NOTE: adding a provider here is a TRUST decision, not a wiring one.
        Public means "no credential was used to fetch it", not merely "no
        credential was needed".
        """
        return DiscoveryScope.NONE

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        """Identity + cache policy of this provider's live model-LIST source (OME-972).

        The listing sibling of ``chat_discovery_source``: one cached document
        declared before any fetch, so the catalog can trust or expire a stored
        snapshot without dialing. For ``PUBLIC_GLOBAL`` that document is one
        process-local snapshot shared across accounts; for ``PROFILE_CREDENTIAL``
        this supplies the TTL/stale/damping policy and the revision, while the
        private catalog scopes the identity per profile.

        INVARIANT: returning a source commits the provider to answering
        ``discover_live_models`` with entries or a sanitized ``DiscoveryError`` —
        a ``None`` there is an inconsistency the catalog fails the attempt on
        rather than caching (the same rule ``DiscoveryRuntime.observe`` enforces).

        Default: None — no live model-list discovery; ``register_models()`` seeds
        are the provider's whole listing.
        """
        return None

    async def discover_live_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
    ) -> tuple[ModelEntry, ...] | None:
        """This provider's complete PUBLIC live LISTING (``PUBLIC_GLOBAL`` scope).

        Returns ready ``ModelEntry`` rows (the provider owns its own merge of
        explicitly configured operator models with discovered ids), fetched
        through the INJECTED bounded transport — never a raw client, never a
        caller-supplied URL. Never runs on the chat dispatch path, and never
        changes what is dispatchable — only what is listed.

        INVARIANT (credentials, OME-1026): NO credential of any kind reaches this
        hook — not an account key, not an OAuth token, and not a deployment key.
        One snapshot serves every account, so any credential would publish one
        party's entitlements to all of them. A provider whose catalog requires
        authentication belongs in ``PROFILE_CREDENTIAL`` scope and implements
        ``discover_profile_models`` instead.

        INVARIANT (three outcomes, same contract as
        ``discover_chat_parameter_snapshot``): entries = the source was reached;
        raises sanitized ``DiscoveryError`` = attempted and FAILED (the catalog
        maps this to stale/fallback); ``None`` = NOT attempted, no connection.

        AIDEV-NOTE: ``None`` must not be widened to cover failure — the cache
        stores every normal return as a successful refresh, so a ``None``
        returned for a failure would be stored labelled fresh and evict the last
        good listing. ``ModelCatalog`` converts an inconsistent None into a
        failed attempt for exactly this reason.
        """
        return None

    def profile_discovery_unsupported_reason(self, *, auth_type: AuthType) -> str | None:
        """Why this profile's auth type cannot do private discovery — or ``None``.

        Consulted BEFORE any credential is read and before any dial, so an
        unsupported auth type costs exactly ZERO egress. The returned string is a
        sanitized, stable code surfaced to the profile's owner (e.g.
        ``"unsupported_auth_type"``) — never upstream text, never anything
        credential-derived.

        # WHY a predicate rather than letting the fetch fail: "we did not try, and
        # here is why" is a different product state from "we tried and it broke".
        # Anthropic's Models API is only verified for API keys, so a Claude
        # subscription OAuth profile must fall back to seeds with an honest reason
        # instead of spending a request to discover a 401.

        Default: ``None`` — a provider in ``PROFILE_CREDENTIAL`` scope supports
        every auth type it can build a credential strategy for.
        """
        return None

    async def discover_profile_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth: ProviderAuthContext,
    ) -> tuple[ModelEntry, ...] | None:
        """This profile's PRIVATE live listing (``PROFILE_CREDENTIAL`` scope).

        ``auth`` carries provider auth headers already built by the profile's own
        credential strategy — the provider never reads a stored key itself and core
        never sees plaintext. The provider decides which of its OWN header names
        are allowed onto the wire; it must not forward the mapping unfiltered.

        INVARIANT (blast radius): the returned rows describe ONE account's
        entitlements. They are cached under that profile's private identity and
        served only to its owner. Returning them from ``discover_live_models``
        instead would publish them deployment-wide.

        Three outcomes, identical to the public hook: entries = reached; raises
        sanitized ``DiscoveryError`` = attempted and FAILED; ``None`` = NOT
        attempted, no connection opened.

        Default: None — the provider declares no private discovery.
        """
        return None

    def discovery_credential_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> CredentialStrategy | None:
        """The strategy whose headers authenticate a CATALOG dial for this profile.

        Returns ``None`` when the provider has no private discovery credential path
        — the private catalog then reports ``fallback`` and dials nothing.

        # WHY this is a separate hook rather than reusing the chat/auth strategy:
        # the header PROJECTION can differ. Anthropic's chat path emits
        # ``Authorization: Bearer`` because LiteLLM re-maps it before the wire, while
        # its REST catalog authenticates a raw key with ``x-api-key``. Same stored
        # blob, same encrypted store — only the projection differs, so the provider
        # owns the choice.
        # INVARIANT: whatever is returned must read its secret through the credential
        # store, keeping that store the ONLY component that decrypts. Core receives
        # headers, never key material.

        Default: ``None``.
        """
        return None
