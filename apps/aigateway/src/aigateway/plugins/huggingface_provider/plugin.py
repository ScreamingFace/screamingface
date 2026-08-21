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

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import litellm

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
from .settings import (
    OFFICIAL_ROUTER_API_BASE,
    HuggingFacePluginSettings,
    pinned_router_target,
)

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

logger = logging.getLogger(__name__)

# Process-global LiteLLM controls that would make a stored HF row describe something other
# than what dispatch actually sent.
#
# AIDEV-NOTE: this is the THIRD near-copy of this predicate in the repo — see
# ``openai_provider/plugin.py::_has_unsafe_litellm_global_state`` and
# ``openrouter_provider/litellm_controls.py::_has_unsafe_litellm_global_state``. Extracting one
# core helper is the right cleanup and is deliberately deferred: the three condition sets are
# NOT identical, because each provider's reachable litellm surface differs, so a shared helper
# needs a union plus per-provider deltas. Until that exists, a change to any one of the three
# should be mirrored in the others.
_LITELLM_GLOBAL_RULE_FIELDS = (
    # ``pre_call_rules``/``post_call_rules`` only ever RAISE
    # (``litellm_core_utils/rules.py:29-58``), so they cannot corrupt a response body. They are
    # guarded anyway for a different reason: a cache HIT returns at ``routes/chat.py:351``,
    # BEFORE dispatch, so a deployment's configured refusal would be silently skipped for a
    # stored row while still applying to a miss.
    "pre_call_rules",
    "post_call_rules",
    # These change WHICH PARAMETERS reach the wire, so the same body produces two different
    # upstream calls depending on process configuration.
    "drop_params",
    "additional_drop_params",
)

_LITELLM_GLOBAL_CALLBACK_FIELDS = (
    "callbacks",
    "input_callback",
    "success_callback",
    "failure_callback",
    "_async_input_callback",
    "_async_success_callback",
    "_async_failure_callback",
)


def _unsafe_litellm_global_state() -> str | None:
    """The ambient LiteLLM control that forbids sharing rows, or ``None`` if the process is clean.

    WHY this gate exists — the load-bearing case, verified against installed litellm 1.97.0
    rather than assumed. ``litellm.model_fallbacks`` is read at ``main.py:602``, INSIDE
    ``async def acompletion`` (lines 388-698), which is exactly what HF's inherited
    ``chat_completion`` calls:

        fallbacks = fallbacks or litellm.model_fallbacks
        if fallbacks is not None:
            response = await async_completion_with_fallbacks(...)

    ``fallback_utils.py:57,62`` then re-enters ``acompletion`` with ``model=fallback``. The
    gateway strips a caller's ``fallbacks`` at ingress (``request_hardening.py:82``), so only
    the process global can set it, and the fill path stores any answer carrying a
    ``finish_reason`` without comparing its model to the key's. One process-global setting
    therefore writes ANOTHER MODEL'S ANSWER under an HF key, in a store whose rows never
    expire. That is a wrong answer, not a stale one — which is why a coarse provider-wide
    decline is the right trade rather than an optimisation to be avoided.

    ``litellm.headers`` is guarded because it reaches the HF wire SPECIFICALLY: ``main.py:2994``
    inside ``_complete_huggingface`` does ``hf_headers = headers or litellm.headers``. Two
    processes with different globals would key alike and send differently — ruling 34's exact
    hazard.

    AIDEV-NOTE: ``litellm.HuggingFaceChatConfig().get_config()`` was considered and REJECTED.
    ``_complete_huggingface`` (``main.py:2971-3011``) reads no ``*Config.get_config()`` at all,
    and ``BaseConfig.get_config`` reads only ``cls.__dict__``, so the condition cannot fire on
    anything reaching the HF wire — while merely EVALUATING it instantiates the class, whose
    ``__init__`` sets ``self.__class__._is_base_class = False`` and thus mutates litellm process
    state on every request. A guard that protects nothing and mutates shared state is strictly
    worse than no guard.
    """
    if getattr(litellm, "model_fallbacks", None):
        return "litellm.model_fallbacks"
    # Coarser than both exemplars, which test ``model in aliases``. WHY: this port's signature
    # receives NO model (``_provider.py:278``), so the exact form is not expressible here. The
    # coarse form is the fail-safe direction — it declines more often, never less — and the
    # narrowing belongs to the OME-884 forward-merge, which changes this signature anyway.
    if getattr(litellm, "model_alias_map", None):
        return "litellm.model_alias_map"
    if getattr(litellm, "headers", None):
        return "litellm.headers"
    if getattr(litellm, "proxy_auth", None) is not None:
        return "litellm.proxy_auth"
    for field in _LITELLM_GLOBAL_RULE_FIELDS:
        if getattr(litellm, field, None):
            return f"litellm.{field}"
    for field in _LITELLM_GLOBAL_CALLBACK_FIELDS:
        callbacks = getattr(litellm, field, None)
        # ``"cache"`` is litellm's own bookkeeping entry, not a third-party observer; both
        # existing exemplars permit it, and excluding it would decline in ordinary deployments.
        if callbacks and any(callback != "cache" for callback in callbacks):
            return f"litellm.{field}"
    return None


