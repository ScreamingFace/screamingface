"""Call a recipe, a URL4 or a gateway model as an OpenAI-style chat model (the chat calls).

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.1, C1.2 and
C2.1), unit U4. The module holds the model rule, the compile step, the argument checks and
the request of one chat call. The parameter policy is in _inference/parameters.py.
INVARIANT: no I/O. The only request is the operator catalogue load that the caller gives to
model_text.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

import httpx
from url4 import Expression, Source, Text, Url4Error, build

from screamingface._evaluation.candidate import (
    _children,
    compile_candidate,
    entry_recipe,
    recipes_need_operators,
)
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface._inference.parameters import KNOWN_PARAMETERS, check_other, refuse_tool_use
from screamingface._inference.trace import new_trace_context
from screamingface.chat_completion import ChatMessage
from screamingface.client import _use_cache_value
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.errors import PlanningError
from screamingface.recipe import Recipe
from screamingface.reducer import Reducer
from screamingface.url4 import Url4, _benchmark_id

type ModelSource = str | Recipe
"""A str is the model text to send as it is. A Recipe is a lowered recipe with a reducer, which
compiles at each call."""

INCLUDE_USAGE: Final[Mapping[str, Any]] = MappingProxyType({"include_usage": True})
_CANDIDATE: Final = "candidate"
_MESSAGES_FORM: Final = "messages must be an iterable of dicts or reply messages"
_TOOLS_FORM: Final = "tools must be an iterable of dicts"


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


def chat_messages(prompt: object, messages: object) -> list[dict[str, Any]]:  # noqa: PLR0912 - one branch per item kind
    """The messages of one chat call: the prompt as one user message, or the messages (C1.2)."""

    if (prompt is None) == (messages is None):
        raise TypeError("give exactly one of prompt and messages")
    if prompt is not None:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a str")
        return [{"role": "user", "content": prompt}]
    items = _items(messages, _MESSAGES_FORM)
    if not items:
        raise ValueError("messages must not be empty")
    # WHY: each item is a shallow copy, so the values are sent with no change (C1.2). A reply
    # message becomes its OpenAI wire form (D23), so the program can append it.
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            result.append(dict(item))
        elif isinstance(item, ChatMessage):
            result.append(_message_param(item))
        else:
            raise TypeError(_MESSAGES_FORM)
    return result


def chat_tools(tools: object) -> list[dict[str, Any]] | None:
    """The tools of one chat call, or None when the caller gave none (C2.1)."""

    if tools is None:
        return None
    items = _items(tools, _TOOLS_FORM)
    if not all(isinstance(item, Mapping) for item in items):
        raise TypeError(_TOOLS_FORM)
    return [dict(item) for item in items] or None


def _message_param(message: ChatMessage) -> dict[str, Any]:
    """The wire form of a reply message, as the OpenAI SDK sends its own message object (D23)."""

    param: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        param["tool_calls"] = [call.to_dict() for call in message.tool_calls]
    if message.refusal is not None:
        param["refusal"] = message.refusal
    return param


def _items(value: object, form: str) -> list[Any]:
    """The items of an iterable argument. A str, bytes or Mapping is not one (C1.7). The
    argument form is the error text."""

    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Iterable):
        raise TypeError(form)
    return list(value)


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
    if max_retries is not None:
        check_retries(max_retries)
    timeout_seconds(timeout)


def _require_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")


def timeout_seconds(value: object) -> float | None:
    """The limit of one chat call in seconds, or None for no limit of the SDK (C1.2, D21)."""

    if value is None:
        return None
    # WHY: the OpenAI clients take an httpx.Timeout. Its read value is the wait for the answer.
    if isinstance(value, httpx.Timeout):
        return timeout_seconds(value.read)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("timeout must be a number of seconds, an httpx.Timeout or None")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be a finite number of seconds above 0")
    return float(value)


def check_retries(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_retries must be an int")
    if value < 0:
        raise ValueError("max_retries must be 0 or more")
    return value


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
    "refuse_tool_use",
    "check_retries",
    "model_source",
    "model_text",
    "model_text_async",
    "timeout_seconds",
    "url4_text",
]
