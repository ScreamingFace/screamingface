"""OpenRouter chat-parameter rules (OME-479 §6.1) — currently-proven set only.

INVARIANT: every rule here is backed by a capture/boundary test proving the
field reaches OpenRouter dispatch, so enabling it is earned, not speculative
(plan §12). INVARIANT: every rule here also carries a validation schema — an
enabled ordinary parameter that cannot be validated is not enabled at all
(OME-646). Standard sampling fields are ``direct``; ``top_k`` — not a standard
OpenAI param for OpenRouter — is the P0 promotion, projected through
``extra_body`` where the installed litellm transform carries it onto the wire
(proven in tests).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ParameterSchema,
    ProviderParameterObservation,
    ToolCapability,
)
from aigateway.core.parameter_projection import WRAPPER_KEY, IncompatibleParametersError
from aigateway.core.profile_models import AuthMode
from aigateway.core.standard_parameters import (
    LOGPROBS_SCHEMA,
    MAX_TOKENS_SCHEMA,
    N_SCHEMA,
    PENALTY_SCHEMA,
    RESPONSE_FORMAT_SCHEMA,
    SEED_SCHEMA,
    STOP_SCHEMA,
    TEMPERATURE_SCHEMA,
    TOP_LOGPROBS_SCHEMA,
    TOP_P_SCHEMA,
    WEB_SEARCH_EXCLUDED_DOMAINS_SCHEMA,
    WEB_SEARCH_SCHEMA,
    direct_parameter_observations,
    direct_rule,
    function_calling_rules,
    provider_native_rule,
    tool_parameter_observations,
)

from .discovery import REVIEWED_ENDPOINT_OBSERVATIONS
from .observations import LOCAL_SOURCE, ROUTING_POLICY_OBSERVATIONS
from .routing_policy import routing_policy_rules
from .web_search import WEB_SEARCH_EXCLUDED_DOMAINS_PARAM, WEB_SEARCH_PARAM

# OpenRouter is API-key only (no OAuth); its auth-mode intersection is a single
# mode, so every proven rule is enabled under it.
_AUTH: tuple[AuthMode, ...] = ("api_key",)
# AIDEV-NOTE (OME-305, owner decision B — READ BEFORE CHANGING A ``cache_behavior``).
# The output-affecting rules below state ``cache_behavior="keyed"`` EXPLICITLY: their
# values change the response, so they must be in the global fingerprint or two callers
# who sent different values would share one entry. This provider is one of only two
# that carry keyed rules, and the reason is a PRECONDITION rather than a preference —
# it implements ``global_cache_projection``. A provider without that port bypasses at
# the projection step no matter what its rules say, so ``keyed`` there would advertise
# a cacheable parameter that can never be cached (see the sibling note in the
# non-projecting providers' rule files).
#
# ``tools`` and ``tool_choice`` are NOT keyed anywhere and must stay that way: their
# presence bypasses structurally, ahead of any rule, via ``PRESENCE_BYPASS_REASONS``.

# Bump when a projection's semantics change; folds into the contract digests.
_REVISION = "openrouter-2026-07"

# WHY: OpenRouter documents ``top_k`` as an integer "0 or above" (0 disables top-k
# sampling) and the installed litellm transform forwards 0 verbatim (§9 probe), so
# OpenRouter binds its OWN minimum=0 schema. Do NOT widen the shared ``TOP_K_SCHEMA``
# (minimum=1) — Anthropic and Gemini still bind it and their top-k lower bound is 1.
OPENROUTER_TOP_K_SCHEMA = ParameterSchema(type="integer", minimum=0)

# WHY (OME-993): only the low/medium/high ladder is proven through the installed
# litellm openrouter transform (§9 probe: the value reaches the wire top-level for
# reasoning-capable models) — "none"/"minimal" are other providers' spellings and
# stay fail-closed rather than dispatching an unproven value. Do NOT bind the shared
# ``REASONING_EFFORT_SCHEMA`` here; its wider enum belongs to the providers that
# proved it. litellm raises UnsupportedParamsError for non-reasoning models at
# dispatch — a named upstream error, not a gateway fail-open.
OPENROUTER_REASONING_EFFORT_SCHEMA = ParameterSchema(type="string", enum=("low", "medium", "high"))

# OME-305: the ONE spelling of where `top_k` lands upstream, shared with
# ``global_cache`` so the rule's target and the cache projection cannot drift.
#
# WHY a shared constant rather than two literals: drift here does not fail loudly.
# The key builder's presence check is ROOT-only — it asks whether `extra_body`
# appears in the projected `prepared`, and trusts the provider for what is inside.
# A projection emitting a different root would therefore turn every `top_k` request
# into a silent `unprojected_parameter` bypass (correct, but permanently uncacheable
# and invisible), and a projection emitting the root WITHOUT this leaf would be worse
# still: `top_k=3` and `top_k=7` would share one key.
EXTRA_BODY_OBJECT = "extra_body"
TOP_K_LEAF = "top_k"

# OME-583: OpenRouter is OpenAI-compatible; the INSTALLED litellm openrouter transform
# forwards tools[] and tool_choice onto the wire (§9), so function calling is enabled
# WITH tool_choice.
_TOOL_CAPABILITIES: tuple[ToolCapability, ...] = (
    ToolCapability(tool_type="function", provider_support="supported", gateway_status="enabled"),
    # AIDEV-NOTE: `openrouter:web_search` / `openrouter:web_fetch` are deliberately ABSENT.
    # OpenRouter documents that server-tool surface, but the 2026-07-31 conformance probe through
    # this Gateway's pinned LiteLLM/provider path returned HTTP 200 without search evidence.
    # Server-side web search in this landing uses the separately proven `web_search` rule below.
    # Advertising another surface requires fresh end-to-end evidence; it is not a compatibility
    # fallback for the proven plugin projection.
)

# --- server-side web search --------------------------------------------------
# OpenRouter retrieves through `plugins: [{"id": "web", ...}]`, and `plugins` stays REFUSED as a
# caller path (OME-646, pinned by `test_openrouter_security`). That is not an obstacle worked
# around here — it is correct, and the reason is worth stating: `plugins` is an extensibility
# ENVELOPE. Carrying arbitrary provider extensions is its entire purpose, so no schema can bound
# it without defeating it, and a rule enabling it forwards nested JSON verbatim.
#
# The caller instead says `web_search: true` — bounded completely, because it is a boolean — and
# `plugin.prepare_chat_body` ASSIGNS the `plugins` payload from gateway-owned policy, the same
# two-layer shape `provider` already uses: the classifier refuses the native field, the provider
# sets it. The caller can never reach the envelope.
#
# AIDEV-NOTE (OME-781, owner decision D2 — READ BEFORE REOPENING A ``cache_behavior`` HERE). Both
# search rules now declare ``cache_behavior="keyed"``, like every other output-affecting rule in
# this file. They were ``bypass`` under OME-712, because the dispatched envelope's
# `exclude_domains` used to be the UNION of the caller's list and a DEPLOYMENT setting
# (``AIGW_OPENROUTER_WEB_SEARCH_EXCLUDED_DOMAINS``) the cache key could never see — exactly the
# shape ruling 34 names: identical bodies, one key, two different upstream calls.
#
# WHY keying is now correct: OME-781 DELETED that setting. The body is the sole source of
# blocked domains, so the emitted `plugins` envelope is a pure function of the two caller
# fields `web_search` and `web_search_excluded_domains` alone — and both are already keyed
# leaves. Two requests that hash to the same key therefore carry the same envelope and
# therefore dispatch the same upstream call, which is the property every other keyed rule in
# this file already relies on. Envelope-shaping constants (`_WEB_SEARCH_POLICY`'s `id`/`engine`,
# the OME-712 `:online` refusal) are not caller-observable, so they fold into
# ``GLOBAL_CACHE_ADAPTER_REVISION`` in ``global_cache.py`` rather than into the key.
#
# INVARIANT this rests on: the `plugins` envelope is emitted ONLY when `web_search is True`
# (``web_search.apply_web_search`` returns early otherwise), and both source fields it reads are
# popped from the body and nowhere else. So a cached hit and a fresh dispatch of the same keyed
# body produce the identical envelope.
#
# INVARIANT: ``apply_web_search`` must never regain a non-body input (a settings object, a
# clock, anything not in the request) without re-opening this decision — that is what makes the
# envelope a pure function of two keyed fields rather than something a stored key can silently
# stop describing. See the signature-shape tripwire in
# ``tests/unit/openrouter/test_openrouter_web_search_keyed.py``.
#
# Retrieval remaining time-varying is an accepted property of every OTHER keyed field too (a
# repeat `temperature` request can land on a different upstream endpoint); it was never a
# reason unique to search, and is not restated here.

_RULES: tuple[ParameterProjectionRule, ...] = (
    direct_rule(
        "temperature",
        auth_modes=_AUTH,
        schema=TEMPERATURE_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # OME-479 (closure Unit 2): the P0 promotion of a genuinely observed-but-unruled
    # field. `top_p` was reported by this provider's own evidence (openrouter:static,
    # supported) while no rule authorized it, so the gateway published it as
    # visible-but-disabled and rejected it at dispatch. Enabling it is exactly this one
    # provider-local rule — no shared core/route edit — because the installed litellm
    # openrouter transform forwards the value VERBATIM onto the wire, including the 0.0
    # and 1.0 boundaries (§9 probe against litellm 1.87.0), and OpenRouter's accepted
    # range IS the standard OpenAI [0, 1], so the SHARED schema binds unchanged.
    # Contrast OPENROUTER_TOP_K_SCHEMA below, which exists only because OpenRouter's
    # top_k floor genuinely differs from the shared one.
    direct_rule(
        "top_p",
        auth_modes=_AUTH,
        schema=TOP_P_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "max_tokens",
        auth_modes=_AUTH,
        schema=MAX_TOKENS_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # OME-993: the DRACO judge's reasoning throttle. Direct passthrough — the installed
    # litellm openrouter transform forwards the standard field verbatim onto the wire
    # (§9 probe, tripwire in test_openrouter_parameter_projection). Output-affecting,
    # so keyed like every other sampling control.
    direct_rule(
        "reasoning_effort",
        auth_modes=_AUTH,
        schema=OPENROUTER_REASONING_EFFORT_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # direct: standard stop (string | array[string]); the installed litellm OpenRouter
    # path forwards it as the OpenAI-native `stop` (proven in test_openrouter_dispatch).
    direct_rule(
        "stop",
        auth_modes=_AUTH,
        schema=STOP_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # OME-584: structured output. The installed litellm OpenRouter transform forwards
    # response_format VERBATIM (§9 probe: both json_object and json_schema reach the wire
    # unchanged), so it is a direct passthrough gated by the shared response-format schema.
    direct_rule(
        "response_format",
        auth_modes=_AUTH,
        schema=RESPONSE_FORMAT_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # OME-585: seed + n sampling controls. The installed litellm OpenRouter transform
    # forwards both VERBATIM (§9 probe), so each is a direct passthrough gated by its
    # bounded integer schema (seed: any int; n: >= 1).
    direct_rule(
        "seed",
        auth_modes=_AUTH,
        schema=SEED_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "n",
        auth_modes=_AUTH,
        schema=N_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # OME-586: frequency_penalty + presence_penalty repetition controls. The installed
    # litellm OpenRouter transform forwards both VERBATIM (§9 probe), so each is a direct
    # passthrough gated by the shared [-2, 2] penalty schema.
    direct_rule(
        "frequency_penalty",
        auth_modes=_AUTH,
        schema=PENALTY_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "presence_penalty",
        auth_modes=_AUTH,
        schema=PENALTY_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # OME-595: logprobs + top_logprobs output-introspection controls. The installed litellm
    # OpenRouter transform forwards both VERBATIM (§9 probe), so each is a direct passthrough:
    # logprobs gated as a boolean, top_logprobs as a bounded integer (0..20).
    direct_rule(
        "logprobs",
        auth_modes=_AUTH,
        schema=LOGPROBS_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "top_logprobs",
        auth_modes=_AUTH,
        schema=TOP_LOGPROBS_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # AIDEV-NOTE (OME-646): `provider`, `plugins`, `route` and `models` were enabled here
    # by schema-less rules. `_accept` validates only when `rule.parameter_schema is not
    # None`, so each authorized a path and forwarded arbitrary nested JSON verbatim —
    # while §Definition of done requires every enabled ordinary parameter to declare a
    # gateway-owned validation schema, and Excluded scope names fallbacks and arbitrary
    # provider controls outright. `route: "fallback"` and `models: [...]` are OpenRouter's
    # server-side fallback controls; `provider` carries `allow_fallbacks`. Both readings
    # forbid the rules, so they are gone and the fields now fail closed with a named 400.
    # Re-enabling any of them needs an approved bounded schema per field — a permissive
    # object/array union added just to satisfy the conformance gate is NOT that.
    provider_native_rule(
        f"{WRAPPER_KEY}.{TOP_K_LEAF}",
        provider_target=f"{EXTRA_BODY_OBJECT}.{TOP_K_LEAF}",
        auth_modes=_AUTH,
        schema=OPENROUTER_TOP_K_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # OME-704: the reviewed price + privacy routing controls. Note what this is NOT:
    # it is not a rule for `provider`. The five leaves each own ONE documented
    # `provider.*` location, and the plugin RECONSTRUCTS the upstream object from
    # that allowlist — so the excluded members of `provider` (order / only / ignore
    # / allow_fallbacks / quantizations) stay unreachable, and the gateway-owned
    # `require_parameters` stays gateway-owned. The table, the schemas and the
    # per-control rationale live in routing_policy.py.
    *routing_policy_rules(auth_modes=_AUTH, projection_revision=_REVISION),
    # OME-583: tools + tool_choice (OpenAI-native, §9 proof).
    # OME-787: opted into cache keying — this provider has a real
    # `global_cache_projection` (below), so its tool rules can actually be backed.
    *function_calling_rules(
        _TOOL_CAPABILITIES,
        auth_modes=_AUTH,
        projection_revision=_REVISION,
        cache_behavior="keyed",
    ),
    # Server-side web search — the caller-facing half. `direct` is the ADDRESSING kind, not the
    # wire shape: `prepare_chat_body` consumes both fields and emits `plugins` in their place,
    # so neither name reaches OpenRouter. Verified live 2026-07-31 (litellm 1.87.0) that the
    # emitted `plugins` retrieves: same prompt, with it a current cited answer, without it the
    # model's training cutoff.
    direct_rule(
        "web_search",
        auth_modes=_AUTH,
        schema=WEB_SEARCH_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "web_search_excluded_domains",
        auth_modes=_AUTH,
        schema=WEB_SEARCH_EXCLUDED_DOMAINS_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
)


def openrouter_chat_parameter_rules(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ParameterProjectionRule, ...]:
    """The proven rule set is identical for every OpenRouter model; auth-mode
    filtering is applied by the core classifier/contract, not here."""
    return _RULES


def openrouter_chat_parameter_tools(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ToolCapability, ...]:
    # OME-583: the accepted tools[].type discriminator(s); drives supported_tools +
    # the detail contract's tools section.
    return _TOOL_CAPABILITIES


def validate_openrouter_parameter_combination(body: Mapping[str, Any]) -> None:
    """Refuse combinations that are individually legal and jointly meaningless.

    Each rule above validates ONE field, so a dependency between two of them has no
    other place to live: the classifier accepts both, and only this check can see the
    pair. Raising here keeps the refusal off the dispatch path entirely.
    """
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


def openrouter_chat_parameter_observations(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ProviderParameterObservation, ...]:
    """Labelled-local endpoint evidence (NO network) for the detail contract.

    OME-479 §5.3: every accepted field shows its gateway status — an unruled field
    (e.g. top_p) stays visible-but-DISABLED (``projection_not_implemented``), while a
    ruled+observed field (temperature, ``provider_params.top_k``) is ENABLED and
    carries its provenance. The live per-model catalog overlays this via
    ``discover_openrouter_chat_snapshot``; endpoint-level evidence is
    model-independent, so it does not vary by model here.

    OME-583: tools + tool_choice are ALSO ruled → ENABLED, evidenced here (same
    labelled-local source) so every enabled tool path is fully backed (§4.4).
    OME-584: response_format is likewise ruled → ENABLED, evidenced here.
    OME-585: seed is already evidenced by the sampling constant; n (a non-sampling
    control) is evidenced here alongside response_format — both ruled → ENABLED.
    OME-704: the five price/privacy routing controls are ruled → ENABLED, and carry
    their OWN source label (openrouter:routing-policy) because they are evidence
    about routing behaviour, not about the model's sampling surface.

    # INVARIANT: an observation NEVER enables a parameter — only a rule does.
    """
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
