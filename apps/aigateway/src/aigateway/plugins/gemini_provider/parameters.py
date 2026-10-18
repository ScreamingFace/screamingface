"""Gemini chat-parameter rules (OME-479 §Phase 9) — currently-proven set only.

INVARIANT: every rule here is backed by a characterization test that runs the
request pipeline and proves the value reaches ``build_generate_content_body``'s
``generationConfig`` — the last AIGateway-owned boundary that emits the Gemini
wire body — so enabling it is earned, not speculative (plan §12; §6.2). Both
dispatch paths (direct ``generateContent`` and the OAuth Code Assist envelope)
call that SAME builder, so every rule applies under BOTH auth modes; there is no
param-level auth asymmetry to fabricate (contrast Anthropic's api-key-only top_k).

Two shapes of enabled field:

- STANDARD OpenAI sampling fields the builder's ``config_map`` renames
  (``temperature``, ``top_p`` → ``topP``, ``max_tokens`` → ``maxOutputTokens``) —
  kept on the request as ``direct`` rules at their identity path.
- The provider-NATIVE ``top_k`` (not an OpenAI param) — a ``provider_native`` rule
  from the ``provider_params.top_k`` wrapper to the top-level ``top_k`` key the
  builder's ``config_map`` reads (renamed to ``topK``).

# AIDEV-NOTE: ``stop`` (OpenAI ``string | array[string]``) is ruled via the shared
# union ``STOP_SCHEMA``; the builder renames it to ``stopSequences`` (scalar coerced
# to a one-element list). Enabled under both auth modes since both dispatch paths run
# the SAME builder. A wrong-typed array item fails closed as malformed.
"""

from __future__ import annotations

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import ParameterProjectionRule, ToolCapability
from aigateway.core.standard_parameters import (
    MAX_TOKENS_SCHEMA,
    STOP_SCHEMA,
    TEMPERATURE_SCHEMA,
    TOP_K_SCHEMA,
    TOP_P_SCHEMA,
    direct_rule,
    function_calling_rules,
    provider_native_rule,
)

# Gemini offers BOTH api-key (generativelanguage) and OAuth (Code Assist) auth; both
# paths run the same body builder, so every proven rule is enabled under both modes.
_AUTH: tuple[AuthMode, ...] = ("api_key", "oauth")
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

_REVISION = "gemini-2026-07"

# OME-583: build_generate_content_body maps tools[] → functionDeclarations (§9), so Gemini
# enables `tools`. It emits NO toolConfig, so tool_choice has no wire home and is NOT
# enabled (tool_choice=False below) — the gateway never advertises a control it cannot honor.
_TOOL_CAPABILITIES: tuple[ToolCapability, ...] = (
    ToolCapability(tool_type="function", provider_support="supported", gateway_status="enabled"),
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
    # direct: standard stop (string | array[string]); the builder renames it to
    # stopSequences. Both auth paths share that builder → enabled under both modes.
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
    # OME-583: tools ONLY (tool_choice=False) — the builder has no toolConfig home.
    *function_calling_rules(
        _TOOL_CAPABILITIES, auth_modes=_AUTH, projection_revision=_REVISION, tool_choice=False
    ),
)


def gemini_chat_parameter_rules(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ParameterProjectionRule, ...]:
    """The proven rule set is identical for every Gemini model and every auth mode;
    auth-mode filtering is applied by the core classifier/contract, not here."""
    return _RULES


def gemini_chat_parameter_tools(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ToolCapability, ...]:
    # OME-583: the accepted tools[].type discriminator(s). tool_choice is deliberately
    # NOT enabled (see _TOOL_CAPABILITIES note); this drives supported_tools + the
    # detail contract's tools section.
    return _TOOL_CAPABILITIES
