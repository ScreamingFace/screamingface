from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import HTTPException
from openai import AsyncOpenAI, Omit

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.api_key_validation import ApiKeyValidator
from aigateway.core.cache_ports import CacheBypass
from aigateway.core.plugin_base import CredentialStrategy, ModelEntry, ProviderPluginBase
from aigateway.core.request_hardening import strip_dispatch_controls
from aigateway.core.standard_parameters import direct_parameter_observations

from .api_key_validation import OpenAIApiKeyValidator
from .global_cache import gateway_dispatch_controls, project_global_cache_request
from .parameters import openai_chat_parameter_rules
from .runtime_guard import (
    certifies_global_cache_participation,
    has_unsafe_litellm_global_state,
    modifier_refuses_dispatch,
)
from .settings import OFFICIAL_API_BASE, OpenAIPluginSettings, is_route_valid_model_id

if TYPE_CHECKING:
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderParameterObservation,
    )
    from aigateway.core.credential_blob.store import CredentialBlobStore
    from aigateway.core.profile_models import AuthMode
    from aigateway.plugins.taxonomy.types import CacheReference


_OBSERVATION_SOURCE = "openai:locked-runtime"


def _credential_service_for(profile_name: str) -> str:
    return f"aigateway:openai:{profile_name}"


def _openai_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        verify=True,
        trust_env=False,
        follow_redirects=False,
    )


def _invalid_model_error() -> HTTPException:
    # OME-884: the refusal is now about the model ID's GRAMMAR, not about catalog
    # membership — ``default_models`` publishes ``/v1/models`` and admits nothing. The
    # ``invalid_model`` code is a caller-visible contract and is unchanged; the message
    # is corrected so it no longer describes a registry check that no longer happens.
    return HTTPException(
        status_code=400,
        detail={
            "code": "invalid_model",
            "provider": "openai",
            "message": "model is not a valid direct OpenAI model id",
        },
    )


def _unsafe_environment_error() -> HTTPException:
    error = HTTPException(
        status_code=503,
        detail={
            "code": "unsafe_openai_environment",
            "provider": "openai",
            "message": "direct OpenAI dispatch is unavailable",
        },
    )
    cast("Any", error).aigw_non_retryable = True
    return error


