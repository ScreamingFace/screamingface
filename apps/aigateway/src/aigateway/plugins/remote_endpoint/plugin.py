"""One provider instance per configured remote endpoint.

# FEATURE: hosted BYOM — every approved endpoint is served by this one class; its definition alone
# decides the provider ID, origin, targets and where its keys are stored.
# STORY: as an operator, I attach a tenant's key for an approved endpoint with the existing admin
# API; the tenant's chat calls reach only that endpoint with only that key.
# INVARIANT: no branch on a specific endpoint ID; two instances differ only by their definitions.
# INVARIANT: the key namespace is the INSTANCE ID (`aigateway:<id>:<name>`), matching what the
# Connection admin publication mints for `credential_service_provider()`, so pairs never share a
# key; the key itself is bound to the instance's origin (see `credential.py`).
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.api_key_validation import ApiKeyValidator
from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import ParameterProjectionRule
from aigateway.core.credential_blob import CredentialBlobStore
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase

from .credential import OriginBoundApiKeyStrategy
from .definitions import ChatTarget, EndpointDefinition
from .request import chat_parameter_rules, chat_request, check_text_messages
from .transport import post_chat_completion
from .validation import RemoteEndpointReadiness

_CHAT_FIELDS = ("model", "messages", "max_tokens")


def _bearer(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


class RemoteEndpointPlugin(ProviderPluginBase):
    def __init__(
        self,
        definition: EndpointDefinition,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__()
        self.custom_llm_provider = definition.id
        self.provider_display_name = definition.display_name
        self._definition = definition
        self._transport = transport

    def register_models(self) -> list[ModelEntry]:
        # WHY empty: catalog rows would name private targets to every account. Listing arrives
        # with the grant-filtered catalog; dispatch never depends on it.
        return []

    def supports_api_key(self) -> bool:
        return True

    def supports_chat_streaming(self) -> bool:
        return False

    def api_key_strategy_for(
        self,
        credential_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> ApiKeyStrategy:
        return OriginBoundApiKeyStrategy(
            credential_name,
            origin=self._definition.origin,
            service=f"aigateway:{self.custom_llm_provider}:{credential_name}",
            account="default",
            header_builder=_bearer,
            credential_store=credential_store,
        )

    def api_key_validator(self) -> ApiKeyValidator:
        return RemoteEndpointReadiness(self._definition, transport=self._transport)

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        del model
        return chat_parameter_rules(auth_type)

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        # INVARIANT: the target and the text contract are checked BEFORE the route authorizes, so
        # an unknown alias or a message outside the contract costs no credential read and no
        # upstream I/O. Caller transport/auth fields are dropped here.
        self._target_for(body.get("model"))
        check_text_messages(body.get("messages"), provider=self.custom_llm_provider)
        return {key: body[key] for key in _CHAT_FIELDS if key in body}

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        target = self._target_for(body.get("model"))
        api_key = body.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            # WHY refuse rather than send unauthenticated: there is no ambient-token fallback.
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "provider_unavailable",
                    "message": "No credential was resolved for this endpoint.",
                },
            )
        return await post_chat_completion(
            self._definition.origin + target.request_path,
            chat_request(target, body.get("messages"), max_tokens=body.get("max_tokens")),
            api_key=api_key,
            transport=self._transport,
        )

    def _target_for(self, model: object) -> ChatTarget:
        prefix = f"{self.custom_llm_provider}/"
        target = None
        if isinstance(model, str) and model.startswith(prefix):
            target = self._definition.target(model.removeprefix(prefix))
        if target is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_model",
                    "message": "model is not a configured target of this provider",
                },
            )
        return target
