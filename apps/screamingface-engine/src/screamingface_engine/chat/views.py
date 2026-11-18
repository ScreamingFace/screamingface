"""The text view and the native messages of the final step (tool-calls §3.4 and §3.5).

The text view is the candidate-input envelope that the run binds to $input. A client message keeps
its role, and each tool call or tool result becomes a line of text, so a step without tool support
reads the whole conversation. Tool content is data: the view quotes it and never runs it or reads
it as an instruction (TC-S20).

INVARIANT: the same input gives the same bytes, so the shared cache of a step works (rule 6).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_SCHEMA,
    CANDIDATE_INPUT_V2_SCHEMA,
)
from screamingface_engine.chat import wire

__all__ = ["CONVERSATION_MARKER", "TOOLS_NOTE", "native_messages", "text_view"]

TOOLS_NOTE = (
    "The client offers the tools below. Only the final step of this ensemble can call them, "
    "so do not try to call a tool. Each line is one tool as JSON."
)
CONVERSATION_MARKER = "[the conversation above]"


def text_view(messages: Sequence[wire.ClientMessage], tools: Sequence[wire.ToolSpec] | None) -> str:
    """The candidate-input envelope of a client conversation, bound to $input by the run.

    Rule 4 puts a system message first when the request has tools. Rule 3 joins the tool results
    in sequence into one user message. The other rules are in the helpers below.
    """

    rendered: list[dict[str, Any]] = []
    if tools:
        rendered.append({"role": "system", "content": _tools_note(tools)})
    pending: list[str] = []
    for message in messages:
        if isinstance(message, wire.ToolMessage):
            pending.append(f"[tool_result id={message.tool_call_id}] {_text(message.content)}")
            continue
        _flush(rendered, pending)
        rendered.append(_message(message))
    _flush(rendered, pending)
    has_list = any(isinstance(message["content"], list) for message in rendered)
    schema = CANDIDATE_INPUT_V2_SCHEMA if has_list else CANDIDATE_INPUT_SCHEMA
    return json.dumps(
        {"schema": schema, "messages": rendered}, ensure_ascii=False, separators=(",", ":")
    )


def native_messages(
    messages: Sequence[wire.ClientMessage],
    *,
    instruction: str,
    context: str | None,
    input_text: str,
) -> list[dict[str, Any]]:
    """The messages of the final step (tool-calls §3.5).

    The instruction comes first, then the client messages as the client sent them, then the
    context of the step when it adds to the input. Tool content stays data in every message.
    """

    rendered: list[dict[str, Any]] = []
    if instruction:
        rendered.append({"role": "system", "content": instruction})
    rendered.extend(wire.message_dict(message) for message in messages)
    if context and context != input_text:
        rendered.append({"role": "user", "content": _shown_context(context, input_text)})
    return rendered


def _tools_note(tools: Sequence[wire.ToolSpec]) -> str:
    """Rule 4: the note that only the final step can call tools, then one JSON line per tool."""

    return TOOLS_NOTE + "\n" + "\n".join(_tool_line(tool) for tool in tools)


def _tool_line(tool: wire.ToolSpec) -> str:
    function = tool.function
    obj: dict[str, Any] = {"name": function.name}
    if function.description is not None:
        obj["description"] = function.description
    if function.parameters is not None:
        obj["parameters"] = function.parameters
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _flush(rendered: list[dict[str, Any]], pending: list[str]) -> None:
    """Rule 3: the tool results in sequence become one user message."""

    if pending:
        rendered.append({"role": "user", "content": "\n".join(pending)})
        pending.clear()


def _message(
    message: wire.SystemMessage | wire.DeveloperMessage | wire.UserMessage | wire.AssistantMessage,
) -> dict[str, Any]:
    """Rules 0, 1, 2 and 5: only role and content are kept."""

    if isinstance(message, wire.AssistantMessage):
        return {"role": "assistant", "content": _assistant_content(message)}
    if isinstance(message, wire.UserMessage):
        return {"role": "user", "content": _user_content(message.content)}
    return {"role": message.role, "content": _text(message.content)}


def _text(content: str | list[wire.TextPart] | None) -> str:
    """Rule 0: a text part list becomes one string, and empty text parts are dropped."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # WHY: rule 0 of tool-calls §3.4. The parts join with "\n", the separator the gateway uses
    # when it joins text parts (aigateway core/content_parts.py). The join is part of the cache
    # key of every non-final step, so it must not change without a spec change.
    return "\n".join(part.text for part in content if part.text)


def _assistant_content(message: wire.AssistantMessage) -> str:
    """Rule 2: the text, then one line for each tool call."""

    text = _text(message.content)
    lines = [
        f"[tool_call id={call.id} name={call.function.name}] {call.function.arguments}"
        for call in message.tool_calls or []
    ]
    if not lines:
        return text
    return "\n".join(([text] if text else []) + lines)


def _user_content(content: str | list[wire.UserPart]) -> str | list[dict[str, Any]]:
    """Rule 5 and rule 0: a part list stays a list only when it holds a picture or a file."""

    if isinstance(content, str):
        return content
    parts = [part for part in content if not (isinstance(part, wire.TextPart) and part.text == "")]
    if not any(isinstance(part, wire.ImagePart | wire.FilePart) for part in parts):
        # WHY: the same rule 0 join as _text; it must not change without a spec change.
        return "\n".join(part.text for part in parts if isinstance(part, wire.TextPart))
    return [_part(part) for part in parts]


def _part(part: wire.UserPart) -> dict[str, Any]:
    if isinstance(part, wire.ImagePart):
        return {"type": "image_url", "image_url": _image(part.image_url)}
    if isinstance(part, wire.FilePart):
        return {"type": "file", "file": _file(part.file)}
    return {"type": "text", "text": part.text}


def _image(image: wire.ImageUrl) -> dict[str, Any]:
    value: dict[str, Any] = {"url": image.url}
    if image.detail is not None:
        value["detail"] = image.detail
    return value


def _file(data: wire.FileData) -> dict[str, Any]:
    value: dict[str, Any] = {"file_data": data.file_data}
    if data.filename is not None:
        value["filename"] = data.filename
    return value


def _shown_context(context: str, input_text: str) -> str:
    """The context with the conversation replaced by a marker when it carries the input.

    A context that is not a JSON object with the input as its "input" value is shown as it is.
    """

    try:
        decoded = json.loads(context)
    except (ValueError, RecursionError):
        return context
    if not isinstance(decoded, dict) or decoded.get("input") != input_text:
        return context
    decoded["input"] = CONVERSATION_MARKER
    return json.dumps(decoded)
