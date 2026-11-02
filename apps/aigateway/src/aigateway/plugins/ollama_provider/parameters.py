"""Ollama chat-parameter rules (OME-636, OME-479 §Phase 9) — proven set only.

Ollama is the one provider whose final transform is not AIGateway code at all.
``prepare_chat_body`` rewrites ``ollama/<name>`` to ``ollama_chat/<name>`` and
hands the body to LiteLLM, so the last boundary before the wire is LiteLLM's own
``OllamaChatConfig.map_openai_params``. Every rule below was earned by running
that mapping and reading the parameters it emits.

INVARIANT (§9): a provider's DECLARED support list is not evidence — the mapping
is. ``get_supported_openai_params()`` names ``tool_choice``, but
``map_openai_params`` has no branch for it and pops it, noting upstream that it
hangs Ollama requests. Trusting the declaration would have advertised a control
the wire never receives.

INVARIANT: "carried" is necessary but NOT sufficient — the mapping must also
preserve MEANING. ``frequency_penalty`` is carried, and is still not enabled: the
transform renames it to ``repeat_penalty``, a different scale. OpenAI's ``0``
means "no penalty" and is the common client default, while Ollama disables at
``1.0`` and treats ``0`` as degenerate. An inverted default silently changes
generation; a dropped field at least leaves default behavior intact. So the
honest refusal wins, and enabling it later needs a value transform, not a rule.

Enabled paths and the wire keys they reach:

- ``temperature``, ``top_p``, ``seed``, ``stop`` — unchanged.
- ``max_tokens`` → ``num_predict``.
- ``response_format`` → ``format`` (``json_object`` → ``"json"``; ``json_schema``
  → the schema object; ``text`` emits nothing, which IS Ollama's free-form
  default, so the caller's request is honored exactly).
- ``reasoning_effort`` → ``think``, coarsened to a boolean outside the
  ``gpt-oss`` family (``low|medium|high`` → True). Carried at reduced resolution,
  direction preserved.
- ``tools`` → ``tools``, passed through in the OpenAI nested shape Ollama 0.4+
  accepts — no adapter needed, unlike a Responses backend.

``presence_penalty`` and ``n`` stay unsupported: the transform RAISES on them, and
the classifier's earlier refusal is the better error and costs no credential read.

# AIDEV-NOTE: these rules are pinned to litellm's mapping, not to Ollama's API.
# Before adding one, run ``get_optional_params(custom_llm_provider="ollama_chat")``
# and read the emitted key — a rule for a field litellm drops or renames onto a
# different scale is worse than no rule at all.
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
    REASONING_EFFORT_SCHEMA,
    RESPONSE_FORMAT_SCHEMA,
    SEED_SCHEMA,
    STOP_SCHEMA,
    TEMPERATURE_SCHEMA,
    TOP_P_SCHEMA,
    direct_parameter_observations,
    direct_rule,
    function_calling_rules,
    tool_parameter_observations,
)

# The evidence is the reviewed LiteLLM chat mapping, under Ollama's own label —
# never borrowed from another provider that happens to share a transform family.
LITELLM_CHAT_SOURCE = "ollama:litellm-chat"

# INVARIANT: Ollama holds no upstream credential, so "none" is its ONLY mode
# (OME-636). Publishing oauth or api_key here would advertise a path dispatch
# cannot take, and would make the summary intersection describe a fiction.
_AUTH: tuple[AuthMode, ...] = ("none",)
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

_REVISION = "ollama-2026-07"

# Non-tool enabled paths, in the order the mapping handles them.
_ENABLED_PATHS: tuple[str, ...] = (
    "temperature",
    "top_p",
    "max_tokens",
    "seed",
    "stop",
    "response_format",
    "reasoning_effort",
)

# tools[] passes through in the OpenAI nested shape; there is no toolConfig-style
# home for tool_choice, and the mapping discards it, so it is NOT enabled.
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
    # direct at the CALLER path: litellm owns the rename to num_predict. A
    # provider_target here would put the wire key on the body twice.
    direct_rule(
        "max_tokens",
        auth_modes=_AUTH,
        schema=MAX_TOKENS_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "seed",
        auth_modes=_AUTH,
        schema=SEED_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "stop",
        auth_modes=_AUTH,
        schema=STOP_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "response_format",
        auth_modes=_AUTH,
        schema=RESPONSE_FORMAT_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    direct_rule(
        "reasoning_effort",
        auth_modes=_AUTH,
        schema=REASONING_EFFORT_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
    *function_calling_rules(
        _TOOL_CAPABILITIES, auth_modes=_AUTH, projection_revision=_REVISION, tool_choice=False
    ),
)

# §4.4: every enabled path carries evidence.
# INVARIANT: an observation NEVER enables a parameter — only a rule does.
OLLAMA_OBSERVATIONS: tuple[ProviderParameterObservation, ...] = (
    *direct_parameter_observations(_ENABLED_PATHS, source=LITELLM_CHAT_SOURCE),
    *tool_parameter_observations(_TOOL_CAPABILITIES, source=LITELLM_CHAT_SOURCE, tool_choice=False),
)


def ollama_chat_parameter_rules(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ParameterProjectionRule, ...]:
    """The proven rule set is identical for every locally installed Ollama model;
    auth-mode filtering is applied by the core classifier/contract, not here."""
    return _RULES


def ollama_chat_parameter_tools(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ToolCapability, ...]:
    # Drives supported_tools on /v1/models and the detail contract's tools section.
    return _TOOL_CAPABILITIES
