from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aigateway.core.content_parts import check_messages
from aigateway.core.parameter_discovery import DiscoveryError, DiscoveryPostClient
from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase

from .discovery import (
    discover_ollama_models,
    discover_ollama_show_modalities,
    ollama_model_discovery_source,
    resolve_ollama_host,
)
from .parameters import (
    OLLAMA_OBSERVATIONS,
    ollama_chat_parameter_rules,
    ollama_chat_parameter_tools,
)

if TYPE_CHECKING:
    from aigateway.core.auth_types import AuthMode
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderParameterObservation,
        ToolCapability,
    )
    from aigateway.core.input_modalities import InputModality
    from aigateway.core.parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
    from aigateway.core.plugin_base import ModelDiscoverySource

_CLIENT_AUTH_HEADER_NAMES = {"authorization", "x-api-key", "proxy-authorization"}


_OLLAMA_MEDIA_ROLES = frozenset({"system", "user", "assistant", "tool"})


class OllamaProviderPlugin(ProviderPluginBase):
    custom_llm_provider = "ollama"
    provider_display_name = "Ollama"

    def register_models(self) -> list[ModelEntry]:
        # INVARIANT (OME-1537 review): seeds only — NO ``/api/show`` probe here. The
        # seeds are text-only; modality evidence comes from the async listing source
        # below, which the discovery kill switch silences.
        host = resolve_ollama_host()
        return [_seed(host, name) for name in discover_ollama_models(host)]

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        return ollama_model_discovery_source(resolve_ollama_host())

    async def discover_live_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
    ) -> tuple[ModelEntry, ...] | None:
        """The installed models, enriched with bounded ``/api/show`` evidence (OME-1537).

        INVARIANT: never changes WHAT is listed — exactly the seeds, in order; only
        ``input_modalities`` is filled. Any failed probe raises sanitized, so the
        catalog keeps its last-good snapshot (or falls back to the text-only seeds).
        """
        host = resolve_ollama_host()
        # WHY a worker thread: the tag listing is the sync, cached ``/api/tags`` call
        # ``register_models`` shares — kept off the event loop here.
        names = await asyncio.to_thread(discover_ollama_models, host)
        if not names:
            return ()
        if not isinstance(client, DiscoveryPostClient):
            raise DiscoveryError("unsupported_transport")
        evidence = await discover_ollama_show_modalities(host, names, client=client, limits=limits)
        return tuple(_seed(host, name, input_modalities=evidence.get(name)) for name in names)

    def conformance_models(self) -> list[ModelEntry]:
        models = self.register_models()
        if models:
            return models
        host = resolve_ollama_host()
        # INVARIANT: this representative exercises provider-owned rules only; it is
        # never returned by register_models and therefore cannot reach runtime routes.
        return [
            ModelEntry(
                model_name="ollama/__conformance__",
                litellm_params={
                    "model": "ollama_chat/__conformance__",
                    "api_base": host,
                },
            )
        ]

    def allows_chatless_credential(self) -> bool:
        return True

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        # OME-636: enabled strictly from what LiteLLM's OllamaChatConfig mapping
        # emits — see parameters.py for the per-field evidence and for the two
        # deliberate exclusions (tool_choice, frequency_penalty).
        # AIDEV-NOTE: available_auth_modes() resolves to ("none",) here because this
        # plugin declares neither oauth_config() nor supports_api_key(). The rules
        # apply to that mode alone; adding either declaration would strand them.
        return ollama_chat_parameter_rules(model=model, auth_type=auth_type)

    def chat_parameter_tools(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ToolCapability, ...]:
        return ollama_chat_parameter_tools(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        # A local Ollama host publishes no machine-readable parameter schema to the
        # gateway, so the evidence is the reviewed LiteLLM mapping under Ollama's
        # own source label.
        # INVARIANT: an observation NEVER enables a parameter; only a rule does.
        return OLLAMA_OBSERVATIONS

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """Sanitize caller auth and adapt Ollama model/api_base for LiteLLM."""
        # INVARIANT (OME-1529): LiteLLM's ollama_chat conversion keeps only `image_url` parts
        # (base64, from any role) and discards `file` parts; a remote URL would be passed on as
        # if it were base64. Refuse both with the typed 422 before dispatch — never a silent drop.
        check_messages(
            body.get("messages") or [],
            provider="ollama",
            media_roles=_OLLAMA_MEDIA_ROLES,
            allow_remote_images=False,
            allow_files=False,
        )
        out = dict(body)
        out.pop("api_key", None)
        extra_headers = out.get("extra_headers")
        if isinstance(extra_headers, dict):
            sanitized_headers = {
                key: value
                for key, value in extra_headers.items()
                if str(key).lower() not in _CLIENT_AUTH_HEADER_NAMES
            }
            if sanitized_headers:
                out["extra_headers"] = sanitized_headers
            else:
                out.pop("extra_headers", None)
        elif "extra_headers" in out:
            out.pop("extra_headers", None)

        out["api_base"] = resolve_ollama_host()
        model = out.get("model")
        if isinstance(model, str) and model.startswith("ollama/"):
            out["model"] = f"ollama_chat/{model.split('/', 1)[1]}"
        # routes/chat.py resolves the provider before this rewrite; do not
        # re-derive the provider from body["model"] after this point.
        return out


def _seed(
    host: str, name: str, *, input_modalities: tuple[InputModality, ...] | None = None
) -> ModelEntry:
    return ModelEntry(
        model_name=f"ollama/{name}",
        litellm_params={"model": f"ollama_chat/{name}", "api_base": host},
        input_modalities=input_modalities,
    )


PLUGIN = OllamaProviderPlugin()
