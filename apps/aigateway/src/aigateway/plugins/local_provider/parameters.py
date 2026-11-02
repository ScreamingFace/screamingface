from __future__ import annotations

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ProviderParameterObservation,
)
from aigateway.core.standard_parameters import (
    MAX_TOKENS_SCHEMA,
    direct_parameter_observations,
    direct_rule,
)

_AUTH: tuple[AuthMode, ...] = ("none",)
_REVISION = "local-openai-v1"
# WHY only max_tokens: this is the proved common denominator across LM Studio,
# vLLM, SGLang, and llama.cpp for the first local Fusion/benchmark contract.
# New controls require their own projection rule and captured wire evidence.
_RULES = (
    direct_rule(
        "max_tokens",
        auth_modes=_AUTH,
        schema=MAX_TOKENS_SCHEMA,
        cache_behavior="bypass",
        projection_revision=_REVISION,
    ),
)
_OBSERVATIONS = direct_parameter_observations(("max_tokens",), source="local:openai-v1")


def local_chat_parameter_rules(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ParameterProjectionRule, ...]:
    del model
    return _RULES if auth_type in (None, "none") else ()


def local_chat_parameter_observations(
    *, model: str, auth_type: AuthMode | None = None
) -> tuple[ProviderParameterObservation, ...]:
    del model
    return _OBSERVATIONS if auth_type in (None, "none") else ()
