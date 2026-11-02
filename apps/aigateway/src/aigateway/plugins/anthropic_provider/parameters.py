"""Anthropic chat-parameter rules (OME-479 §6.1/§6.3) — proven set only.

INVARIANT (§9): every rule here is backed by a test proving the caller param
reaches the Anthropic dispatch body — the standard fields through the INSTALLED
litellm ``AnthropicConfig`` transform (``test_anthropic_parameter_projection``),
so enabling a field is earned, not speculative.

Auth-mode split (§6.3 — Anthropic offers BOTH api-key and OAuth):

- ``reasoning_effort``, ``temperature``, ``max_tokens``, ``top_p`` — standard
  fields whose forwarding is auth-agnostic (the OAuth Claude-Code attribution
  block only rewrites messages/system; the SAME transform then runs), so they are
  enabled under BOTH modes and survive the conservative summary intersection.
- ``provider_params.top_k`` → native top-level ``top_k`` — enabled for API KEY
  ONLY. The direct api-key path is transform-verifiable here; the OAuth Claude-Code
  SUBSCRIPTION path's native-param forwarding is uncaptured in v1 and §6.3 forbids
  credentialed discovery, so OAuth "cannot prove it". It therefore surfaces ENABLED
  in the api-key detailed contract but is DROPPED from the inline summary
  intersection. Because the global key is built before auth resolution, its presence
  bypasses the cache. Promoting it for OAuth later needs a captured-body proof.

# AIDEV-NOTE: the caller-facing wrapper ``provider_params.top_k`` matches OpenRouter
# for client consistency; only the projection TARGET is provider-specific (top-level
# top_k here vs extra_body.top_k for OpenRouter). ``stop`` is a standard field the
# INSTALLED transform renames to ``stop_sequences`` (proven under both auth modes).
"""

from __future__ import annotations

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ParameterSchema,
    ToolCapability,
)
from aigateway.core.model_parameter_contract import upstream_model_id
from aigateway.core.standard_parameters import (
    MAX_TOKENS_SCHEMA,
    REASONING_EFFORT_SCHEMA,
    STOP_SCHEMA,
    TOP_K_SCHEMA,
    TOP_P_SCHEMA,
    direct_rule,
    function_calling_rules,
    provider_native_rule,
)

# reasoning_effort/temperature/max_tokens/top_p are model behavior, not auth-specific
# features, so they are enabled under both modes (surviving the summary intersection).
_AUTH: tuple[AuthMode, ...] = ("api_key", "oauth")
# top_k: proven through the DIRECT api-key transform only (OAuth subscription path
# uncaptured in v1) — so it is authorized under api_key alone.
_API_KEY_ONLY: tuple[AuthMode, ...] = ("api_key",)
# AIDEV-NOTE (OME-305, owner decisions 52 and 59 — READ BEFORE CHANGING A
# ``cache_behavior``). Output-affecting rules available under every Anthropic auth mode
# are keyed. The api-key-only ``top_k`` is the deliberate exception: the global key is
# built before auth resolution, so it must bypass rather than advertise an unreachable
# keyed contract. A provider without ``global_cache_projection`` also cannot key rules.
#
# ``tools`` and ``tool_choice`` are NOT keyed anywhere and must stay that way: their
# presence bypasses structurally, ahead of any rule, via ``PRESENCE_BYPASS_REASONS``.

_REVISION = "anthropic-2026-07"

_SAMPLING_PATHS: frozenset[str] = frozenset({"temperature", "top_p", "provider_params.top_k"})
_SAMPLING_SUPPORTED_MODELS: frozenset[str] = frozenset(
    {"claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5"}
)
_SAMPLING_UNSUPPORTED_MODELS: frozenset[str] = frozenset({"claude-opus-4-8", "claude-opus-4-7"})

# WHY: Anthropic's Messages API accepts temperature in [0, 1] (NOT the shared
# OpenAI-compatible [0, 2]), and the installed litellm AnthropicConfig forwards the
# value with no clamp — so the gateway must enforce the real bound here or forward a
# value the provider 400s. Provider-local by design: standard_parameters forbids
# provider-specific ranges (its "no provider names appear here" invariant).
ANTHROPIC_TEMPERATURE_SCHEMA = ParameterSchema(type="number", minimum=0, maximum=1)

