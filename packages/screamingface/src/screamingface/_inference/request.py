"""Call a recipe, a URL4 or a gateway model as an OpenAI-style chat model (the chat calls).

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.1, C1.2 and
C2.1), unit U4. The module holds the model rule, the compile step, the argument checks, the
parameter policy and the request of one chat call.
INVARIANT: no I/O. The only request is the operator catalogue load that the caller gives to
model_text.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from url4 import Expression, Source, Text, Url4Error, build

from screamingface._evaluation.candidate import (
    _children,
    compile_candidate,
    entry_recipe,
    recipes_need_operators,
)
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface._inference.trace import new_trace_context
from screamingface.client import _use_cache_value
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.errors import PlanningError
from screamingface.recipe import Recipe
from screamingface.reducer import Reducer
from screamingface.url4 import Url4, _benchmark_id
from screamingface.warnings import IgnoredParameterWarning

type ModelSource = str | Recipe
"""A str is the model text to send as it is. A Recipe is a lowered recipe with a reducer, which
compiles at each call."""

# WHY: the set of names that the SDK accepts (C1.2). 'audio' and 'modalities' are in it because the
# Engine knows them (E/rest/chat_body.py _unsupported_parameter): a value that the Engine refuses
# raises PlanningError through _REFUSED, and a value with no effect is ignored with the warning.
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
)

# WHY: the same rule as the Engine (E/rest/chat_body.py _unsupported_parameter).
_REFUSED: Final[Mapping[str, Callable[[Any], bool]]] = MappingProxyType(
    {
        "n": lambda value: isinstance(value, int) and not isinstance(value, bool) and value > 1,
        "logprobs": lambda value: value is True,
        "audio": lambda value: value is not None,
        "modalities": lambda value: isinstance(value, list | tuple) and "audio" in value,
    }
)
INCLUDE_USAGE: Final[Mapping[str, Any]] = MappingProxyType({"include_usage": True})
_CANDIDATE: Final = "candidate"


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatCall:
    """One checked chat call for the transport."""

    body: Mapping[str, Any]
    use_cache: bool
    max_retries: int
    timeout: float | None


def model_source(model: object) -> ModelSource:
    """The model text or recipe of one chat call (P1, P14, P17).

    It raises TypeError, ValueError or PlanningError and sends no request.
    """

    if isinstance(model, Recipe):
        return _recipe_source(model)
    if not isinstance(model, str):
        raise TypeError("model must be a recipe, a sf.Url4 or a str")
    if not model.strip():
        raise ValueError("model must not be blank")
    # WHY: the rule of the Engine (E/chat/recipe.py is_recipe_value): "(" after white space is
    # URL4 text.
    if isinstance(model, Url4) or model.lstrip().startswith("("):
        return url4_text(model)
    return str(model)


def url4_text(text: str) -> str:
    """The Candidate URL4 text of URL4 text (P14).

    Candidate URL4 text goes as it is. An evaluation URL4 gives its candidate source. The result
    is always a plain str, never a Url4.
    """

    root = _parsed(text)
    if root is None:
        # WHY: the Engine is the authority for text that does not parse.
        return str(text)
    candidate = _candidate_text(root)
    if candidate is not None:
        return candidate
    if _benchmark_id(root) is not None:
        raise _no_candidate()
    return str(text)


def _parsed(text: str) -> Expression | None:
    try:
        root = build(text)
    except (Url4Error, RecursionError):
        return None
    return root if isinstance(root, Expression) else None


def _candidate_text(root: Expression) -> str | None:
    # WHY: the rule of the Engine (E/benchmarks/picture_admission.py _candidate_recipes) and of
    # S/url4.py _candidate_expression: only a top-level 'candidate' Text source is the Candidate of
    # an evaluation URL4. Any other 'candidate' source is a plain binding.
    for source in root.sources:
        if (
            isinstance(source, Source)
            and source.name == _CANDIDATE
            and isinstance(source.value, Text)
        ):
            return source.value.value
    return None


def _no_candidate() -> PlanningError:
    return PlanningError(
        "This URL4 is an evaluation URL4 with no Candidate URL4 text in it; the chat route needs "
        "Candidate URL4 text or a gateway model id",
        code="recipe_invalid",
        permanent=True,
        hint="Give the url4 of a Candidate, for example report.candidates[...].url4.",
    )


def _recipe_source(recipe: Recipe) -> ModelSource:
    # WHY entry_recipe once: it lowers the recipe and gives the judge-writer warning one time.
    # Each compile after it uses warn_judge_writers=False.
    lowered = entry_recipe(recipe)
    if _has_corrective_loop(lowered):
        raise PlanningError(
            "The chat route cannot run a corrective loop (sf.CorrectiveLoop or sf.SelfCorrective)",
            code="recipe_not_supported",
            permanent=True,
            hint="Remove the corrective loop from the recipe; sf.evaluate can run it.",
        )
    if recipes_need_operators([lowered]):
        return lowered
    return compile_candidate(lowered, warn_judge_writers=False).url4


def _has_corrective_loop(value: Recipe | Reducer) -> bool:
    if isinstance(value, CorrectiveLoop | SelfCorrective):
        return True
    if isinstance(value, Reducer):
        return False
    return any(_has_corrective_loop(child) for child in _children(value))


def model_text(source: ModelSource, load_operators: Callable[[], _OperatorCatalog]) -> str:
    """The Candidate URL4 text that one chat call sends (P2, P17).

    The compiler errors (ValueError, PlanningError) are not caught here.
    """

    if isinstance(source, str):
        return source
    # WHY at each call (P2): the text follows the operator catalogue of the Engine, as in an
    # evaluation.
    return compile_candidate(source, operators=load_operators(), warn_judge_writers=False).url4


async def model_text_async(
    source: ModelSource, load_operators: Callable[[], Awaitable[_OperatorCatalog]]
) -> str:
    """The async twin of model_text: the catalogue loads with await, then the same compile."""

    if isinstance(source, str):
        return source
    catalog = await load_operators()
    return model_text(source, lambda: catalog)


def chat_messages(prompt: object, messages: object) -> list[dict[str, Any]]:
    """The messages of one chat call: the prompt as one user message, or the messages (C1.2)."""

    if (prompt is None) == (messages is None):
        raise TypeError("give exactly one of prompt and messages")
    if prompt is not None:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a str")
        return [{"role": "user", "content": prompt}]
    return _mappings(messages, "messages", allow_empty=False)


def chat_tools(tools: object) -> list[dict[str, Any]] | None:
    """The tools of one chat call, or None when the caller gave none (C2.1)."""

    if tools is None:
        return None
    return _mappings(tools, "tools", allow_empty=True) or None


def _mappings(value: object, name: str, *, allow_empty: bool) -> list[dict[str, Any]]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a list of dicts")
    if not all(isinstance(item, Mapping) for item in value):
        raise TypeError(f"{name} must be a list of dicts")
    if not value and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    # WHY: each item is a shallow copy; the values do not change (C1.2: sent with no change).
    return [dict(item) for item in value]


def check_options(
    *,
    stream: object,
    stream_options: object,
    use_cache: object,
    max_retries: object,
    timeout: object,
) -> None:
    """Check the typed options of one chat call (C1.2)."""

    _require_bool(stream, "stream")
    # WHY: one check and one message for use_cache in sf.evaluate and the chat calls.
    _use_cache_value(use_cache)
    if stream_options is not None and not isinstance(stream_options, Mapping):
        raise TypeError("stream_options must be a dict or None")
    # WHY: OpenAI refuses an include_usage that is not a bool; a value such as 1 must not drop the
    # usage chunk with no error.
    if stream_options is not None and not isinstance(
        stream_options.get("include_usage", False), bool
    ):
        raise TypeError("stream_options['include_usage'] must be a bool")
    _check_retries(max_retries)
    _check_timeout(timeout)


def _require_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")


def _check_retries(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_retries must be an int")
    if value < 0:
        raise ValueError("max_retries must be 0 or more")


def _check_timeout(value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("timeout must be a number of seconds or None")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be a finite number of seconds above 0")


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
        warnings.warn(
            f"The SF Engine ignores the chat parameter {name!r}, so the call does not send it. "
            "Set model parameters on the recipe with sf.Model(..., params=...).",
            IgnoredParameterWarning,
            stacklevel=stacklevel,
        )


def chat_body(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    stream_options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The JSON body of one chat call (C2.1)."""

    body: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
    # WHY: each call is streamed on the wire (ans:Q5).
    body["stream"] = True
    if stream_options is not None:
        body["stream_options"] = dict(stream_options)
    return body


