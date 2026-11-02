"""Antigravity chat-parameter rules (OME-634, OME-479 §Phase 9) — proven set only.

INVARIANT: every rule here is backed by a characterization test that runs the
request pipeline and proves the value reaches ``build_generate_content_body`` — the
last AIGateway-owned boundary before the Code Assist wire body — so enabling it is
earned, not speculative (§6.2, §9).

INVARIANT: Antigravity is OAuth-ONLY (``supports_api_key()`` is ``False``), so every
rule declares that single mode. Publishing an api-key mode would advertise a path
dispatch cannot take.

Two shapes of enabled field, exactly as the builder reads them:

- STANDARD OpenAI fields its ``config_map`` renames (``temperature``,
  ``top_p`` → ``topP``, ``max_tokens`` → ``maxOutputTokens``) plus ``stop`` →
  ``stopSequences`` — kept at their identity path as ``direct`` rules.
- The provider-NATIVE ``top_k`` (not an OpenAI param) — a ``provider_native`` rule
  from the ``provider_params.top_k`` wrapper to the top-level key the builder reads.

# AIDEV-NOTE: this set mirrors Gemini's because the two builders are the same shape,
# NOT because one provider inherits the other's evidence. They are different
# upstreams; each is proven independently and labelled with its own source. If one
# builder changes, only that provider's rules move.
"""

from __future__ import annotations

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ProviderParameterObservation,
    ToolCapability,
)
from aigateway.core.standard_parameters import (
    MAX_TOKENS_SCHEMA,
    STOP_SCHEMA,
    TEMPERATURE_SCHEMA,
    TOP_K_SCHEMA,
    TOP_P_SCHEMA,
    direct_parameter_observations,
    direct_rule,
    function_calling_rules,
    provider_native_rule,
    tool_parameter_observations,
)

# The Code Assist envelope publishes no machine-readable schema, so the only honest
# evidence is the reviewed builder mapping — labelled with THIS provider's own source
# so it is never mistaken for, or inferred from, another provider's document.
CODE_ASSIST_SOURCE = "antigravity:code-assist"

_AUTH: tuple[AuthMode, ...] = ("oauth",)
# Bump when a projection's semantics change; folds into the contract digests.

# AIDEV-NOTE (OME-305, owner decision B — READ BEFORE CHANGING A ``cache_behavior``).
# Every rule below states ``cache_behavior="bypass"`` EXPLICITLY. That is a disposition,
# not an oversight, and it is not a judgement about the parameter: each of these values
# is output-affecting and WOULD have to be keyed for a cached answer to be correct.
#
# The reason they are not keyed is that THIS PROVIDER DOES NOT IMPLEMENT
# ``global_cache_projection`` — it inherits the ``CacheBypass`` default from
# ``ProviderPluginBase``. While that is true, every request to this provider bypasses
# the cache at the projection step regardless of any rule, so declaring ``keyed`` here
# would change no behaviour while advertising a cacheable parameter to callers that can
# never be cached. ``test_a_provider_that_declares_a_keyed_rule_backs_it_with_a_real_projection``
# in ``tests/unit/test_global_cache_registry_conformance.py`` is what enforces that.
#
# TO PROMOTE THESE: implement ``global_cache_projection`` for this provider FIRST, then
# flip these to ``keyed`` in the same change. The order matters — the conformance sweep
# will refuse the flip on its own, which is the intended guard rail rather than an
# obstacle. Anthropic and OpenRouter are the two providers that have the projection and
# therefore carry keyed rules today.

_REVISION = "antigravity-2026-07"

# build_generate_content_body converts tools[] → functionDeclarations, so `function`
# is a real capability. It emits NO toolConfig, so tool_choice has no wire home and is
# NOT enabled — the gateway never advertises a control it cannot honor.
_TOOL_CAPABILITIES: tuple[ToolCapability, ...] = (
    ToolCapability(tool_type="function", provider_support="supported", gateway_status="enabled"),
)

# The non-tool request paths the builder reads out of optional_params.
_SAMPLING_PATHS: tuple[str, ...] = (
    "temperature",
    "top_p",
    "max_tokens",
    "stop",
    "provider_params.top_k",
)

_RULES: tuple[ParameterProjectionRule, ...] = (
    direct_rule(
        "temperature",
        auth_modes=_AUTH,
        schema=TEMPERATURE_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "top_p",
        auth_modes=_AUTH,
        schema=TOP_P_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "max_tokens",
        auth_modes=_AUTH,
        schema=MAX_TOKENS_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    # The builder renames `stop` to stopSequences, coercing the scalar arm of the
    # OpenAI union into a one-element list — both arms have a proven wire home.
    direct_rule(
        "stop",
        auth_modes=_AUTH,
        schema=STOP_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    provider_native_rule(
        "provider_params.top_k",
        provider_target="top_k",
        auth_modes=_AUTH,
        schema=TOP_K_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    *function_calling_rules(
        _TOOL_CAPABILITIES, auth_modes=_AUTH, projection_revision=_REVISION, tool_choice=False
    ),
)

# §4.4: every enabled path carries evidence. The shared builder is used for the
# sampling paths too — it is the generic "these paths are supported" constructor, and
# keeping one source of truth here stops the rules and their evidence from drifting.
# INVARIANT: an observation NEVER enables a parameter — only a rule does.
ANTIGRAVITY_OBSERVATIONS: tuple[ProviderParameterObservation, ...] = tuple(
    sorted(
        direct_parameter_observations(_SAMPLING_PATHS, source=CODE_ASSIST_SOURCE)
        + tool_parameter_observations(
            _TOOL_CAPABILITIES, source=CODE_ASSIST_SOURCE, tool_choice=False
        ),
        key=lambda obs: obs.request_path,
    )
)


def antigravity_chat_parameter_rules(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ParameterProjectionRule, ...]:
    """The proven rule set is identical for every Antigravity model; auth-mode
    filtering is applied by the core classifier/contract, not here."""
    return _RULES


def antigravity_chat_parameter_tools(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ToolCapability, ...]:
    # The accepted tools[].type discriminator(s); drives supported_tools and the
    # detail contract's tools section. tool_choice is deliberately not enabled.
    return _TOOL_CAPABILITIES
