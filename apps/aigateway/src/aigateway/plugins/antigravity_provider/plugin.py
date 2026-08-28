"""Antigravity provider plugin.

Wires provider discovery, model seed, loopback OAuth config, the OAuth
strategy / authorization-code exchange (Unit 3), and LiteLLM registration under
provider="antigravity". The chat transport (Unit 4) is added next; its hook is
declared here so the contract is stable.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError
from litellm.types.utils import ModelResponse

from aigateway.core.google_code_assist import (
    account_label_from_credentials,
    extract_account_identity,
)
from aigateway.core.oauth.identity import AccountIdentity
from aigateway.core.plugin_base import (
    CredentialStrategy,
    ModelEntry,
    OAuthCodeExchangeRequest,
    OAuthConfig,
    ProviderPluginBase,
)

from .auth import AntigravityOAuth, exchange_authorization_code
from .chat_handler import (
    ANTIGRAVITY_ACTIVATION_REQUIRED_CODE,
    CLIENT_AUTH_HEADER_NAMES,
    AntigravityCustomLLM,
    ensure_litellm_antigravity_provider_registered,
    get_litellm_antigravity_handler,
)
from .models import MODELS
from .parameters import (
    ANTIGRAVITY_OBSERVATIONS,
    antigravity_chat_parameter_rules,
    antigravity_chat_parameter_tools,
)
from .settings import AntigravityPluginSettings

if TYPE_CHECKING:
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderParameterObservation,
        ToolCapability,
    )
    from aigateway.core.credential_blob.store import CredentialBlobStore
    from aigateway.core.profile_models import AuthMode


def _retry_after_header(exc: CustomLLMError) -> dict[str, str]:
    seconds = getattr(exc, "retry_after", None)
    if seconds is None:
        return {}
    return {"Retry-After": str(math.ceil(seconds))}


def _detail_for_error(exc: CustomLLMError) -> dict[str, str]:
    status_code = int(exc.status_code or 502)
    code = "provider_error"
    if getattr(exc, "detail_code", None) == ANTIGRAVITY_ACTIVATION_REQUIRED_CODE:
        code = ANTIGRAVITY_ACTIVATION_REQUIRED_CODE
    elif status_code in (401, 403):
        code = "auth_required"
    elif status_code == 429:
        code = "rate_limited"
    elif status_code >= 500:
        code = "provider_unavailable"
    return {"code": code, "message": exc.message}


class AntigravityProviderPlugin(ProviderPluginBase[AntigravityPluginSettings]):
    custom_llm_provider = "antigravity"
    provider_display_name = "Antigravity"
    provider_kind = "session"
    provider_group = "local_and_sessions"
    provider_group_display_name = "Local & Sessions"
    provider_description = "Models available through your Google Antigravity account"
    provider_color = "#6976ae"
    provider_sort_order = 40
    settings_cls = AntigravityPluginSettings

    def credential_service_provider(self) -> str:
        return "antigravity"

    def register_models(self) -> list[ModelEntry]:
        return list(MODELS)

    def oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            authorize_url=self.settings.authorize_url,
            token_url=self.settings.token_url,
            client_id=self.settings.client_id,
            scopes=list(self.settings.scopes),
            redirect_path=self.settings.redirect_path,
            extra_authorize_params=dict(self.settings.authorize_extra_params),
        )

    def _client_secret(self) -> str | None:
        # GATE-2 Option A: the public installed-app secret has a SecretStr
        # default with optional AIGW_ANTIGRAVITY_CLIENT_SECRET override. Read the
        # raw value only here, at the point it is passed into the token POST.
        secret = self.settings.client_secret
        return secret.get_secret_value() if secret is not None else None

    def oauth_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
        http_client_factory: Any | None = None,
    ) -> CredentialStrategy:
        return AntigravityOAuth(
            profile_name=profile_name,
            client_secret=self._client_secret(),
            client_id=self.settings.client_id,
            token_url=self.settings.token_url,
            credential_store=credential_store,
            http_client_factory=http_client_factory,
        )

    async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict[str, Any]:
        return await exchange_authorization_code(
            request.code,
            request.code_verifier,
            redirect_uri=request.redirect_uri,
            client_secret=self._client_secret(),
            client_id=self.settings.client_id,
            token_url=self.settings.token_url,
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

    def supports_api_key(self) -> bool:
        # No Antigravity API-key path; OAuth-only for v1.
        return False

    def allows_chatless_profile(self) -> bool:
        return False

    def supports_chat_streaming(self) -> bool:
        # Upstream SSE is aggregated into a non-streaming response in v1.
        return False

    def should_mark_profile_error_on_dispatch_status(self, status_code: int) -> bool:
        return status_code in (401, 403)

    def invalidate_profile_session(self, profile_name: str) -> None:
        get_litellm_antigravity_handler().invalidate_session(profile_name)

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        # OME-634: the fields build_generate_content_body actually reads out of
        # optional_params, each pinned into the Code Assist body it emits. A rule is
        # the ONLY thing that enables a parameter; every other caller field fails
        # closed at classification, before any credential is read.
        return antigravity_chat_parameter_rules(model=model, auth_type=auth_type)

    def chat_parameter_tools(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ToolCapability, ...]:
        # OME-634: the builder converts tools[] → functionDeclarations, so `function`
        # is advertised. It emits no toolConfig, so tool_choice stays unruled.
        return antigravity_chat_parameter_tools(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        # OME-634: the Code Assist envelope publishes no machine-readable schema, so
        # the only honest evidence is the reviewed builder mapping, labelled with THIS
        # provider's own source. Endpoint-level evidence does not vary by model.
        # INVARIANT: an observation NEVER enables a parameter — only a rule does.
        return ANTIGRAVITY_OBSERVATIONS

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        # Layer 1 of the two-layer caller-auth strip (findings U4): drop
        # gateway-owned headers a caller tried to supply, BEFORE the gateway
        # merges the OAuth strategy's headers. The chat handler re-filters the
        # same superset on the upstream forward (layer 2).
        out = dict(body)
        extra_headers = out.get("extra_headers")
        if isinstance(extra_headers, dict):
            out["extra_headers"] = {
                key: value
                for key, value in extra_headers.items()
                if isinstance(key, str) and key.lower() not in CLIENT_AUTH_HEADER_NAMES
            }
        elif "extra_headers" in out:
            # A non-dict value would crash the handler downstream; drop it.
            out.pop("extra_headers", None)
        return out

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        optional_params = {
            key: value
            for key, value in body.items()
            if key not in {"model", "messages", "api_key", "extra_headers", "timeout"}
        }
        try:
            return await get_litellm_antigravity_handler().acompletion(
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


# Register a handler bound to this plugin's settings so the Code Assist hosts,
# user agent, and api version come from configuration rather than defaults.
ensure_litellm_antigravity_provider_registered(
    AntigravityCustomLLM(settings=AntigravityPluginSettings())
)

PLUGIN = AntigravityProviderPlugin()