# OME-583: Anthropic accepts OpenAI-style function tools; the INSTALLED litellm
# AnthropicConfig transform maps tools[] → Anthropic custom tools and tool_choice
# (string → {"type":"auto"}, object → {"type":"tool","name":…}) onto the wire (§9), so
# function calling is enabled WITH tool_choice under both auth modes.
_TOOL_CAPABILITIES: tuple[ToolCapability, ...] = (
    ToolCapability(tool_type="function", provider_support="supported", gateway_status="enabled"),
)

_RULES: tuple[ParameterProjectionRule, ...] = (
    # direct: stays top-level as reasoning_effort (prepare_chat_body drops the
    # value "none" AFTER classification); schema accepts "none".
    direct_rule(
        "reasoning_effort",
        auth_modes=_AUTH,
        schema=REASONING_EFFORT_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # direct: standard sampling param a client sends bare — proven to reach the
    # Anthropic dispatch body by test_chat_request_cache.py::
    # test_a_keyed_parameter_is_cached_under_its_value_and_still_reaches_dispatch.
    # OME-305: that test has now carried three names (`test_unsupported_field_bypasses`
    # -> `test_a_declared_bypass_parameter_bypasses_the_global_cache` -> the current
    # one), because the global key asks THIS rule for the disposition instead of
    # refusing every field it does not recognise, and decision B then promoted
    # temperature to `keyed` — so it is now cached UNDER ITS VALUE rather than
    # bypassing. The bypass reason keeps v1's `unsupported_fields` spelling
    # (decision 53); only the condition that produces it narrowed.
    direct_rule(
        "temperature",
        auth_modes=_AUTH,
        schema=ANTHROPIC_TEMPERATURE_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # direct: proven through the installed AnthropicConfig transform (body top-level).
    direct_rule(
        "max_tokens",
        auth_modes=_AUTH,
        schema=MAX_TOKENS_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "top_p",
        auth_modes=_AUTH,
        schema=TOP_P_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # direct: standard stop (string | array[string]); the installed AnthropicConfig
    # transform renames it to stop_sequences on the outbound body. Auth-agnostic like
    # the other standard fields, so enabled under both modes (survives the summary).
    direct_rule(
        "stop",
        auth_modes=_AUTH,
        schema=STOP_SCHEMA,
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
    # provider_native: Anthropic-native top_k (NOT an OpenAI param) projected to the
    # top level; api-key only (see module docstring). Proven through the installed
    # transform + litellm.get_optional_params delivery.
    provider_native_rule(
        "provider_params.top_k",
        provider_target="top_k",
        auth_modes=_API_KEY_ONLY,
        schema=TOP_K_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    # OME-583: tools + tool_choice (enabled under both auth modes, §9 proof above).
    *function_calling_rules(_TOOL_CAPABILITIES, auth_modes=_AUTH, projection_revision=_REVISION),
)


def anthropic_sampling_support(model: str) -> bool | None:
    """Whether reviewed evidence permits sampling parameters for ``model``."""
    model_id = upstream_model_id(model)
    if model_id in _SAMPLING_SUPPORTED_MODELS:
        return True
    if model_id in _SAMPLING_UNSUPPORTED_MODELS:
        return False
    return None


def anthropic_chat_parameter_rules(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ParameterProjectionRule, ...]:
    # INVARIANT: sampling is fail-closed by model. Unknown operator-configured
    # ids keep the model-independent rules but cannot inherit unreviewed sampling.
    if anthropic_sampling_support(model) is True:
        return _RULES
    return tuple(rule for rule in _RULES if rule.request_path not in _SAMPLING_PATHS)


def anthropic_chat_parameter_tools(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ToolCapability, ...]:
    # OME-583: the accepted tools[].type discriminator(s); drives the summary's
    # supported_tools and the detail contract's tools section.
    return _TOOL_CAPABILITIES
