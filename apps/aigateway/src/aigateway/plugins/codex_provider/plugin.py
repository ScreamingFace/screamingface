from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError
from litellm.types.utils import ModelResponse

from aigateway.core.content_parts import check_messages
from aigateway.core.oauth.identity import AccountIdentity, identity_from_id_token
from aigateway.core.plugin_base import (
    ModelEntry,
    OAuthCodeExchangeRequest,
    OAuthConfig,
    OAuthStrategy,
    ProviderPluginBase,
)
from aigateway.core.provider_error_text import credential_values, plugin_error_message

from .auth import (
    CodexOAuth,
    account_label_from_credentials,
    exchange_authorization_code,
    plan_type_from_token,
)
from .chat_handler import (
    ensure_litellm_codex_provider_registered,
    get_litellm_codex_handler,
)
from .live_models import (
    LIVE_MODELS_DISCOVERY_SOURCE,
    available_models_for,
    latest_listing,
)
from .models import MODELS
from .oauth_config import (
    CODEX_AUTHORIZE_EXTRA_PARAMS,
    CODEX_AUTHORIZE_URL,
    CODEX_CLIENT_ID,
    CODEX_REDIRECT_PATH,
    CODEX_REDIRECT_PORTS,
    CODEX_SCOPES,
    CODEX_TOKEN_URL,
)
from .parameters import CODEX_OBSERVATIONS, codex_chat_parameter_rules

if TYPE_CHECKING:
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderParameterObservation,
    )
    from aigateway.core.credential_blob.store import CredentialBlobStore
    from aigateway.core.parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from aigateway.core.plugin_base import ModelDiscoverySource
    from aigateway.core.profile_models import AuthMode


class CodexProviderPlugin(ProviderPluginBase):
    # api_key_strategy_for intentionally stays the base None default: codex
    # subscription models ride the ChatGPT backend Responses endpoint, which
    # only accepts OAuth tokens — chat_handler.py rejects sk-/sk-proj- keys
    # outright. The set-api-key endpoint therefore returns
    # api_key_not_supported for codex. Routing API-key profiles to the OpenAI
    # platform API instead is a possible follow-up.
    custom_llm_provider = "codex"
    provider_display_name = "Codex"

    def register_models(self) -> list[ModelEntry]:
        return list(MODELS)

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        # OME-1634: the live list is per ChatGPT account (see live_models.py); the
        # process-wide listing serves the most recently refreshed account list.
        return LIVE_MODELS_DISCOVERY_SOURCE

    async def discover_live_models(
        self,
        *,
        client: DiscoveryHttpClient,  # noqa: ARG002
        limits: DiscoveryLimits | None = None,  # noqa: ARG002
    ) -> tuple[ModelEntry, ...] | None:
        """The latest account's live list; ``no_snapshot`` until one was read.

        # INVARIANT: the injected client is credential-free and the Codex catalog needs
        # the account's token, so this NEVER dials — it serves what a dispatch-driven
        # refresh already read (fail closed to the static seeds otherwise).
        """
        return latest_listing()

    def oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            authorize_url=CODEX_AUTHORIZE_URL,
            token_url=CODEX_TOKEN_URL,
            client_id=CODEX_CLIENT_ID,
            scopes=CODEX_SCOPES,
            redirect_path=CODEX_REDIRECT_PATH,
            extra_authorize_params=CODEX_AUTHORIZE_EXTRA_PARAMS,
            loopback_redirect_ports=CODEX_REDIRECT_PORTS,
        )

    def oauth_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
        http_client_factory: Any | None = None,
    ) -> OAuthStrategy:
        return CodexOAuth(
            profile_name=profile_name,
            credential_store=credential_store,
            http_client_factory=http_client_factory,
        )

    async def exchange_oauth_code(self, request: OAuthCodeExchangeRequest) -> dict:
        return await exchange_authorization_code(
            request.code,
            request.code_verifier,
            redirect_uri=request.redirect_uri,
            http_client_factory=request.http_client_factory,
        )

    def account_label_from_credentials(self, credentials: dict) -> str | None:
        return account_label_from_credentials(credentials)

    async def extract_identity(
        self,
        credentials: dict[str, Any],
        *,
        http_client_factory: Any | None = None,  # noqa: ARG002
    ) -> AccountIdentity | None:
        return identity_from_id_token(credentials.get("id_token"))

    def supports_chat_streaming(self) -> bool:
        return False

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        # OME-634: reasoning_effort alone, because _build_payload copies a fixed key
        # list into the Responses body and drops everything else. prepare_chat_body
        # below already converted the field — without this rule the classifier
        # rejected it first, so that conversion was unreachable.
        # AIDEV-NOTE: chat_parameter_tools is deliberately NOT overridden; the base
        # default () is correct until the transform learns the Responses tool shape.
        return codex_chat_parameter_rules(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        # OME-634: the ChatGPT Responses endpoint publishes no machine-readable
        # schema to the gateway, so the evidence is the reviewed transform mapping
        # under Codex's own source label — never OpenAI's.
        # INVARIANT: an observation NEVER enables a parameter; only a rule does.
        return CODEX_OBSERVATIONS

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        # INVARIANT (OME-1541): refuse here, in the route, every part the adapter cannot
        # carry, so the caller gets the typed 422 instead of LiteLLM's remapped error — and
        # never a silent drop.
        check_messages(
            body.get("messages") or [],
            provider="codex",
            media_roles=frozenset({"user"}),
            allow_remote_images=True,
        )
        if "reasoning_effort" in body:
            effort = body.pop("reasoning_effort")
            if effort is not None and "reasoning" not in body:
                body["reasoning"] = {"effort": effort}
        return body

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        optional_params = {
            key: value
            for key, value in body.items()
            if key not in {"model", "messages", "api_key", "extra_headers", "timeout"}
        }
        try:
            return await get_litellm_codex_handler().acompletion(
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
            if _is_model_refusal(exc):
                raise await _model_unsupported(body) from exc
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "code": "provider_error",
                    "message": plugin_error_message(
                        exc.message, status=exc.status_code, forbidden=credential_values(body)
                    ),
                },
            ) from exc


