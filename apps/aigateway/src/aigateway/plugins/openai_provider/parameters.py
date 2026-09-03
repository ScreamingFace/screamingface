"""Direct OpenAI's chat-parameter contract.

FEATURE (OME-864): `max_tokens` is the one ordinary parameter direct OpenAI accepts.
FEATURE (OME-884): it is KEYED, so two callers sending the identical effective request
share one stored response and two different ceilings never do.
"""

from __future__ import annotations

from aigateway.core.chat_parameters import ParameterProjectionRule
from aigateway.core.profile_models import AuthMode
from aigateway.core.standard_parameters import MAX_TOKENS_SCHEMA, direct_rule

_AUTH: tuple[AuthMode, ...] = ("api_key",)

# OME-884 (`...-p0` -> `...-p1`): `max_tokens` moved from `cache_behavior="bypass"` to
# `"keyed"`. Under `p0` no direct OpenAI request was cacheable at all — the provider
# inherited the base `CacheBypass` — so there is no stored row from the old semantics to
# serve stale. The bump is still taken, because a rule's revision travels WITH its value
# into the key and a disposition change is exactly what it exists to record.
#
# WHY this is separate from `GLOBAL_CACHE_ADAPTER_REVISION` in `global_cache.py`: this
# one versions what a caller may say and where the value lands; that one versions what
# the boundary adds on its own. Collapsing them would make every rule edit look like a
# wire change, and vice versa.
_REVISION = "openai-2026-08-p1"

_RULES: tuple[ParameterProjectionRule, ...] = (
    direct_rule(
        "max_tokens",
        auth_modes=_AUTH,
        schema=MAX_TOKENS_SCHEMA,
        # INVARIANT (OME-884): KEYED, and it must stay keyed. `chat_cache_stage`
        # deliberately STORES a `finish_reason: "length"` response, because a truncation
        # is the correct answer to the request that asked for it. That is sound only
        # while the ceiling is part of the key — un-key it and a caller asking for 4000
        # tokens is served the answer that stopped at 20. Both LiteLLM spellings of the
        # ceiling (`max_tokens` for GPT-4/4o, `max_completion_tokens` for GPT-5/o-series)
        # mean one thing, and the model is keyed independently, so one entry per
        # (model, ceiling) is exactly right.
        cache_behavior="keyed",
        projection_revision=_REVISION,
    ),
)


def openai_chat_parameter_rules(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ParameterProjectionRule, ...]:
    # INVARIANT: the SAME rule for every route-valid `openai/*` model, seeded or not.
    # `default_models` is the published catalog, not an allowlist, so a model's absence
    # from it may not change what a caller is allowed to send or how it is keyed.
    del model, auth_type
    return _RULES
