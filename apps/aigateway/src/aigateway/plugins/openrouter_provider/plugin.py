"""OpenRouter provider plugin (OME-428 Checkpoint A — local BYOK).

An API-key-only provider (no OAuth) routed through LiteLLM's built-in
``openrouter`` provider. Key design points (validated against litellm 1.87.0):

- Disabled by default (plan D2): a disabled plugin registers no models and
  returns no API-key strategy, so no key can be stored and every dispatch
  path fails closed through existing route handling — even for connection
  rows created while the provider was enabled.
- Exactly one gateway prefix (plan D8): the gateway ID
  ``openrouter/<author>/<model>[:variant]`` is passed to LiteLLM unchanged;
  LiteLLM's provider routing strips the single ``openrouter/`` prefix at the
  wire, so upstream receives ``<author>/<model>[:variant]`` exactly once.
  ``prepare_chat_body`` validates the upstream remainder before dispatch and
  copies the body — it never mutates the caller's dict.
- Non-streaming in every mode (plan D5): the route rejects ``stream:true``
  before credentials are read.
- Only 401 marks the stored credential unusable (plan D9); 402/403/408/429/5xx
  are provider/billing states and must not invalidate a valid key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from aigateway.core.api_key_strategy import ApiKeyStrategy
from aigateway.core.api_key_validation import ApiKeyValidator
from aigateway.core.cache_ports import CacheBypass
from aigateway.core.parameter_discovery import (
    DiscoveryHttpClient,
    DiscoveryLimits,
    DiscoverySourceRef,
)
from aigateway.core.parameter_projection import IncompatibleParametersError
from aigateway.core.plugin_base import (
    CredentialStrategy,
    ModelAdmission,
    ModelDiscoverySource,
    ModelEntry,
    ProviderPluginBase,
)
from aigateway.core.standard_parameters import (
    direct_parameter_observations,
    tool_parameter_observations,
)
from aigateway.plugins.taxonomy import (
    CacheReference,
    ProviderUsageAccountingEvidence,
    UsageAccountingStrategy,
)

from .admission import admit_openrouter_model
from .api_key_validation import OpenRouterApiKeyValidator
from .discovery import (
    LOCAL_SOURCE,
    MODEL_SOURCE,
    REVIEWED_ENDPOINT_OBSERVATIONS,
    SNAPSHOT_SOURCE_REVISION,
    discover_openrouter_snapshot,
)
from .dispatch_errors import (
    _embedded_error_exception,
    _invalid_model_error,
    _online_model_suffix_error,
    _response_conversion_exception,
    _unsafe_litellm_state_error,
)

# AIDEV-NOTE: ``X as X`` is an explicit RE-EXPORT, not a redundant alias. OME-305
# moved ``GLOBAL_CACHE_ADAPTER_REVISION`` and ``OFFICIAL_API_BASE`` out of this module
# to keep it under the size limit and to home the pure projection away from the impure
# wiring; several test modules and the dispatch path still import them from here, so
# the names must stay reachable. Removing the alias form makes ruff delete them.
from .global_cache import GLOBAL_CACHE_ADAPTER_REVISION as GLOBAL_CACHE_ADAPTER_REVISION
from .global_cache import project_global_cache_request
from .litellm_controls import (
    _has_unsafe_litellm_global_state,
    _strip_openrouter_litellm_controls,
)
from .live_models import (
    LIVE_MODELS_DISCOVERY_SOURCE,
    fetch_live_model_ids,
    live_listing_entries,
    publishable_upstream_ids,
)
from .observations import ROUTING_POLICY_OBSERVATIONS
from .parameters import openrouter_chat_parameter_rules, openrouter_chat_parameter_tools
from .provenance import converter_error_status, is_http200_body_error
from .response_errors import (
    _embedded_error_status as _embedded_error_status,
)
from .response_errors import (
    _find_embedded_error,
)
from .response_errors import (
    _top_level_error_is_meaningful as _top_level_error_is_meaningful,
)
from .routing_policy import build_provider_policy
from .settings import (
    GATEWAY_MODEL_PREFIX,
    OpenRouterPluginSettings,
    is_online_variant,
    is_valid_upstream_model_id,
)
from .settings import OFFICIAL_API_BASE as OFFICIAL_API_BASE
from .usage_accounting import (
    cache_reference_from_cached,
    normalize_openrouter_usage_accounting,
)
from .web_search import (
    WEB_SEARCH_EXCLUDED_DOMAINS_PARAM,
    WEB_SEARCH_PARAM,
    apply_web_search,
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


def _credential_service_for(profile_name: str) -> str:
    """Namespace the stored credential slot by provider + profile/connection."""
    return f"aigateway:openrouter:{profile_name}"


def _upstream_model_for_discovery(model: str) -> str | None:
    """The upstream catalog key for a gateway id, or None when there is none.

    ONE predicate shared by ``chat_discovery_source`` and
    ``discover_chat_parameter_snapshot``: the source declaration and the fetch must
    agree on exactly which ids are discoverable, or the runtime sees a provider that
    promised evidence and then reported NO ATTEMPT. It applies the SAME strip as
    ``prepare_chat_body``, so discovery and dispatch also agree on model identity.
    """
    if not model.startswith(GATEWAY_MODEL_PREFIX):
        return None
    upstream = model[len(GATEWAY_MODEL_PREFIX) :]
    return upstream if is_valid_upstream_model_id(upstream) else None


# D7: trusted attribution, injected AFTER caller-header sanitization so the
# gateway owns these keys end-to-end. LiteLLM 1.87.0 lets caller headers
# override its OR_SITE_URL/OR_APP_NAME defaults (openrouter_headers.update),
# which is exactly why the caller's copies must be dropped first.
_TRUSTED_ATTRIBUTION = {
    "HTTP-Referer": "https://screamingface.ai",
    "X-OpenRouter-Title": "ScreamingFace",
    "X-Title": "ScreamingFace",
}

# AIDEV-NOTE (OME-704): the gateway-owned strict-routing policy moved to
# routing_policy.py, which now BUILDS the whole `provider` object rather than
# assigning a constant. Its WHY/INVARIANT block moved with it, so the rationale sits
# beside the code that enforces it.

# Caller copies of auth, host/framing, and attribution headers are dropped
# before the gateway injects its own (D7). Lower-cased for comparison.
_STRIPPED_CALLER_HEADERS = frozenset(
    {
        # auth
        "authorization",
        "x-api-key",
        "proxy-authorization",
        # host / framing
        "host",
        "content-length",
        "transfer-encoding",
        # attribution (gateway-owned)
        "http-referer",
        "referer",
        "x-openrouter-title",
        "x-title",
    }
)


class OpenRouterProviderPlugin(ProviderPluginBase[OpenRouterPluginSettings]):
    custom_llm_provider = "openrouter"
    provider_display_name = "OpenRouter"
    provider_kind = "hub"
    provider_group = "hubs"
    provider_group_display_name = "Hubs"
    provider_description = "A broad model catalog behind one connection"
    provider_color = "#937098"
    provider_sort_order = 200
    settings_cls = OpenRouterPluginSettings

    def register_models(self) -> list[ModelEntry]:
        if not self.settings.enabled:
            # D2: a disabled provider exposes no models.
            return []
        return [
            ModelEntry(model_name=slug, litellm_params={"model": slug})
            for slug in self.settings.default_models
        ]

    def model_discovery_source(self) -> ModelDiscoverySource | None:
        # INVARIANT (OME-972): gated on BOTH flags — a disabled provider or
        # live_models=false declares no source, so the catalog never opens a
        # cache slot or dials for it (zero egress when off).
        if not (self.settings.enabled and self.settings.live_models):
            return None
        return LIVE_MODELS_DISCOVERY_SOURCE

    async def discover_live_models(
        self,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
    ) -> tuple[ModelEntry, ...] | None:
        """The finished live listing: operator-explicit entries, then discovered.

        Three-outcome contract (see the base hook): entries = reached; raises
        sanitized ``DiscoveryError`` = attempted and failed; None = gated off,
        not attempted, no connection.
        """
        if not (self.settings.enabled and self.settings.live_models):
            return None
        raw_ids = await fetch_live_model_ids(client=client, limits=limits)
        return live_listing_entries(self.settings, publishable_upstream_ids(raw_ids))

    async def admit_model(
        self,
        model_id: str,
        *,
        discovery_client: DiscoveryHttpClient | None,
        discovery_limits: DiscoveryLimits | None,
        catalog_cache: dict[str, Any],
        credentialed: bool,
    ) -> ModelAdmission:
        # OME-879: the decision ladder lives in `admission.py`; this override is
        # only the port wiring.
        return await admit_openrouter_model(
            model_id,
            settings=self.settings,
            client=discovery_client,
            limits=discovery_limits,
            cache=catalog_cache,
            credentialed=credentialed,
        )

    def supports_api_key(self) -> bool:
        return True

    def supports_chat_streaming(self) -> bool:
        # D5: enforced in every credential mode; the route rejects stream:true
        # before _inject_credentials so no credential is ever read for it.
        return False

    def api_key_strategy_for(
        self,
        profile_name: str,
        *,
        credential_store: CredentialBlobStore | None = None,
    ) -> CredentialStrategy | None:
        if not self.settings.enabled:
            # D2 fail closed: no strategy means the api-key connection routes
            # answer 400 api_key_not_supported and chat cannot resolve
            # credentials, without any provider branch in core.
            return None
        return ApiKeyStrategy(
            profile_name,
            service=_credential_service_for(profile_name),
            account="default",
            header_builder=lambda api_key: {"Authorization": f"Bearer {api_key}"},
            credential_store=credential_store,
        )

    def api_key_validator(self) -> ApiKeyValidator | None:
        if not self.settings.enabled:
            return None
        return OpenRouterApiKeyValidator(settings=self.settings)

    def should_mark_profile_error_on_dispatch_status(self, status_code: int) -> bool:
        # D9: only 401 proves the stored key is bad. 402 (credits), 403
        # (policy), 408/429/5xx (transient) must not invalidate a valid key.
        return status_code == 401

    def chat_parameter_rules(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ParameterProjectionRule, ...]:
        # OME-479: one provider-local source drives summary, detail, and
        # fail-closed dispatch. Adding a parameter is a change here, never in core.
        return openrouter_chat_parameter_rules(model=model, auth_type=auth_type)

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
        if WEB_SEARCH_EXCLUDED_DOMAINS_PARAM in body and body.get(WEB_SEARCH_PARAM) is not True:
            raise IncompatibleParametersError(
                (WEB_SEARCH_PARAM, WEB_SEARCH_EXCLUDED_DOMAINS_PARAM),
                reason="web_search_excluded_domains_requires_web_search_true",
            )

    def chat_parameter_tools(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ToolCapability, ...]:
        # OME-583: OpenRouter is OpenAI-compatible; the installed litellm openrouter
        # transform forwards OpenAI tools (§9), so it advertises the `function` type.
        return openrouter_chat_parameter_tools(model=model, auth_type=auth_type)

    def chat_parameter_observations(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> tuple[ProviderParameterObservation, ...]:
        # OME-479 §5.3: labelled-local endpoint evidence (NO network) so the detail
        # contract shows every accepted field with its gateway status — an unruled
        # field (e.g. top_p) stays visible-but-DISABLED (projection_not_implemented),
        # while a ruled+observed field (temperature, provider_params.top_k) is
        # ENABLED and carries its provenance. The live per-model catalog overlays
        # this via discover_chat_parameter_snapshot when request-path discovery is
        # wired; endpoint-level evidence is model-independent, so it does not vary
        # by model here.
        # OME-583: tools + tool_choice are ALSO ruled → ENABLED, evidenced here (same
        # labelled-local source) so every enabled tool path is fully backed (§4.4).
        # OME-584: response_format is likewise ruled → ENABLED, evidenced here.
        # OME-585: seed is already evidenced by the sampling constant; n (a non-sampling
        # control) is evidenced here alongside response_format — both ruled → ENABLED.
        # OME-704: the five price/privacy routing controls are ruled → ENABLED, and
        # carry their OWN source label (openrouter:routing-policy) because they are
        # evidence about routing behaviour, not about the model's sampling surface.
        # INVARIANT: an observation NEVER enables a parameter — only a rule does.
        return (
            REVIEWED_ENDPOINT_OBSERVATIONS
            + ROUTING_POLICY_OBSERVATIONS
            + tool_parameter_observations(
                openrouter_chat_parameter_tools(model=model, auth_type=auth_type),
                source=LOCAL_SOURCE,
            )
            + direct_parameter_observations(
                (
                    "response_format",
                    "n",
                    "logprobs",
                    "top_logprobs",
                    "web_search",
                    "web_search_excluded_domains",
                ),
                source=LOCAL_SOURCE,
            )
        )

    def chat_discovery_source(
        self, *, model: str, auth_type: AuthMode | None = None
    ) -> DiscoverySourceRef | None:
        # OME-632: the catalog is public and auth-INDEPENDENT — OpenRouter publishes
        # one row per model whichever credential dispatch will use — so the resolved
        # mode is accepted for port conformance and deliberately ignored.
        # OME-629: declare the public catalog BEFORE any fetch, so the observation
        # cache can judge a stored entry's trustworthiness without paying for a
        # round trip. The revision names the reading as well as the source.
        # INVARIANT: the SAME predicate gates both hooks — a model this provider
        # cannot dispatch has nothing to discover. Owning it here (rather than only
        # in the fetch) makes "declared a source, then reported NOT ATTEMPTED"
        # structurally unreachable, which is the one inconsistency the runtime
        # cannot distinguish from a real outage.
        # AIDEV-NOTE (OME-647): ``source`` is the provider's CACHE-KEY label, not a
        # published claim about which document an observation came from — that
        # provenance rides on each observation. The snapshot now draws on the
        # catalog AND the OpenAPI document, and the REVISION names the pair.
        if _upstream_model_for_discovery(model) is None:
            return None
        return DiscoverySourceRef(source=MODEL_SOURCE, revision=SNAPSHOT_SOURCE_REVISION)

    async def discover_chat_parameter_snapshot(
        self,
        *,
        model: str,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None = None,
        auth_type: AuthMode | None = None,
    ) -> ProviderDiscoverySnapshot | None:
        # OME-479 §5.1: the DYNAMIC source. Strip the gateway prefix to the
        # upstream id the public catalog is keyed by — the SAME rule as
        # prepare_chat_body, so discovery and dispatch agree on identity. A value
        # that is not a valid gateway id is not dispatchable, so there is nothing
        # to discover: return None WITHOUT opening a connection — NOT ATTEMPTED,
        # which is a different claim from "attempted and failed".
        # INVARIANT: never enables a parameter (only a rule does); off the chat
        # dispatch path; a sanitized DiscoveryError from the fetch PROPAGATES so
        # the cache can degrade honestly rather than store a failure as fresh.
        upstream = _upstream_model_for_discovery(model)
        if upstream is None:
            return None
        return await discover_openrouter_snapshot(upstream, client=client, limits=limits)

    def strip_provider_dispatch_controls(self, body: dict[str, Any]) -> dict[str, Any]:
        # OME-479: neutralize LiteLLM orchestration selectors BEFORE the
        # fail-closed classifier, so they are structurally authorized (§4.5 tier a)
        # rather than 400-rejected as unknown params. prepare_chat_body repeats
        # this strip (idempotent) as defense in depth.
        return _strip_openrouter_litellm_controls(body)

    def prepare_chat_body(self, body: dict[str, Any]) -> dict[str, Any]:
        out = _strip_openrouter_litellm_controls(body)
        model = out.get("model")
        if not isinstance(model, str) or not model.startswith(GATEWAY_MODEL_PREFIX):
            raise _invalid_model_error()
        # OME-712: BEFORE the validity check, so a `:online` id reports the specific
        # `unsupported_model_variant` rather than a generic invalid-model error. The
        # cache projection refuses the same ids via the same predicate.
        if is_online_variant(model):
            raise _online_model_suffix_error()
        if not is_valid_upstream_model_id(model[len(GATEWAY_MODEL_PREFIX) :]):
            raise _invalid_model_error()
        # Keep the model unchanged: the gateway prefix IS LiteLLM's provider
        # prefix, so LiteLLM strips it exactly once at the wire (D8).
        out.pop("api_key", None)  # gateway-owned; injected after this hook
        extra_headers = out.get("extra_headers")
        headers: dict[str, Any] = {}
        if isinstance(extra_headers, dict):
            headers = {
                key: value
                for key, value in extra_headers.items()
                if str(key).lower() not in _STRIPPED_CALLER_HEADERS
            }
        headers.update(_TRUSTED_ATTRIBUTION)
        out["extra_headers"] = headers
        # Pinned official base (D7): the ingress strip removed any caller
        # value; request-local api_base beats every LiteLLM global/env
        # fallback (litellm 1.87.0 main.py precedence).
        out["api_base"] = OFFICIAL_API_BASE
        # OME-651 + OME-704: RECONSTRUCTION, never a merge. The classifier already
        # refuses a caller `provider` as unknown, so the only thing legitimately here
        # is what projection wrote for the five reviewed routing controls — but the
        # two layers are deliberately independent, so the boundary rebuilds the
        # object from its own allowlist (re-validating each value) and forces
        # `require_parameters` last. An unexpected key or shape is refused with a
        # sanitized 503 rather than dropped: silently discarding it could silently
        # discard an accepted price ceiling or data policy. A fresh dict per request
        # keeps one caller from mutating the policy the next one gets.
        out["provider"] = build_provider_policy(out.pop("provider", None))
        apply_web_search(out)
        return out

    def global_cache_projection(self, body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
        # OME-305: delegated to ``global_cache`` so the PURE projection lives in a
        # module that holds nothing impure. See that module for the invariants.
        #
        # AIDEV-NOTE: the `enabled` gate deliberately is NOT here. It lives in
        # ``participates_in_global_cache`` below, because this method's port contract
        # is that it reads the request body ALONE — and `test_no_projection_reads_
        # operator_configuration` enforces that with a poison-settings twin. Gating
        # here would also be the wrong shape: PARTICIPATION and KEY MATERIAL are
        # separate decisions, and only the latter belongs to a pure projection.
        return project_global_cache_request(body)

    def participates_in_global_cache(self, model: object = None) -> bool:
        # D2, extended to the cache path. `register_models` and `api_key_strategy_for`
        # already fail closed when disabled, but the global cache is a SECOND way to
        # serve this provider's responses — a stored row needs no model entry and no
        # credential to be replayed, and the cache stage runs AHEAD of both checks, so
        # neither the 404 nor the 400 ever gets a chance to refuse the request.
        # Without this gate a disabled OpenRouter keeps answering from rows an enabled
        # deployment filled, indefinitely (current rows never expire).
        #
        # OME-884: the port now carries the raw requested model. This provider has no
        # per-model reason to stand down — its `:online` refusal is KEY MATERIAL and is
        # already handled by the projection's bypass — so the argument is ignored and
        # the operator gate is the whole answer, exactly as before.
        del model
        return self.settings.enabled

    def usage_accounting_strategy(self) -> UsageAccountingStrategy:
        # OME-303 §5.1: openrouter dispatches through litellm's base_llm_http_handler,
        # which uses the shared AsyncHTTPHandler and honours an injected client — so the
        # gateway's observed handler sees every generation send.
        return UsageAccountingStrategy.litellm_async_http()

    def normalize_chat_usage_accounting(
        self,
        *,
        request_body: Mapping[str, Any],
        raw_response: Mapping[str, Any] | None,
        final_response: Mapping[str, Any] | None,
        failed: bool = False,
    ) -> ProviderUsageAccountingEvidence:
        return normalize_openrouter_usage_accounting(
            request_body=request_body,
            raw_response=raw_response,
            final_response=final_response,
            failed=failed,
        )

    def cache_reference_from_cached_response(
        self, cached_response: Mapping[str, Any]
    ) -> CacheReference | None:
        # Historical final-response evidence only. It cannot prove original retry spend
        # and is never labelled as current spend or counterfactual savings.
        return cache_reference_from_cached(cached_response)

    async def chat_completion(self, body: dict[str, Any]) -> Any:
        import litellm

        # INVARIANT: process-global LiteLLM routing and callbacks must never
        # receive or redirect an account-scoped OpenRouter credential.
        if _has_unsafe_litellm_global_state(litellm, body.get("model")):
            raise _unsafe_litellm_state_error()

        dispatch_body = dict(body)
        # AIDEV-NOTE (OME-303 §4.2): this field is IGNORED whenever the gateway injects
        # its own client — LiteLLM uses the client it was given, and that client's TLS
        # was fixed when it was built. For an accounted request the active TLS guarantee
        # is ``core.usage_accounting.hooks.AccountingAsyncHTTPHandler``, which pins
        # verification on its primary AND on the replacement client litellm builds
        # during its hidden retry. This line still governs the un-accounted path.
        dispatch_body["ssl_verify"] = True
        dispatch_body["caching"] = False
        dispatch_body["cache"] = {"no-cache": True, "no-store": True}
        # OME-303 §4.3: pin the gateway-owned OUTER retry cardinality so the accounting
        # contract's observed-attempt count cannot be changed by a process-global default.
        dispatch_body["num_retries"] = 0
        dispatch_body["max_retries"] = 0

        # cast: acompletion's static type is a ModelResponse|CustomStreamWrapper
        # union, but D5 guarantees non-streaming here (stream rejected at the
        # route before dispatch), so model_dump is always present.
        try:
            response = cast("Any", await litellm.acompletion(**dispatch_body))
        except Exception as exc:
            # WHY (FINDING A): litellm 1.87.0 RAISES while converting a nominal
            # HTTP-200 body that carries a meaningful top-level error — it never
            # returns a payload for _find_embedded_error to scan below. Such an
            # error came from an already-returned, potentially billed upstream call, so
            # route it through the SAME sanitizer as a scanned embedded error:
            # non-retryable, status sanitized, raw provider text discarded.
            # INVARIANT: a genuine transport failure is re-raised unchanged so
            # the shared overload-retry loop (core.retry) still applies to it.
            if is_http200_body_error(exc):
                raise _embedded_error_exception(converter_error_status(exc)) from exc
            raise
        try:
            payload: Any = response.model_dump() if hasattr(response, "model_dump") else response
        except Exception:
            raise _response_conversion_exception() from None
        if isinstance(payload, dict):
            found, status = _find_embedded_error(payload)
            if found:
                # A 401 here flows through the route's dispatch-failure path
                # and marks only the selected connection (D9 local).
                raise _embedded_error_exception(status)
        # Return the dumped dict so native usage/cost/generation metadata
        # reaches the caller byte-for-byte (D10 — URL4 per-leaf telemetry).
        return payload


PLUGIN = OpenRouterProviderPlugin()
