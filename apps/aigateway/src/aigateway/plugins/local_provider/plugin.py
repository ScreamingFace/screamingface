from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException

from aigateway.core.plugin_base import ModelDiscoverySource, ModelEntry, ProviderPluginBase

from .discovery import discover_local_models, upstream_model_id
from .parameters import local_chat_parameter_observations, local_chat_parameter_rules
from .settings import LocalPluginSettings
from .transport import post_chat_completion

if TYPE_CHECKING:
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderParameterObservation,
    )
    from aigateway.core.parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from aigateway.core.profile_models import AuthMode


LOCAL_MODEL_SOURCE = ModelDiscoverySource(
    key="local:models:list",
    revision="local:models:list-v1",
    ttl_s=5.0,
    stale_ttl_s=30.0,
    failure_ttl_s=1.0,
)


class LocalProviderPlugin(ProviderPluginBase[LocalPluginSettings]):
    custom_llm_provider = "local"
    provider_display_name = "Local"
    settings_cls = LocalPluginSettings

    def __init__(
        self,
        settings: LocalPluginSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(settings)
        self._transport = transport

    def register_models(self) -> list[ModelEntry]:
        return []

    def conformance_models(self) -> list[ModelEntry]:
        # INVARIANT: never reaches runtime listing; dynamic providers still need a
        # deterministic representative for the registry-wide contract sweep.
        return [
            ModelEntry(
                model_name="local/__conformance__",
                litellm_params={"model": "__conformance__"},
            )
        ]

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return LOCAL_MODEL_SOURCE if self.settings.enabled else None

    async def discover_live_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
    ) -> tuple[ModelEntry, ...] | None:
        if not self.settings.enabled:
            return None
        return await discover_local_models(self.settings, client=client, limits=limits)

    def allows_chatless_profile(self) -> bool:
        return True

    def supports_chat_streaming(self) -> bool:
        return False

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        return local_chat_parameter_rules(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        return local_chat_parameter_observations(model=model, auth_type=auth_type)

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        # FEATURE: v1 intentionally supports only the common minimum needed for
        # local Fusion execution. Additional fields earn provider rules and wire tests.
        return {key: body[key] for key in ("model", "messages", "max_tokens") if key in body}

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        if not self.settings.enabled:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "provider_unavailable",
                    "message": "The local model provider is disabled.",
                },
            )
        # INVARIANT: live listing controls visibility, never dispatchability. The
        # fixed loopback endpoint plus this structural namespace check are dispatch
        # authority, so a Gateway restart cannot invalidate Engine's warm catalog.
        upstream = upstream_model_id(body.get("model"))
        if upstream is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_model",
                    "message": "model is not a valid local model id",
                },
            )
        payload = dict(body)
        payload["model"] = upstream
        return await post_chat_completion(
            self.settings.base_url,
            payload,
            transport=self._transport,
        )


PLUGIN = LocalProviderPlugin()
