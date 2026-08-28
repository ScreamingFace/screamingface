"""Hugging Face provider plugin for the AI Gateway (SF-345).

An API-key-only provider (no OAuth). Chat routes through LiteLLM's built-in
``huggingface`` provider against the unified OpenAI-compatible router
(``https://router.huggingface.co/v1``); the request-local HF token is injected by
the gateway as ``body["api_key"]`` and never read from the process environment.

Key design points (validated against litellm 1.87.0):
- ``register_models`` emits ``huggingface/<org>/<model>:<provider>`` entries with the
  router pinned as ``api_base``. Pinning ``api_base`` short-circuits litellm's
  per-request provider-mapping fetch to ``huggingface.co`` (which would be
  ``HUGGINGFACE_API_KEY``-env-keyed and ignore the request token).
- ``prepare_chat_body`` injects that same ``api_base`` on dispatch (the default
  ``chat_completion`` calls ``litellm.acompletion(**body)``, which does not read
  ``register_models`` params) and strips any caller-supplied auth so only the
  gateway-owned credential reaches upstream.
- Only 401 marks the stored credential unusable; 403 is ambiguous (model-access vs
  token permission) and must not nuke a valid key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.api_key_validation import ApiKeyValidator
from aigateway.core.cache_ports import CacheBypass
from aigateway.core.parameter_discovery import DiscoverySourceRef
from aigateway.core.parameter_projection import IncompatibleParametersError
from aigateway.core.plugin_base import (
    CredentialStrategy,
    ModelEntry,
    ProviderPluginBase,
)
from aigateway.core.standard_parameters import (
    direct_parameter_observations,
    tool_parameter_observations,
)

from .api_key_validation import HuggingFaceApiKeyValidator
from .discovery import (
    HF_STATIC_PARAM_OBSERVATIONS,
    ROUTER_SOURCE,
    ROUTER_SOURCE_REVISION,
    STATIC_SOURCE,
    discover_huggingface_snapshot,
)
from .global_cache import project_global_cache_request
from .parameters import huggingface_chat_parameter_rules, huggingface_chat_parameter_tools
from .runtime_guard import (
    global_cache_decline_reason,
    log_decline_once,
    reset_decline_log,  # noqa: F401  (re-exported: tests reset the guard's per-process memo)
)
from .settings import HuggingFacePluginSettings, pinned_router_target

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

# Caller-supplied copies of these are stripped before the gateway injects its own
# credential, so a client can never smuggle auth material to the upstream router.
_CLIENT_AUTH_HEADER_NAMES = {"authorization", "x-api-key", "proxy-authorization"}


def _credential_service_for(profile_name: str) -> str:
    """Namespace the stored credential slot by provider + profile/connection."""
    return f"aigateway:huggingface:{profile_name}"


class HuggingFaceProviderPlugin(ProviderPluginBase[HuggingFacePluginSettings]):
    custom_llm_provider = "huggingface"
    provider_display_name = "Hugging Face"
    provider_kind = "hub"
    provider_group = "hubs"
    provider_group_display_name = "Hubs"
    provider_description = "Hosted open-source models from Hugging Face"
    provider_color = "#f79763"
    provider_sort_order = 210
    settings_cls = HuggingFacePluginSettings

    def register_models(self) -> list[ModelEntry]:
        api_base = self.settings.router_api_base
        return [
            ModelEntry(model_name=slug, litellm_params={"model": slug, "api_base": api_base})
            for slug in self.settings.default_models
        ]

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
            service=_credential_service_for(profile_name),
            account="default",
            header_builder=lambda api_key: {"Authorization": f"Bearer {api_key}"},
            credential_store=credential_store,
        )

    def api_key_validator(self) -> ApiKeyValidator:
        return HuggingFaceApiKeyValidator(settings=self.settings)

    def should_mark_profile_error_on_dispatch_status(self, status_code: int) -> bool:
        # 401 => bad/missing token (invalidate). 403 is ambiguous (model-access vs
        # token permission) and must not invalidate a valid stored credential.
        return status_code == 401

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        # OME-479 §6.2: HF's OpenAI-compatible sampling fields, each proven through
        # the installed final transform. A rule is the ONLY thing that enables a
        # parameter; every other caller field fails closed at classification.
        return huggingface_chat_parameter_rules(model=model, auth_type=auth_type)

    def validate_chat_parameter_combination(
        self,
        body: Mapping[str, Any],
        *,
        model: str,
        auth_mode: AuthMode,
    ) -> None:
        del model, auth_mode
        if "top_logprobs" in body and body.get("logprobs") is not True:
            raise IncompatibleParametersError(
                ("logprobs", "top_logprobs"),
                reason="top_logprobs_requires_logprobs_true",
            )

    def chat_parameter_tools(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ToolCapability, ...]:
        # OME-583: HF's OpenAI-compatible router forwards tools/tool_choice through the
        # installed transform (§9), so function calling is a first-class capability —
        # reported in supported_tools and the detail contract's tools section.
        return huggingface_chat_parameter_tools(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        # OME-479 §5.1/§6.2: HF's catalog carries NO parameter list, so the ONLY
        # honest parameter evidence is labelled-static — the standard OpenAI sampling
        # fields the INSTALLED transform accepts (source "huggingface:static", NO
        # network). This makes the detail contract show every accepted field with its
        # gateway status: temperature/max_tokens are ALSO ruled → ENABLED with this
        # provenance; the rest stay visible-but-DISABLED (projection_not_implemented).
        # Endpoint-level evidence is model-independent, so it does not vary by model.
        # INVARIANT: an observation NEVER enables a parameter — only a rule does.
        # OME-583: the tools/tool_choice request-path observations are contributed here
        # (mirroring the tool rules) so §4.4 holds — every enabled tool path has a rule,
        # a schema, AND an observation — WITHOUT polluting the sampling-field constant.
        # OME-584: response_format is contributed the same way (ruled → ENABLED, evidenced).
        # OME-585: seed is already evidenced by the sampling constant; n (a non-sampling
        # control) is evidenced here alongside response_format — both ruled → ENABLED.
        return (
            HF_STATIC_PARAM_OBSERVATIONS
            + tool_parameter_observations(
                huggingface_chat_parameter_tools(model=model, auth_type=auth_type),
                source=STATIC_SOURCE,
            )
            + direct_parameter_observations(
                ("response_format", "n", "logprobs", "top_logprobs"), source=STATIC_SOURCE
            )
        )

    def chat_discovery_source(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> DiscoverySourceRef | None:
        # OME-632: Hugging Face is api-key only and its router catalog is public, so
        # the resolved mode cannot change the evidence — accepted for port
        # conformance and deliberately ignored.
        # OME-631: declare the public router catalog BEFORE any fetch, so the
        # observation cache can judge a stored entry's trustworthiness without
        # paying for a round trip.
        # INVARIANT: the SAME predicate gates both hooks. Owning it here (rather
        # than only in the fetch) makes "declared a source, then reported NOT
        # ATTEMPTED" structurally unreachable — the one inconsistency the runtime
        # cannot distinguish from a real outage.
        if pinned_router_target(model) is None:
            return None
        return DiscoverySourceRef(source=ROUTER_SOURCE, revision=ROUTER_SOURCE_REVISION)

    async def discover_chat_parameter_snapshot(
        self,
        *,
        model: str,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth_type: AuthMode | None = None,
    ) -> ProviderDiscoverySnapshot | None:
        # OME-479 §6.2: the DYNAMIC source. The catalog is keyed by the bare
        # <org>/<model>, and the pinned :<backend> selects one row inside it — so a
        # gateway id that pins no backend has nothing single-backend to discover and
        # returns None WITHOUT opening a connection (NOT ATTEMPTED, a different
        # claim from "attempted and failed").
        # INVARIANT: never enables a parameter or a tool (only a rule does); off the
        # chat dispatch path; a sanitized DiscoveryError PROPAGATES so the cache can
        # degrade honestly rather than store a failure as fresh.
        target = pinned_router_target(model)
        if target is None:
            return None
        upstream, backend = target
        return await discover_huggingface_snapshot(
            upstream, backend=backend, client=client, limits=limits
        )

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        out = dict(body)
        # The gateway owns the key; a caller copy would be overwritten by injection
        # anyway, but drop it explicitly for defense in depth.
        out.pop("api_key", None)
        extra_headers = out.get("extra_headers")
        if isinstance(extra_headers, dict):
            sanitized = {
                key: value
                for key, value in extra_headers.items()
                if str(key).lower() not in _CLIENT_AUTH_HEADER_NAMES
            }
            if sanitized:
                out["extra_headers"] = sanitized
            else:
                out.pop("extra_headers", None)
        elif "extra_headers" in out:
            # A non-dict extra_headers would crash the downstream handler; drop it.
            out.pop("extra_headers", None)
        # Gateway-owned router base. routes/chat.py strips the caller's api_base
        # first, then we set our own; this keeps litellm on the request-local path.
        out["api_base"] = self.settings.router_api_base
        return out

    # ---- OME-791: global exact-response cache (OME-305) ------------------------------

    def global_cache_projection(self, body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        """Delegate to the PURE module; see ``global_cache.py`` for the invariants."""
        return project_global_cache_request(body)

    def participates_in_global_cache(self, model: object = None) -> bool:
        """Whether THIS deployment's rows may be shared, given state the projection cannot see.

        INVARIANT: the projection describes a request sent to the OFFICIAL router by a process
        with no ambient LiteLLM interference. This hook is what makes that description true, by
        declining whenever it would not be. A ``False`` answer is fail-safe and LOSSLESS — it
        suppresses the lookup without invalidating, rewriting or re-keying any stored row.

        WHY the port licenses this to read deployment-local state (``_provider.py:299-317``)
        while the projection may not: the projection's output is hashed into a globally shared
        key, so anything it reads must be identical everywhere. Participation is a local
        yes/no that never enters a key.

        INVARIANT: TOTAL in practice — ``global_plan.py:72-77`` swallows any raise here into
        non-participation, and the guard must never be the thing that fails a request.

        AIDEV-NOTE (M5): the decision itself lives in ``runtime_guard.py`` — ONE Hugging Face
        source of truth for every ambient and configuration condition. This hook only supplies
        the deployment-local value the guard may not read for itself and reports the outcome.

        OME-884 passes the raw model through this port. HF deliberately keeps the existing
        deployment-wide fail-closed predicate for now; narrowing individual alias-map entries is
        a separate cross-provider runtime-guard follow-up.
        """
        del model
        reason = global_cache_decline_reason(
            configured_router_api_base=self.settings.router_api_base
        )
        if reason is None:
            return True
        log_decline_once(reason)
        return False

    def cache_reference_from_cached_response(self, cached: Mapping[str, Any]) -> None:
        """No usage-accounting reference for HF — and saying so explicitly is REQUIRED.

        AIDEV-NOTE: not decoration. ``plugins/taxonomy/session.py:374`` reaches this hook
        through ``getattr`` inside a ``try/except Exception`` and there is no base-class
        default, so a provider that simply omits it logs "cache-reference mapper failed
        provider=huggingface" on EVERY hit — an operator-visible failure that never happened.
        HF owns no usage-accounting strategy (unlike anthropic and openrouter, each of which has
        a ``usage_accounting.py``), so there is nothing truthful to attach and ``None`` is the
        honest answer. Building one is out of scope for OME-791.
        """
        return None


PLUGIN = HuggingFaceProviderPlugin()
