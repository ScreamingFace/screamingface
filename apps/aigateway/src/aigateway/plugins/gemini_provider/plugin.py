from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError
from litellm.types.utils import ModelResponse

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.api_key_validation import ApiKeyValidator
from aigateway.core.google_code_assist import (
    account_label_from_credentials,
    extract_account_identity,
)
from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.parameter_discovery import DiscoverySourceRef
from aigateway.core.plugin_base import (
    CredentialStrategy,
    ModelEntry,
    OAuthCodeExchangeRequest,
    OAuthConfig,
    ProviderPluginBase,
)
from aigateway.core.standard_parameters import tool_parameter_observations

from .api_key_validation import GeminiApiKeyValidator
from .auth import (
    CLIENT_AUTH_HEADER_NAMES,
    GeminiOAuth,
    credential_service_for,
    exchange_authorization_code,
)
from .chat_handler import (
    _env_api_key,
    ensure_litellm_gemini_provider_registered,
    get_litellm_gemini_handler,
)
from .discovery import (
    CODE_ASSIST_SOURCE,
    DISCOVERY_SOURCE,
    DISCOVERY_SOURCE_REVISION,
    GEMINI_CODE_ASSIST_OBSERVATIONS,
    GEMINI_DISCOVERY_STATIC_OBSERVATIONS,
    discover_gemini_snapshot,
)
from .models import MODELS
from .oauth_config import (
    GEMINI_AUTHORIZE_EXTRA_PARAMS,
    GEMINI_AUTHORIZE_URL,
    GEMINI_CLIENT_ID,
    GEMINI_REDIRECT_PATH,
    GEMINI_SCOPES,
    GEMINI_TOKEN_URL,
)
from .parameters import gemini_chat_parameter_rules, gemini_chat_parameter_tools
from .settings import GeminiPluginSettings

if TYPE_CHECKING:
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderDiscoverySnapshot,
        ProviderParameterObservation,
        ToolCapability,
    )
    from aigateway.core.credential_blob.store import CredentialBlobStore
    from aigateway.core.parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from aigateway.core.profile_models import AuthMode


_CLIENT_AUTH_HEADER_NAMES = CLIENT_AUTH_HEADER_NAMES


def _retry_after_header(exc: CustomLLMError) -> dict[str, str]:
    """Surface the provider's reset window as a Retry-After header.

    ``_error_from_response`` stashes the parsed delay on ``exc.retry_after``;
    promoting it to a header lets the gateway's retry loop honor the *real*
    window instead of guessing via exponential backoff.
    """
    seconds = getattr(exc, "retry_after", None)
    if seconds is None:
        return {}
    return {"Retry-After": str(math.ceil(seconds))}


def _detail_for_error(exc: CustomLLMError) -> dict[str, str]:
    status_code = int(exc.status_code or 502)
    code = "provider_error"
    if status_code in (401, 403):
        code = "auth_required"
    elif status_code == 429:
        code = "rate_limited"
    elif status_code >= 500:
        code = "provider_unavailable"
    return {"code": code, "message": exc.message}