# WHY module state for logging: every decline path publishes the SAME wire reason
# (``provider_projection``), so without a log an operator whose HF caching silently stopped has
# no way to learn which check declined. But this runs per request, so an unconditional warning
# would be its own operational problem. One line per condition per process is the compromise.
_LOGGED_DECLINES: set[str] = set()


def _log_decline_once(reason: str) -> None:
    """Name the declining condition once per process, never the configured value.

    INVARIANT: the TOKEN only. ``router_api_base`` can carry an internal hostname, and
    ``litellm.headers`` can carry tenant or auth material, so neither value is ever logged.
    """
    if reason in _LOGGED_DECLINES:
        return
    _LOGGED_DECLINES.add(reason)
    logger.warning(
        "huggingface is not participating in the global cache: %s (this deployment's rows "
        "are neither read nor written; requests dispatch normally)",
        reason,
    )


def reset_decline_log() -> None:
    """Clear the once-per-process log memo. For tests only."""
    _LOGGED_DECLINES.clear()


def _credential_service_for(profile_name: str) -> str:
    """Namespace the stored credential slot by provider + profile/connection."""
    return f"aigateway:huggingface:{profile_name}"


class HuggingFaceProviderPlugin(ProviderPluginBase[HuggingFacePluginSettings]):
    custom_llm_provider = "huggingface"
    provider_display_name = "Hugging Face"
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

    def participates_in_global_cache(self) -> bool:
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
        """
        reason = self._global_cache_decline_reason()
        if reason is None:
            return True
        _log_decline_once(reason)
        return False

    def _global_cache_decline_reason(self) -> str | None:
        """The condition that declines participation, or ``None`` to participate."""
        # D3 — the operator-overridable router base. The projection emits the OFFICIAL constant
        # unconditionally, so a deployment pointed anywhere else would key its requests as
        # though they had gone to the official router and share rows with deployments that did.
        # That is cross-endpoint contamination of a globally shared cache.
        #
        # WHY the comparison is NORMALISED rather than literal: litellm's
        # ``_build_chat_completion_url`` does ``model_url.rstrip("/")`` before appending
        # ``/chat/completions`` (``transformation.py:26-28``), so a trailing slash produces a
        # byte-identical upstream call. A literal ``!=`` would silently disable caching for a
        # deployment that is provably sending the same request. The normalisation stops there on
        # purpose: this is a safety gate, so every accepted spelling must be provably
        # wire-equivalent, not merely plausible. Anything else declines.
        # AIDEV-NOTE: OBSERVED TO FIRE. This gate was neutralised on 2026-08-20 and
        # ``test_a_row_filled_at_the_official_base_is_not_replayed_after_an_override`` was run.
        # Observed symptom: the deployment configured for ``https://proxy.internal/v1`` was
        # served ``X-AIGW-Cache: hit`` from the row a DIFFERENT deployment filled against the
        # official router — a 200 carrying an answer its own upstream never produced, with no
        # dispatch. That is the cross-endpoint contamination this gate exists to prevent, and it
        # is silent on the wire. Gate restored.
        configured = self.settings.router_api_base
        if not isinstance(configured, str):
            return "router_api_base"
        if configured.rstrip("/") != OFFICIAL_ROUTER_API_BASE.rstrip("/"):
            return "router_api_base"
        return _unsafe_litellm_global_state()

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