class OpenAIProviderPlugin(ProviderPluginBase[OpenAIPluginSettings]):
    custom_llm_provider = "openai"
    provider_display_name = "OpenAI"
    provider_description = "GPT and reasoning models direct from OpenAI"
    provider_color = "#53bea9"
    provider_sort_order = 110
    settings_cls = OpenAIPluginSettings

    def register_models(self) -> list[ModelEntry]:
        return [
            ModelEntry(model_name=model, litellm_params={"model": model})
            for model in self.settings.default_models
        ]

    def supports_api_key(self) -> bool:
        return True

    def supports_chat_streaming(self) -> bool:
        return False

    def api_key_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> CredentialStrategy:
        return ApiKeyStrategy(
            profile_name,
            service=_credential_service_for(profile_name),
            account="default",
            header_builder=lambda api_key: {"Authorization": f"Bearer {api_key}"},
            credential_store=credential_store,
        )

    def should_mark_profile_error_on_dispatch_status(self, status_code: int) -> bool:
        return status_code == 401

    def api_key_validator(self) -> ApiKeyValidator:
        return OpenAIApiKeyValidator(settings=self.settings)

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        return openai_chat_parameter_rules(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        del model, auth_type
        return direct_parameter_observations(("max_tokens",), source=_OBSERVATION_SOURCE)

    def global_cache_projection(self, body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        # OME-884: delegated to ``global_cache`` so the PURE projection lives in a module
        # that holds nothing impure — see that module for the invariants.
        #
        # AIDEV-NOTE: the runtime-safety gate deliberately is NOT here. It lives in
        # ``participates_in_global_cache`` below, because this method's port contract is
        # that it reads the request body ALONE, and the registry-wide purity sweep
        # poisons the environment to prove it. Gating here would also be the wrong shape:
        # PARTICIPATION and KEY MATERIAL are separate decisions.
        return project_global_cache_request(body)

    def participates_in_global_cache(self, model: object = None) -> bool:
        """Whether a row may be read or filled for this model in this runtime.

        # WHY the verdict is checked here at all, and not left to dispatch: the cache stage
        # runs ahead of model resolution and of any credential read, so the dispatch-side
        # 503 never gets the chance to refuse a replayed row.
        # The verdict itself — the shared ambient hazards, the exact-model alias rule and
        # the asymmetric ``modify_params`` exception — belongs to ``runtime_guard``. Its
        # reasoning is documented there once, rather than in two copies that can drift.
        """
        import litellm

        return certifies_global_cache_participation(litellm, model)

    def cache_reference_from_cached_response(
        self, cached_response: Mapping[str, Any]
    ) -> CacheReference | None:
        # OME-884: direct OpenAI certifies NO historical accounting evidence for a
        # replayed row. It contributes no usage-accounting strategy at all, so there is
        # nothing truthful to attach — and an explicit ``None`` is not the same as not
        # implementing the hook: ``attach_hit_metadata`` reaches it through ``getattr``
        # inside a ``try``, so a missing attribute logs "cache-reference mapper failed"
        # on every hit, reporting a failure that never happened.
        del cached_response
        return None

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        out = strip_dispatch_controls(body)
        # OME-884: SYNTAX, not membership. ``default_models`` is the bootstrap catalog
        # ``/v1/models`` publishes; it is not a dispatch allowlist. OpenAI stays the only
        # authority on whether a route-valid model exists and whether the selected
        # credential may use it, and it answers that on the MISS this request is on.
        #
        # INVARIANT: the SAME predicate the projection uses. The cache is read BEFORE
        # this runs, so a request the projection keyed must be one this method forwards
        # — otherwise a stored row could answer 200 for a request the gateway refuses.
        if not is_route_valid_model_id(out.get("model")):
            raise _invalid_model_error()
        out["api_base"] = OFFICIAL_API_BASE
        return out

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        import litellm

        if has_unsafe_litellm_global_state(litellm, body.get("model")):
            raise _unsafe_environment_error()
        # OME-884 cycle 2: the PRECISE half of the modifier asymmetry — see
        # ``runtime_guard.modifier_refuses_dispatch``. What matters HERE is the position:
        # both refusals precede API-key removal, client construction and ``acompletion``,
        # so a refused request does no upstream work and builds no client. The effective
        # body is what gets inspected, so a profile-defaulted ceiling counts.
        if modifier_refuses_dispatch(litellm, body.get("max_tokens")):
            raise _unsafe_environment_error()

        dispatch_body = dict(body)
        api_key = dispatch_body.pop("api_key", None)
        if not isinstance(api_key, str) or not api_key:
            raise _unsafe_environment_error()
        # INVARIANT (OME-884): the SAME table the global-cache projection reports. Adding
        # a control here changes both the wire and the key, which is what keeps "the key
        # describes what dispatch sends" true by construction — and it is a mandatory
        # ``GLOBAL_CACHE_ADAPTER_REVISION`` bump, since older rows were keyed without it.
        dispatch_body.update(gateway_dispatch_controls())

        # Folded into GLOBAL_CACHE_ADAPTER_REVISION rather than into the key: an
        # ``Omit()`` sentinel is not JSON and the key builder refuses it. Suppressing
        # both headers is the explicit condition that licenses cross-account replay —
        # restoring either one is a mandatory revision bump.
        default_headers: dict[str, Any] = {
            "OpenAI-Organization": Omit(),
            "OpenAI-Project": Omit(),
        }
        http_client = _openai_http_client()
        try:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=OFFICIAL_API_BASE,
                max_retries=0,
                default_headers=default_headers,
                http_client=http_client,
            )
        except Exception:
            await http_client.aclose()
            raise
        dispatch_body["client"] = client
        try:
            response = cast("Any", await litellm.acompletion(**dispatch_body))
        finally:
            await client.close()

        payload = response.model_dump() if hasattr(response, "model_dump") else response
        return cast("Any", payload)


PLUGIN = OpenAIProviderPlugin()
