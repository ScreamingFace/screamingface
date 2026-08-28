from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aigateway.core.plugin_base import ModelEntry, ProviderPluginBase

from .discovery import discover_ollama_models, resolve_ollama_host
from .parameters import (
    OLLAMA_OBSERVATIONS,
    ollama_chat_parameter_rules,
    ollama_chat_parameter_tools,
)

if TYPE_CHECKING:
    from aigateway.core.chat_parameters import (
        ParameterProjectionRule,
        ProviderParameterObservation,
        ToolCapability,
    )
    from aigateway.core.profile_models import AuthMode

_CLIENT_AUTH_HEADER_NAMES = {"authorization", "x-api-key", "proxy-authorization"}


class OllamaProviderPlugin(ProviderPluginBase):
    custom_llm_provider = "ollama"
    provider_display_name = "Ollama"
    provider_kind = "local"
    provider_group = "local_and_sessions"
    provider_group_display_name = "Local & Sessions"
    provider_description = "Local models on your machine — no API key required"
    provider_color = "#52aec5"
    provider_sort_order = 10

    def register_models(self) -> list[ModelEntry]:
        host = resolve_ollama_host()
        return [
            ModelEntry(
                model_name=f"ollama/{name}",
                litellm_params={"model": f"ollama_chat/{name}", "api_base": host},
            )
            for name in discover_ollama_models(host)
        ]

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

    def allows_chatless_profile(self) -> bool:
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


PLUGIN = OllamaProviderPlugin()