# WHY a text marker: the backend answers a model refusal with a plain 400 and no error code;
# this sentence is the only thing that tells it apart from a malformed request.
_MODEL_REFUSAL_MARKER = "not supported when using Codex with a ChatGPT account"


def _is_model_refusal(exc: CustomLLMError) -> bool:
    # INVARIANT: both the 400 and the marker — the text alone on another status stays as is.
    return exc.status_code == 400 and _MODEL_REFUSAL_MARKER in str(exc.message)


async def _model_unsupported(body: dict[str, Any]) -> HTTPException:
    """OME-1634: the sign-in is valid but Codex does not serve this model to its account.

    # WHY 403: the request is fine; the account's entitlement refuses the model (a free plan
    # is refused every model, a plus plan every retired slug). Codex keeps the default
    # no-mark status hook, so the profile stays authenticated. The message is
    # gateway-authored: no upstream text.
    # WHY available_models is fetched here: the refusal is exactly when the caller needs the
    # account's real list, and this is the one place holding that account's own credential.
    # Unknown → the key is omitted; the 403 never depends on discovery succeeding.
    """
    token = body.get("api_key")
    model = body.get("model")
    plan = plan_type_from_token(token) or "unknown"
    detail: dict[str, Any] = {
        "code": "codex_model_unsupported",
        "provider": "codex",
        "model": model,
        "plan": plan,
        "message": (
            f"Codex does not serve {model} to this ChatGPT account (plan: {plan}). "
            "Pick a model the account lists, or sign in with a ChatGPT plan that includes it."
        ),
    }
    available = await available_models_for(
        token if isinstance(token, str) else None, account_id=_account_id_header(body)
    )
    if available is not None:
        detail["available_models"] = available
    return HTTPException(status_code=403, detail=detail)


def _account_id_header(body: dict[str, Any]) -> str | None:
    headers = body.get("extra_headers") or {}
    value = headers.get("ChatGPT-Account-Id") or headers.get("chatgpt-account-id")
    return value if isinstance(value, str) and value else None


ensure_litellm_codex_provider_registered()

PLUGIN = CodexProviderPlugin()
