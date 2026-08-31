from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any

from aigateway.core.api_key_strategy import API_KEY_AUTH_TYPE, ApiKeyStrategy
from aigateway.core.api_key_validation import ApiKeyValidator
from aigateway.core.model_discovery_scope import DiscoveryScope, ProviderAuthContext
from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
from aigateway.core.plugin_base import (
    PROJECTION_BYPASS_REASON,
    CacheBypass,
    CredentialStrategy,
    ModelDiscoverySource,
    ModelEntry,
    OAuthCodeExchangeRequest,
    OAuthConfig,
    ProviderPluginBase,
)
from aigateway.core.standard_parameters import tool_parameter_observations
from aigateway.plugins.taxonomy import (
    CacheReference,
    ProviderUsageAccountingEvidence,
    UsageAccountingStrategy,
)

from .api_key_validation import AnthropicApiKeyValidator
from .auth import AnthropicOAuth, credential_service_for, exchange_authorization_code
from .bootstrap import bootstrap_from_claude_code
from .chat_handler import (
    apply_anthropic_dispatch_controls,
    chat_completion,
    chat_completion_stream,
    claude_code_attribution_revision,
)
from .discovery import STATIC_SOURCE, anthropic_static_param_observations
from .live_models import (
    ANTHROPIC_MODELS_DISCOVERY_SOURCE,
    fetch_live_model_ids,
    live_listing_entries,
    publishable_model_ids,
)
from .parameters import anthropic_chat_parameter_rules, anthropic_chat_parameter_tools
from .settings import AnthropicPluginSettings
from .thinking import raise_on_thinking_conflict
from .usage_accounting import (
    cache_reference_from_cached,
    normalize_anthropic_usage_accounting,
)

if TYPE_CHECKING:
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderParameterObservation,
        ToolCapability,
    )
    from aigateway.core.credential_blob.store import CredentialBlobStore
    from aigateway.core.profile_index import ProfileIndexStore
    from aigateway.core.profile_models import AuthMode, AuthType


# OME-305: this provider's contribution to a global cache key. The date names the
# reviewed preparation behaviour; the suffix is COMPUTED from every constant that
# shapes the Claude-Code attribution block, so bumping the Claude Code version
# abandons entries filled under the old block without anyone remembering to.
GLOBAL_CACHE_ADAPTER_REVISION = (
    f"anthropic-global-cache-2026-08-{claude_code_attribution_revision()}"
)

_GATEWAY_MODEL_PREFIX = "anthropic/"


def _discovery_api_key_headers(api_key: str) -> dict[str, str]:
    # INVARIANT: Anthropic's REST API authenticates a raw API key with ``x-api-key``.
    # ``Authorization: Bearer`` is its OAUTH shape — sending a raw key that way 401s. The
    # chat builder below can use Bearer because LiteLLM re-maps it before the wire; a
    # direct catalog dial has no such translation layer.
    return {"x-api-key": api_key}


def _api_key_headers(api_key: str) -> dict[str, str]:
    # chat.py pops Authorization into body["api_key"]; LiteLLM then sends raw
    # (non-"sk-ant-oat") keys upstream as x-api-key, and only OAuth tokens get
    # the Bearer + oauth beta-header treatment.
    return {"Authorization": f"Bearer {api_key}"}


