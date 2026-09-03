"""The provider-plugin base: auth, model registration, and dispatch.

FEATURE: everything a plugin does OTHER than describe its chat-parameter
contract — contributing models, producing credentials, exchanging OAuth codes,
mounting auth routes, and dispatching a completion.

AIDEV-NOTE: this is the LOWER half of ``ProviderPluginBase``, not a second port.
Plugins subclass ``ProviderPluginBase`` (in ``._contract``), which extends this
class; nothing subclasses ``ProviderPluginCore`` directly, and it is deliberately
NOT re-exported from the package. The two halves exist only to keep each file
within the repository's 450-line limit.

WHY the contract half is the SUBCLASS rather than a sibling mixin: its
derivations READ the capability declarations defined here —
``available_auth_modes`` calls ``supports_api_key`` and ``oauth_config``, and
``chat_transport_capabilities`` calls ``supports_chat_streaming``. A mixin would
have to redeclare all three, giving every one of those defaults two definitions
that could drift apart. Inheritance resolves them with none.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar, cast

from ..api_key_validation import ApiKeyValidator
from ..cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from ._ports import (
    CredentialStrategy,
    ModelAdmission,
    ModelEntry,
    OAuthCodeExchangeRequest,
    OAuthConfig,
    PluginSettings,
)

if TYPE_CHECKING:
    from ..credential_blob.store import CredentialBlobStore
    from ..oauth.identity import AccountIdentity
    from ..parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from ..profile_index import ProfileIndexStore
    from ..profile_models import AuthMode, AuthType


class ProviderPluginCore[TSettings: PluginSettings](ABC):
    """The auth, model-registration and dispatch half of the plugin contract.

    Not a port of its own: see the module docstring. ``ProviderPluginBase``
    extends this class and is the name every plugin subclasses.
    """

    custom_llm_provider: str
    provider_display_name: str
    settings_cls: ClassVar[type[PluginSettings]] = PluginSettings

    def __init__(self, settings: TSettings | None = None) -> None:
        self.settings = settings if settings is not None else cast(TSettings, self.settings_cls())

    @abstractmethod
    def register_models(self) -> list[ModelEntry]:
        """Return the model_list entries this plugin contributes."""

    async def admit_model(
        self,
        model_id: str,
        *,
        discovery_client: DiscoveryHttpClient | None,
        discovery_limits: DiscoveryLimits | None,
        catalog_cache: dict[str, Any],
        credentialed: bool,
    ) -> ModelAdmission:
        """Decide whether ``model_id`` may join the served catalog at runtime (OME-879).

        The default answer is a refusal: dynamic admission is opt-in per
        provider, and only a provider with an authoritative public catalog to
        validate against (OpenRouter today) overrides this.

        Args: ``discovery_client``/``discovery_limits`` are the bounded
        discovery transport (``None`` when discovery is disabled);
        ``catalog_cache`` is app-owned mutable scratch the provider may use to
        TTL-cache its catalog; ``credentialed`` says whether the CALLING account
        holds a usable credential for this provider — the route resolves it,
        because credential scoping is account+profile shaped and lives in core.
        Returns a ``ModelAdmission`` — never raises for a refusal.
        """
        del model_id, discovery_client, discovery_limits, catalog_cache, credentialed
        return ModelAdmission.refused(
            "dynamic_admission_unsupported",
            f"provider {self.custom_llm_provider!r} does not support dynamic model admission",
        )

    def conformance_models(self) -> list[ModelEntry]:
        """Return deterministic model representatives for contract conformance.

        The default is the production catalog. Providers whose catalog requires a
        live local process may override with test-only representatives; runtime
        registration and route validation must continue to call ``register_models``.
        """
        return self.register_models()

    def oauth_config(self) -> OAuthConfig | None:
        """Return provider OAuth metadata, or None for no-auth providers (e.g. local Ollama)."""
        return None

    def oauth_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
        http_client_factory: Any | None = None,
    ) -> CredentialStrategy | None:
        """Return a per-profile OAuth strategy. Default: no auth."""
        return None

    def api_key_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> CredentialStrategy | None:
        """Return a per-profile API-key strategy, or None when the provider
        does not support API-key auth (e.g. codex subscription endpoints)."""
        return None

    def api_key_validator(self) -> ApiKeyValidator | None:
        """Return an operational API-key validator, or None when unavailable."""
        return None

    def credential_strategy_for(
        self,
        profile_name: str,
        *,
        auth_type: AuthType = "oauth",
        credential_store: CredentialBlobStore | None = None,
        http_client_factory: Any | None = None,
    ) -> CredentialStrategy | None:
        """Resolve the credential strategy for ``profile_name`` by auth type."""
        if auth_type == "api_key":
            return self.api_key_strategy_for(profile_name, credential_store=credential_store)
        return self.oauth_strategy_for(
            profile_name,
            credential_store=credential_store,
            http_client_factory=http_client_factory,
        )

    async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict[str, Any]:
        """Exchange an OAuth authorization code for provider credentials."""
        raise NotImplementedError(f"{self.custom_llm_provider} does not exchange OAuth codes")

    def account_label_from_credentials(self, _credentials: dict[str, Any]) -> str | None:
        """Return a display label for credentials persisted after OAuth, if available."""
        return None

    def credential_service_provider(self) -> str:
        """Return the provider namespace used in persisted credential service keys."""
        return self.custom_llm_provider

    async def extract_identity(
        self,
        _credentials: dict[str, Any],
        *,
        http_client_factory: Any | None = None,
    ) -> AccountIdentity | None:
        """Return stable account identity from provider credentials when available."""
        return None

    def requires_oauth_connection_label(self) -> bool:
        """Whether first-class OAuth connection creation needs a user label up front."""
        return False

    def supports_chat_streaming(self) -> bool:
        """Whether `/v1/chat/completions` may create a streaming response."""
        return True

    def supports_api_key(self) -> bool:
        """Whether this provider accepts a raw API key (vs OAuth-only).

        Capability flag surfaced to clients so the UI only offers API-key auth
        where it works. The default is False; providers that implement
        ``api_key_strategy_for`` override this to True. Codex stays False (its
        subscription endpoint is OAuth-only and rejects raw keys)."""
        return False

    def strip_provider_dispatch_controls(self, body: dict[str, Any]) -> dict[str, Any]:
        """Remove caller-supplied LiteLLM control-plane fields THIS provider owns.

        # WHY: the global ``strip_dispatch_controls`` covers provider-neutral
        # control fields; a provider that dispatches through a shared LiteLLM
        # surface (e.g. OpenRouter) may also expose orchestration selectors
        # (caching/guardrails/prompt-management/named-credential) that are not
        # model parameters. Those must be neutralized BEFORE the OME-479
        # fail-closed classifier runs, so the classifier only ever adjudicates
        # genuine model-parameter candidates — plan §4.5 tier (a): transport /
        # gateway-owned fields are authorized structurally, not via a rule.
        # INVARIANT: the returned body carries no field this provider will refuse
        # to forward; the strip is idempotent (``prepare_chat_body`` may repeat it
        # as defense in depth). Default: identity — a provider opts in by override.
        """
        return body

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Apply provider-specific request normalization before dispatch."""
        return body

    def global_cache_projection(self, body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        """This provider's PURE view of the output-affecting call it would send.

        FEATURE (OME-305): one global exact-request cache. The gateway can hash the
        caller's explicit request on its own, but only the provider knows what IT
        adds — a resolved model snapshot, a normalized routing policy, a mandatory
        strictness flag. Two callers may share one cached response only when that
        provider-side contribution is identical too, so it must be part of the key.

        Return a closed mapping::

            {"resolved_model": str, "provider_adapter_revision": str, "prepared": dict}

        ``prepared`` carries every output-affecting field this provider will add or
        rewrite, in a deterministic normalized form. ``provider_adapter_revision``
        is bumped whenever that preparation changes without the caller's request
        changing, which abandons entries built under the old behaviour.

        INVARIANT (this is the whole reason the port exists): PURE. Synchronous, no
        I/O, no clock, no randomness, no counter, no cache lookup — and it receives
        the request body ALONE, so no account, profile, user, auth mode or
        credential can reach a globally shared key. A provider that cannot describe
        itself under those terms returns ``CacheBypass``.

        INVARIANT: it must never mutate ``body``; the core passes a deep copy as
        defence in depth, not as permission.

        INVARIANT (ruling 34) — what ``provider_adapter_revision`` does NOT cover.
        The revision handles variation ACROSS revisions: you changed what this boundary
        sends, so every entry built under the old behaviour is abandoned. It cannot
        handle variation WITHIN one deployment at a FIXED revision on state the
        projection cannot observe. If what you dispatch depends on something absent
        from ``body`` — a credential kind, an environment variable, a flag evaluated at
        dispatch, a per-instance cache — then two requests identical in ``body`` produce
        one key and two different upstream calls, and the cache will serve one caller
        the other's answer. Bumping the revision does not help: both variants bump
        together. There are exactly two correct answers. Either return ``CacheBypass``,
        or make the unobservable variation IRRELEVANT to the key and say so in writing
        — which means folding the shaping constants into the revision unconditionally
        and accepting that both variants share an entry, as a documented consequence.

        INVARIANT (ruling 36) — credential-gated transforms default to ``CacheBypass``.
        A transform that runs at dispatch time from credential material is the common
        case of the above, and the port is structurally incapable of keying it: the
        projection never receives a credential, by design, because a credential in a
        globally shared key is the thing this whole feature must never do. So a
        provider whose outbound body changes shape according to which KIND of
        credential is present cannot key that difference, and must bypass unless it can
        argue the difference does not affect the answer.

        The worked example is the Anthropic plugin. Its Claude-Code attribution block
        is added only for an OAuth subscription token, decided at dispatch from
        ``body["api_key"]``. It does NOT bypass; it folds every constant that shapes the
        block into its revision unconditionally and accepts the cross-credential share,
        on the stated grounds that the block is attribution rather than instruction, is
        derived from already-keyed ``messages``, and that a MISS still dispatches under
        the caller's own real credential. Read that plugin's docstring before copying
        the pattern — the accepted consequence is what makes it legitimate, and an
        unstated one is just a bug.

        Default: ``CacheBypass`` — fail safe. A provider is cacheable only by
        deliberately implementing this hook, never by inheriting a guess about what
        ``prepare_chat_body`` does.

        WHY an operator gate must NOT be expressed here: see
        ``participates_in_global_cache``. Reading ``self.settings`` from this method
        breaks the purity contract above, and the two decisions are genuinely
        different — this one describes WHAT would be sent, that one whether this
        provider may take part at all.
        """
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)

    def participates_in_global_cache(self, model: object = None) -> bool:
        """Whether this provider may take part in the shared cache at all.

        ``model`` is the RAW requested model, exactly as the caller sent it — not a
        resolved, stripped or validated form, and possibly not even a string, because
        this gate is consulted before the request's shape is adjudicated. It is the ONE
        request fact this port carries (OME-884), and it exists for a hazard that is
        per-model rather than per-deployment: an ambient ``litellm.model_alias_map``
        entry REDIRECTS one model id to another, so a row stored for the requested id
        would be replayed while a miss dispatched something else. A model-free gate
        could only answer that by disabling the whole provider, which would abandon
        every unrelated model's cache over one poisoned alias.

        INVARIANT: nothing ELSE crosses this port. No body, no account, no profile, no
        auth mode, no credential, no settings instance — this hook may read
        deployment-local state, but the request itself reaches it only as this one id.

        AIDEV-NOTE: the parameter is DEFAULTED so the hook stays callable in isolation
        (``plugin.participates_in_global_cache()`` in a test, a direct base-class call).
        ``build_global_cache_plan`` always passes it; ``None`` therefore means "no model
        was available", never "the caller sent none".

        WHY this is separate from ``global_cache_projection`` rather than a branch
        inside it: the two answer different questions, and only one of them may see
        operator configuration.

        - The PROJECTION decides KEY MATERIAL. It is contractually a pure function of
          the request body, so that the same request keys identically in every
          deployment. A per-deployment key would partition a shared cache, or worse
          let two deployments agree on a key while disagreeing on what gets dispatched
          (``test_no_projection_reads_operator_configuration`` is the tripwire).
        - This hook decides PARTICIPATION. Returning False removes the provider from
          the cache entirely — no read, no write — which is deployment-local by nature
          and cannot affect any key. Flipping it must leave every stored row exactly as
          it was, so that re-enabling the provider finds its cache intact.

        INVARIANT: a False answer is FAIL-SAFE and lossless. It suppresses the lookup;
        it never invalidates, rewrites or re-keys an entry.

        AIDEV-NOTE: an operator kill switch has to be checked HERE and not left to the
        dispatch-side guards, because the cache stage runs before model resolution and
        before credentials are read. A provider that registers no models and yields no
        credential strategy can still have its stored rows replayed — that was a real
        defect in OpenRouter (observed: a 200 with ``X-AIGW-Cache: hit`` from a
        switched-off provider), not a hypothetical.

        Default: True — a provider that has implemented a projection participates.
        Overriding is only for a provider that can be switched off, or that has a
        per-model reason to stand down.
        """
        del model
        return True

    def should_apply_profile_default(self, field: str) -> bool:
        """Return whether a profile default field should be merged into chat bodies."""
        return True

    def allows_chatless_profile(self) -> bool:
        """Whether chat may proceed when no gateway OAuth profile exists."""
        return False

    def profileless_auth_mode(self) -> AuthMode | None:
        """Return the runtime-selected auth mode when no stored target exists."""
        return None

    def invalidate_profile_session(self, _profile_name: str) -> None:
        """Drop provider-owned per-profile chat/session cache, if any."""
        return None

    def should_mark_profile_error_on_dispatch_status(self, _status_code: int) -> bool:
        """Whether a provider dispatch failure means stored profile auth is unusable."""
        return False

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        """Dispatch a normalized OpenAI-compatible chat completion request."""
        import litellm

        return await litellm.acompletion(**body)

    async def chat_completion_stream(self, body: dict[str, Any]) -> AsyncIterator[Any]:
        """Dispatch a normalized streaming chat completion request."""
        import litellm

        stream: Any = await litellm.acompletion(**body)
        async for chunk in stream:
            yield chunk

    def auth_router(self):
        """Provider-specific auth routes.

        Handlers should require `CurrentAccount` unless they are OAuth callback
        targets protected by a pending-auth state nonce.
        """
        return None

    async def bootstrap_profiles(
        self,
        *,
        account_id: str,
        credential_store: CredentialBlobStore | None = None,
        index_store: ProfileIndexStore | None = None,
    ) -> None:
        """Populate provider-owned profile metadata at startup, if any."""
        return None