class GeminiProviderPlugin(ProviderPluginBase[GeminiPluginSettings]):
    custom_llm_provider = "gemini-cli"
    provider_display_name = "Gemini CLI"
    provider_kind = "session"
    provider_group = "local_and_sessions"
    provider_group_display_name = "Local & Sessions"
    provider_description = "Gemini models through your Google account or API key"
    provider_color = "#4392c5"
    provider_sort_order = 30
    settings_cls = GeminiPluginSettings

    def credential_service_provider(self) -> str:
        return "gemini"

    def register_models(self) -> list[ModelEntry]:
        return list(MODELS)

    def oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            authorize_url=GEMINI_AUTHORIZE_URL,
            token_url=GEMINI_TOKEN_URL,
            client_id=GEMINI_CLIENT_ID,
            scopes=GEMINI_SCOPES,
            redirect_path=GEMINI_REDIRECT_PATH,
            extra_authorize_params=GEMINI_AUTHORIZE_EXTRA_PARAMS,
        )

    def oauth_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
        http_client_factory: Any | None = None,
    ) -> CredentialStrategy:
        return GeminiOAuth(
            profile_name=profile_name,
            credential_store=credential_store,
            http_client_factory=http_client_factory,
        )

    def supports_api_key(self) -> bool:
        return True

    def api_key_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> CredentialStrategy:
        # The injected x-goog-api-key rides extra_headers into the custom
        # handler (caller-supplied copies are stripped in prepare_chat_body
        # BEFORE the gateway merges strategy headers, so only the gateway-owned
        # key survives) and selects the generativelanguage API-key path there.
        return ApiKeyStrategy(
            profile_name,
            service=credential_service_for(profile_name),
            account="default",
            header_builder=lambda api_key: {"x-goog-api-key": api_key},
            credential_store=credential_store,
        )

    def api_key_validator(self) -> ApiKeyValidator:
        return GeminiApiKeyValidator(
            settings=self.settings,
            registered_models=self.register_models(),
        )

    async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict[str, Any]:
        return await exchange_authorization_code(
            request.code,
            request.code_verifier,
            redirect_uri=request.redirect_uri,
            http_client_factory=request.http_client_factory,
        )

    def account_label_from_credentials(self, credentials: dict[str, Any]) -> str | None:
        return account_label_from_credentials(credentials)

    async def extract_identity(
        self,
        credentials: dict[str, Any],
        *,
        http_client_factory: Any | None = None,
    ) -> AccountIdentity | None:
        identity = await extract_account_identity(
            credentials,
            http_client_factory=http_client_factory,
        )
        if identity is None:
            return None
        return AccountIdentity(
            sub=identity.subject,
            email=identity.email,
            name=identity.name,
            raw=identity.as_dict(),
        )

    def allows_chatless_profile(self) -> bool:
        return True

    def profileless_auth_mode(self) -> AuthMode | None:
        # INVARIANT: this is the same selector the handler consults before
        # dispatching to the public generativelanguage endpoint.
        return "api_key" if _env_api_key() is not None else None

    def supports_chat_streaming(self) -> bool:
        return False

    def should_mark_profile_error_on_dispatch_status(self, status_code: int) -> bool:
        return status_code in (401, 403)

    def invalidate_profile_session(self, profile_name: str) -> None:
        get_litellm_gemini_handler().invalidate_session(profile_name)

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        # OME-479 §Phase 9: Gemini's proven sampling fields, each pinned through
        # build_generate_content_body's generationConfig. A rule is the ONLY thing
        # that enables a parameter; every other caller field fails closed at
        # classification. Both auth paths share the builder, so rules apply to both.
        return gemini_chat_parameter_rules(model=model, auth_type=auth_type)

    def chat_parameter_tools(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ToolCapability, ...]:
        # OME-583: build_generate_content_body maps tools[] → functionDeclarations (§9),
        # so Gemini advertises the `function` tool type (tool_choice stays unruled).
        return gemini_chat_parameter_tools(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        # OME-479 §Phase 9 step 2: evidence is AUTH-SCOPED. The api-key path talks to
        # the public generativelanguage API, which publishes a Discovery schema
        # (source "gemini:discovery" — the richer surface). The OAuth path talks to
        # the Code Assist envelope, which has NO public schema, so its only honest
        # evidence is the reviewed builder mapping (source "gemini:code-assist" — a
        # strict subset). This is why public Discovery never overclaims OAuth.
        # OME-583: the `tools` request path is evidenced HERE too (tool_choice=False —
        # Gemini has no toolConfig home), carrying THAT mode's label so the auth-scoped
        # source invariant holds; the sampling-evidence discovery constants stay pure.
        # INVARIANT: an observation NEVER enables a parameter — only a rule does.
        tools = gemini_chat_parameter_tools(model=model, auth_type=auth_type)
        if auth_type == "oauth":
            return GEMINI_CODE_ASSIST_OBSERVATIONS + tool_parameter_observations(
                tools, source=CODE_ASSIST_SOURCE, tool_choice=False
            )
        return GEMINI_DISCOVERY_STATIC_OBSERVATIONS + tool_parameter_observations(
            tools, source=DISCOVERY_SOURCE, tool_choice=False
        )

    def _discovers(self, model: str, auth_type: AuthMode | None) -> bool:
        """Is the PUBLIC Discovery document evidence about THIS contract read?

        # INVARIANT: the ONE predicate behind both discovery hooks. Owning it here
        # rather than in each makes "declared a source, then reported NOT ATTEMPTED"
        # structurally unreachable — the one inconsistency the runtime cannot
        # distinguish from a real outage.
        # WHY the api-key mode only: that path talks to the public
        # generativelanguage API, which publishes this document. The OAuth path talks
        # to the Code Assist envelope, which publishes NO schema — inferring one
        # upstream's surface from another's would be exactly the overclaim the two
        # source labels exist to prevent. An unresolved mode fails closed.
        """
        return auth_type == "api_key" and model.startswith(f"{self.custom_llm_provider}/")

    def chat_discovery_source(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> DiscoverySourceRef | None:
        # OME-632: declared BEFORE any fetch, so the observation cache can judge a
        # stored entry's trustworthiness without paying for a round trip. Returning
        # None on the OAuth path costs nothing AND publishes no freshness window —
        # the honest report for a contract no fetch stands behind.
        if not self._discovers(model, auth_type):
            return None
        return DiscoverySourceRef(source=DISCOVERY_SOURCE, revision=DISCOVERY_SOURCE_REVISION)

    async def discover_chat_parameter_snapshot(
        self,
        *,
        model: str,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth_type: AuthMode | None = None,
    ) -> ProviderDiscoverySnapshot | None:
        # OME-479 §Phase 9: the DYNAMIC source. The document is model-INDEPENDENT, so
        # the model only decides WHETHER this provider is being asked, not what is
        # fetched — the evidence lands endpoint-scoped.
        # INVARIANT: never enables a parameter (only a rule does); off the chat
        # dispatch path; a sanitized DiscoveryError PROPAGATES so the cache can
        # degrade honestly rather than store a failure as fresh.
        if not self._discovers(model, auth_type):
            return None
        return await discover_gemini_snapshot(client=client, limits=limits)

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        out = dict(body)
        # API-key fallback is gateway-owned via environment, not caller-supplied per request.
        out.pop("api_key", None)
        extra_headers = out.get("extra_headers")
        if isinstance(extra_headers, dict):
            out["extra_headers"] = {
                key: value
                for key, value in extra_headers.items()
                if isinstance(key, str) and key.lower() not in _CLIENT_AUTH_HEADER_NAMES
            }
        elif "extra_headers" in out:
            # A non-dict value would crash the handler downstream on the
            # chatless path (SF-244 audit F06); drop it like ollama does.
            out.pop("extra_headers", None)
        return out

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        optional_params = {
            key: value
            for key, value in body.items()
            if key not in {"model", "messages", "api_key", "extra_headers", "timeout"}
        }
        try:
            return await get_litellm_gemini_handler().acompletion(
                model=body["model"],
                messages=body["messages"],
                api_base=None,
                custom_prompt_dict={},
                model_response=ModelResponse(),
                print_verbose=lambda *_args, **_kwargs: None,
                encoding=None,
                api_key=body.get("api_key"),
                logging_obj=None,
                optional_params=optional_params,
                headers=body.get("extra_headers"),
                timeout=body.get("timeout"),
            )
        except CustomLLMError as exc:
            raise HTTPException(
                status_code=int(exc.status_code or 502),
                detail=_detail_for_error(exc),
                headers=_retry_after_header(exc),
            ) from exc


ensure_litellm_gemini_provider_registered()

PLUGIN = GeminiProviderPlugin()