class AnthropicProviderPlugin(ProviderPluginBase[AnthropicPluginSettings]):
    custom_llm_provider = "anthropic"
    provider_display_name = "Anthropic"
    settings_cls = AnthropicPluginSettings

    def register_models(self) -> list[ModelEntry]:
        return list(self.settings.models)

    def model_discovery_scope(self) -> DiscoveryScope:
        # INVARIANT (OME-1026): Anthropic's catalog answers FOR THE CALLING KEY, so its
        # listing is per-account data by construction. It is therefore PRIVATE: cached
        # per authenticated profile and served only to that profile's owner. There is no
        # deployment discovery credential and no shared Anthropic snapshot.
        # AIDEV-NOTE: this plugin deliberately does NOT implement ``discover_live_models``.
        # The base default returns None, so even if something asked the shared catalog for
        # Anthropic rows, there is no code path that could produce credentialed ones.
        if not self.settings.live_models:
            return DiscoveryScope.NONE
        return DiscoveryScope.PROFILE_CREDENTIAL

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        # Supplies the private cache's POLICY (ttl / stale / damping) and revision. The
        # private identity is composed from profile OWNERSHIP data, never from this key and
        # never from the credential.
        if not self.settings.live_models:
            return None
        return ANTHROPIC_MODELS_DISCOVERY_SOURCE

    def profile_discovery_unsupported_reason(self, *, auth_type: AuthType) -> str | None:
        # INVARIANT (zero egress on unverified auth): Anthropic's Models API is verified
        # only for API keys. Claude-subscription OAuth tokens are NOT known to work with
        # /v1/models, and this has not been probed — so an OAuth profile must not spend a
        # credentialed request to find out. Refusing here, before any credential is read,
        # is what makes "OAuth profile ⇒ zero Models-API egress" true by construction
        # rather than by a 401 handler.
        if auth_type != API_KEY_AUTH_TYPE:
            return "unsupported_auth_type"
        return None

    def discovery_credential_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> CredentialStrategy:
        """The credential strategy whose headers authenticate a MODELS-API dial.

        # WHY separate from ``api_key_strategy_for``: the chat path's header builder emits
        # ``Authorization: Bearer <key>`` because LiteLLM re-maps it downstream, but
        # Anthropic's REST catalog authenticates raw keys with ``x-api-key`` — a bearer
        # token there is an OAuth credential, not an API key. Same stored blob, same
        # encrypted store, same class: only the header projection differs.
        # INVARIANT: reusing ``ApiKeyStrategy`` keeps the store the ONLY component that
        # decrypts, so neither core nor this plugin ever holds a plaintext key of its own.
        """
        return ApiKeyStrategy(
            profile_name,
            service=credential_service_for(profile_name),
            account=self.settings.keychain_account,
            header_builder=_discovery_api_key_headers,
            credential_store=credential_store,
        )

    async def discover_profile_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth: ProviderAuthContext,
    ) -> tuple[ModelEntry, ...] | None:
        """This PROFILE's finished listing: operator-explicit entries, then discovered ids.

        Three-outcome contract (see the base hook): entries = the catalog was reached;
        raises sanitized ``DiscoveryError`` = attempted and FAILED, which the private
        catalog maps to its stale-then-seeds ladder; None = gated off, no connection.
        """
        if not self.settings.live_models:
            return None
        # Defense in depth: the private catalog already consulted
        # ``profile_discovery_unsupported_reason``. Re-checking costs nothing and makes the
        # zero-egress guarantee local to the function that would otherwise do the dialing.
        if self.profile_discovery_unsupported_reason(auth_type=auth.auth_type) is not None:
            return None
        raw_ids = await fetch_live_model_ids(
            client=client,
            limits=limits,
            auth_headers=auth.headers,
            api_version=self.settings.api_version,
        )
        return live_listing_entries(self.settings, publishable_model_ids(raw_ids))

    def oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            authorize_url=self.settings.authorize_url,
            token_url=self.settings.token_url,
            client_id=self.settings.client_id,
            scopes=list(self.settings.scopes),
            redirect_path=self.settings.redirect_path,
            extra_authorize_params=dict(self.settings.authorize_extra_params),
        )

    def oauth_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
        http_client_factory: Any | None = None,
    ) -> CredentialStrategy:
        return AnthropicOAuth(
            profile_name=profile_name,
            credential_store=credential_store,
            http_client_factory=http_client_factory,
            settings=self.settings,
        )

    def supports_api_key(self) -> bool:
        return True

    def api_key_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> CredentialStrategy:
        return ApiKeyStrategy(
            profile_name,
            service=credential_service_for(profile_name),
            account=self.settings.keychain_account,
            header_builder=_api_key_headers,
            credential_store=credential_store,
        )

    def api_key_validator(self) -> ApiKeyValidator:
        return AnthropicApiKeyValidator(
            settings=self.settings,
            registered_models=self.register_models(),
        )

    def should_mark_profile_error_on_dispatch_status(self, status_code: int) -> bool:
        # Stored keys/tokens get no validation at set time (plan D6); an
        # upstream 401 after header injection means the credential is bad, so
        # flip the target to ERROR like gemini does (SF-244 audit F14).
        return status_code == 401

    def should_apply_profile_default(self, field: str) -> bool:
        # The legacy SF Claude backend ignored default_effort. Applying it as a
        # gateway profile default enables Anthropic thinking on every request and
        # burns the Claude Code rate-limit pool unexpectedly.
        return field != "reasoning_effort"

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        # OME-479: one provider-local source drives summary, detail, and dispatch.
        return anthropic_chat_parameter_rules(model=model, auth_type=auth_type)

    def chat_parameter_tools(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ToolCapability, ...]:
        # OME-583: Anthropic validates OpenAI-style function tools through the installed
        # AnthropicConfig transform (§9), so it advertises the `function` tool type.
        return anthropic_chat_parameter_tools(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        # OME-479 §5.1/§6.3: Anthropic has NO live discovery (no credentialed Models-API
        # probe in v1), so the ONLY honest parameter evidence is reviewed labelled-static
        # — the standard chat fields the INSTALLED transform accepts (source
        # "anthropic:static", NO network). Endpoint-level evidence is model-independent,
        # so it does not vary by model. This makes the detail contract show every accepted
        # field with its gateway status: temperature/top_p/max_tokens/reasoning_effort are
        # ALSO ruled → ENABLED with this provenance; native provider_params.top_k is ruled
        # for api_key only (ENABLED there, visible-but-DISABLED under OAuth); stop is ALSO
        # ruled → ENABLED under both modes with this provenance (OME-582); tools +
        # tool_choice are ALSO ruled → ENABLED under both modes (OME-583), evidenced here
        # so every enabled tool path is fully backed (§4.4).
        # INVARIANT: an observation NEVER enables a parameter — only a rule does.
        return anthropic_static_param_observations(model) + tool_parameter_observations(
            anthropic_chat_parameter_tools(model=model, auth_type=auth_type),
            source=STATIC_SOURCE,
        )

    def validate_chat_parameter_combination(
        self, body: Mapping[str, Any], *, model: str, auth_mode: AuthMode
    ) -> None:
        # OME-640: reasoning_effort and max_tokens each validate alone, but on a
        # manual-thinking model the effort becomes a thinking budget Anthropic
        # requires max_tokens to exceed. The rule is model- and auth-specific, so
        # it lives beside the parameter rules rather than in the classifier.
        raise_on_thinking_conflict(body, model=model, auth_mode=auth_mode)

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        # Claude-Code attribution moved to dispatch time (chat_handler):
        # prepare runs before auth resolution, so the OAuth-vs-API-key
        # decision the billing block depends on is not known yet (SF-244 F02).
        out = dict(body)
        if out.get("reasoning_effort") == "none":
            out.pop("reasoning_effort", None)
        return out

    def global_cache_projection(self, body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        """OME-305: what Anthropic will send, as a pure function of the request body.

        FEATURE: one global exact-request cache. Anthropic is the provider the
        benchmark suites actually hammer, so it has to be cacheable for the ticket to
        deliver anything — which means describing the two things this boundary does
        without the caller asking: it drops ``reasoning_effort="none"``, and (on OAuth
        traffic only) it prepends a Claude-Code attribution block.

        INVARIANT: pure. No I/O, no clock, no randomness, no credential, no identity,
        and no read of ``self.settings`` — the registered model list is per-deployment
        configuration, and consulting it would make one host's key differ from
        another's while each host's own determinism test still passed.

        ACCEPTED CONSEQUENCE — the credential-gated attribution block. Whether the
        block is prepended depends on the resolved ``api_key`` (``sk-ant-oat…`` means
        an OAuth subscription), and a global key may never see a credential. So the
        mode bit is NOT keyed, and an entry filled by an OAuth caller can be served to
        an api-key caller whose own dispatch would carry no block, and vice versa.
        This is deliberate and approved, and it rests on three things:
          * the block is billing ATTRIBUTION, not an instruction — its variable part
            is a three-hex-character digest of the caller's own first user text;
          * that text is ``messages``, which is hashed VERBATIM, so the block is a
            function of already-keyed material plus the mode bit alone;
          * a MISS still dispatches under the caller's real mode, so an api-key
            request never gets the spoofed block sent upstream on its behalf
            (SF-244 audit F02) — the cache changes who may READ a stored answer, never
            what goes on the wire.
        The constants that shape the block are folded into
        ``GLOBAL_CACHE_ADAPTER_REVISION`` unconditionally, so changing the scheme
        abandons every entry rather than re-serving old ones under new attribution.

        AIDEV-NOTE: ``prepared`` deliberately does NOT describe ``top_k``. Owner
        decision 59 keeps this api-key-only parameter as a cache bypass because the
        key is built before auth resolution; describing it here would overstate the
        auth-independent projection.
        """
        model = body.get("model")
        if not isinstance(model, str) or not model.startswith(_GATEWAY_MODEL_PREFIX):
            return CacheBypass(reason=PROJECTION_BYPASS_REASON)
        if not model[len(_GATEWAY_MODEL_PREFIX) :]:
            # A bare prefix names no model. Bypass rather than key an id that cannot
            # dispatch — a projection may never fail a request, only decline to key it.
            return CacheBypass(reason=PROJECTION_BYPASS_REASON)
        prepared: dict[str, Any] = {}
        # WHY the EFFECTIVE value and not the caller's: ``prepare_chat_body`` removes
        # ``reasoning_effort="none"``, and omission is what "none" already means. This
        # records what will actually be sent. (The rule for this path still keys the
        # caller's own spelling separately today, so "none" and omitted remain two
        # entries for one upstream call — a duplicate entry, never a wrong hit.)
        if "reasoning_effort" in body and body["reasoning_effort"] != "none":
            prepared["reasoning_effort"] = body["reasoning_effort"]
        return {
            # INVARIANT: the gateway prefix is LiteLLM's own provider prefix and
            # travels to the wire intact, so the resolved id IS the full model string.
            "resolved_model": model,
            "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
            "prepared": prepared,
        }

    def usage_accounting_strategy(self) -> UsageAccountingStrategy:
        # OME-303 §5.2: anthropic dispatches through litellm's AnthropicChatCompletion,
        # which uses the shared AsyncHTTPHandler and honours an injected client — so the
        # gateway's observed handler sees every generation send.
        return UsageAccountingStrategy.litellm_async_http()

    def normalize_chat_usage_accounting(
        self,
        *,
        request_body: Mapping[str, Any],
        raw_response: Mapping[str, Any] | None,
        final_response: Mapping[str, Any] | None,
        failed: bool = False,
    ) -> ProviderUsageAccountingEvidence:
        return normalize_anthropic_usage_accounting(
            request_body=request_body,
            raw_response=raw_response,
            final_response=final_response,
            failed=failed,
        )

    def cache_reference_from_cached_response(
        self, cached_response: Mapping[str, Any]
    ) -> CacheReference | None:
        return cache_reference_from_cached(cached_response)

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        return await chat_completion(apply_anthropic_dispatch_controls(body))

    async def chat_completion_stream(self, body: dict[str, Any]) -> AsyncIterator[Any]:
        stream = await chat_completion_stream(body)
        async for chunk in stream:
            yield chunk

    async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict:
        return await exchange_authorization_code(
            request.code,
            request.code_verifier,
            redirect_uri=request.redirect_uri,
            state=request.state,
            http_client_factory=request.http_client_factory,
            settings=self.settings,
        )

    async def extract_identity(
        self,
        _credentials: dict[str, Any],
        *,
        http_client_factory: Any | None = None,  # noqa: ARG002
    ) -> AccountIdentity | None:
        return None

    def requires_oauth_connection_label(self) -> bool:
        return True

    async def bootstrap_profiles(
        self,
        *,
        account_id: str,
        credential_store: CredentialBlobStore | None = None,
        index_store: ProfileIndexStore | None = None,
    ) -> None:
        await bootstrap_from_claude_code(
            account_id=account_id,
            credential_store=credential_store,
            index_store=index_store,
            settings=self.settings,
        )


PLUGIN = AnthropicProviderPlugin()