def chat_call(
    model: str,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    stream: bool,
    stream_options: Mapping[str, Any] | None,
    use_cache: bool,
    max_retries: int,
    timeout: float | None,
) -> ChatCall:
    """The chat call of one model text for the transport (C2.1).

    WHY two forms of stream_options (C2.1, P6): with stream=False the SDK builds the reply, and the
    reply needs the usage chunk, so the wire always asks for it. With stream=True the wire carries
    the value of the caller, so the caller gets the chunks that an OpenAI client gets, and the SDK
    does not copy the frame rule of the Engine.
    """

    options = stream_options if stream else INCLUDE_USAGE
    body = chat_body(model, messages, tools, stream_options=options)
    return ChatCall(body=body, use_cache=use_cache, max_retries=max_retries, timeout=timeout)


def chat_headers(*, use_cache: bool) -> tuple[dict[str, str], str]:
    """The headers of one try and its trace id (C2.1, P8).

    The client adds the auth and User-Agent headers. httpx adds Content-Type for json=.
    """

    trace = new_trace_context()
    headers = {"Accept": "text/event-stream", **trace.headers()}
    if not use_cache:
        headers["Cache-Control"] = "no-store"
    return headers, trace.trace_id


__all__ = [
    "KNOWN_PARAMETERS",
    "INCLUDE_USAGE",
    "ChatCall",
    "ModelSource",
    "chat_body",
    "chat_call",
    "chat_headers",
    "chat_messages",
    "chat_tools",
    "check_options",
    "check_other",
    "model_source",
    "model_text",
    "model_text_async",
    "url4_text",
]
