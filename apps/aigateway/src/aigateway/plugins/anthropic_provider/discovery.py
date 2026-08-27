"""OME-479 §5.1/§6.3 — Anthropic reviewed labelled-static parameter evidence (PURE).

Anthropic has no live PARAMETER discovery: §6.3 forbids spending credentials on parameter
discovery, and there is no unauthenticated Anthropic catalog to parse. OME-1026 narrowed §6.3
for the model LIST ONLY — ``live_models.py`` may dial the credentialed Models API with the
operator's dedicated deployment key to discover which model IDS exist. That says nothing about
which PARAMETERS a model accepts, so the ONLY honest parameter evidence here is still
reviewed labelled-static — the standard chat fields the
INSTALLED litellm ``AnthropicConfig`` transform accepts (source ``anthropic:static``, NO
network), used as the detail contract's observation source.

Two shapes of accepted field, kept apart:

- STANDARD OpenAI-surface fields the transform maps (``temperature``, ``top_p``,
  ``max_tokens``, ``reasoning_effort`` → ``thinking``, ``stop`` → ``stop_sequences``) —
  observed at their identity path.
- The Anthropic-NATIVE ``top_k`` (NOT an OpenAI param; litellm forwards it via
  ``get_optional_params``) — observed at the ``provider_params.top_k`` wrapper path so a
  wrapped field's observation lines up with its provider-native rule in the overlay.

INVARIANT (SOLID/hexagonal): pure module-level constants — NO network, NO clock, NO
credentials, NO provider-name switch. The plugin selects this evidence; core only composes.
INVARIANT (§4.4): an observation NEVER enables a parameter — only a rule does. ``stop`` is
observed here but has no rule, so it stays visible-but-DISABLED in the contract.
INVARIANT (§5.3): honest support only — every name below is a field the installed transform
provably accepts; ``seed``/``frequency_penalty``/``presence_penalty`` raise
``UnsupportedParamsError`` for Anthropic, so they are deliberately ABSENT (no fabricated
support), unlike the OpenAI-compatible providers.
"""

from __future__ import annotations

from typing import Literal

from aigateway.core.chat_parameters import ProviderParameterObservation
from aigateway.core.parameter_projection import WRAPPER_KEY

from .parameters import anthropic_sampling_support

# Reviewed labelled-static provenance — deliberately DISTINCT from any live label so a
# reader can tell reviewed-static evidence from a network fetch (§5.1 "labelled"). There is
# no live Anthropic PARAMETER label: OME-1026's credentialed discovery covers the model LIST
# only, and this evidence stays byte-identical whether or not that discovery is configured.
STATIC_SOURCE = "anthropic:static"

# Anthropic-native fields AIGateway addresses through the ``provider_params.*`` wrapper
# (native, non-OpenAI-standard). Mirrors the provider_native rule paths so a wrapped
# field's observation lines up with its rule in the detail overlay.
# AIDEV-NOTE: grows with each native rule added in parameters.py; keep in sync.
_WRAPPED_NATIVE_PARAMS: frozenset[str] = frozenset({"top_k"})

# OME-479 §6.3 — reviewed labelled-static evidence (NO network). Each name is a SAMPLING /
# generation field the INSTALLED litellm ``AnthropicConfig`` provably accepts (verified
# against its ``get_supported_openai_params`` / ``get_optional_params``). The tool request
# paths ``tools`` / ``tool_choice`` are NOT listed here: they are evidenced separately at
# the plugin level (``tool_parameter_observations`` over the plugin's tool capabilities,
# OME-583), so this constant stays a pure sampling-field inventory. ``response_format`` /
# ``stream`` remain excluded — structured output is unruled and ``stream`` is transport.
# AIDEV-NOTE: reviewed labelled-static evidence, not a central inventory — extend only for
# a SAMPLING field the installed transform provably accepts for Anthropic; tool paths are
# added via the plugin's tool observations, never here.
_STATIC_PARAM_NAMES: tuple[str, ...] = (
    "temperature",
    "top_p",
    "max_tokens",
    "reasoning_effort",
    "stop",
    "top_k",
)
_SAMPLING_PARAMS: frozenset[str] = frozenset({"temperature", "top_p", "top_k"})


def _request_path(param: str) -> str:
    if param in _WRAPPED_NATIVE_PARAMS:
        return f"{WRAPPER_KEY}.{param}"
    return param


def _observation(
    param: str, *, support: Literal["supported", "unsupported"] = "supported"
) -> ProviderParameterObservation:
    return ProviderParameterObservation(
        request_path=_request_path(param), support=support, source=STATIC_SOURCE
    )


ANTHROPIC_STATIC_PARAM_OBSERVATIONS: tuple[ProviderParameterObservation, ...] = tuple(
    _observation(param) for param in sorted(_STATIC_PARAM_NAMES)
)


def anthropic_static_param_observations(model: str) -> tuple[ProviderParameterObservation, ...]:
    """Reviewed static evidence narrowed by the selected model."""
    sampling_support = anthropic_sampling_support(model)
    observations: list[ProviderParameterObservation] = []
    for param in sorted(_STATIC_PARAM_NAMES):
        if param not in _SAMPLING_PARAMS:
            observations.append(_observation(param))
        elif sampling_support is not None:
            observations.append(
                _observation(
                    param,
                    support="supported" if sampling_support else "unsupported",
                )
            )
    return tuple(observations)
