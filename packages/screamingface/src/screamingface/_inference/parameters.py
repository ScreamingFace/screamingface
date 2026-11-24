"""The parameter policy of the chat calls: the other keywords of create.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.2 and C1.7;
P4, D4, D25). A known name is accepted, is not sent and gives a warning. A value that the Engine
cannot do is refused. Each other name is a TypeError.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from screamingface.errors import PlanningError
from screamingface.warnings import IgnoredParameterWarning

# WHY: the keywords of the OpenAI create that are not model parameters of a recipe (D25). Their
# warning does not point to sf.Model(params=...), because that advice does not apply to them.
OPENAI_ONLY_PARAMETERS: Final[frozenset[str]] = frozenset(
    {
        "extra_headers",
        "extra_query",
        "extra_body",
        "prediction",
        "web_search_options",
        "prompt_cache_key",
        "prompt_cache_options",
        "prompt_cache_retention",
        "safety_identifier",
        "verbosity",
        "moderation",
        "functions",
        "function_call",
    }
)

# WHY: the set of names that the SDK accepts (C1.2). It holds every keyword of the OpenAI create
# (openai==2.54.0) that is not a named parameter (C1.7, D25). 'audio' and 'modalities' are in it
# because the Engine knows them (E/rest/chat_body.py _unsupported_parameter): a value that the
# Engine refuses raises PlanningError through _REFUSED, and a value with no effect is ignored with
# the warning.
KNOWN_PARAMETERS: Final[frozenset[str]] = frozenset(
    {
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "top_p",
        "stop",
        "seed",
        "response_format",
        "tool_choice",
        "parallel_tool_calls",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "top_logprobs",
        "reasoning_effort",
        "user",
        "metadata",
        "store",
        "service_tier",
        "n",
        "logprobs",
        "audio",
        "modalities",
    }
    | OPENAI_ONLY_PARAMETERS
)

# WHY: the same rule as the Engine (E/rest/chat_body.py _unsupported_parameter).
_REFUSED: Final[Mapping[str, Callable[[Any], bool]]] = MappingProxyType(
    {
        "n": lambda value: isinstance(value, int) and not isinstance(value, bool) and value > 1,
        "logprobs": lambda value: value is True,
        "audio": lambda value: value is not None,
        "modalities": lambda value: isinstance(value, list | tuple) and "audio" in value,
        # WHY: a call must not lose its tools with only a warning (P4, D25).
        "functions": lambda value: value is not None,
        "function_call": lambda value: value is not None,
    }
)


def check_other(other: Mapping[str, Any], *, stacklevel: int = 3) -> None:
    """Apply the parameter policy to the other keywords of one chat call (P4).

    Order: an unknown name raises TypeError first, then a refused value raises PlanningError,
    then each known name gives one warning. So a call that raises gives no warning.
    AIDEV-NOTE: stacklevel counts from this function (2 is the caller of check_other). The
    default 3 names the caller of that caller. create_call in _inference/calls.py passes 4, so
    the warning names the line of the user on each chat surface. Do not call it through another
    helper.
    """

    unknown = [name for name in other if name not in KNOWN_PARAMETERS]
    if unknown:
        raise TypeError(f"create() got an unexpected keyword argument {unknown[0]!r}")
    for name, value in other.items():
        refuse = _REFUSED.get(name)
        if refuse is not None and refuse(value):
            raise PlanningError(
                f"The SF Engine does not support the chat parameter {name!r} with this value",
                code="unsupported_parameter",
                permanent=True,
                details={"param": name},
            )
    for name in other:
        if name in OPENAI_ONLY_PARAMETERS:
            text = (
                f"ScreamingFace does not use the OpenAI chat parameter {name!r}, so the call does "
                "not send it."
            )
        else:
            text = (
                f"The SF Engine ignores the chat parameter {name!r}, so the call does not send "
                "it. Set model parameters on the recipe with sf.Model(..., params=...)."
            )
        warnings.warn(text, IgnoredParameterWarning, stacklevel=stacklevel)


__all__ = ["KNOWN_PARAMETERS", "OPENAI_ONLY_PARAMETERS", "check_other"]
