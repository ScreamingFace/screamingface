"""Seeded chat conversations for the text view tests (plan decision D8).

One seeded random.Random draws every case, so a run tests the same bodies each time. A failing
test prints the case index and its body, which is enough to replay the case by hand. Some
messages, parts, tool calls and tools carry UNKNOWN_KEY, a key the wire models do not declare.
"""

from __future__ import annotations

import copy
import json
import random
from collections.abc import Callable
from typing import Any

SEED = 20261117
CASES = 300
PNG = "data:image/png;base64,iVBORw0KGgo="
PDF = "data:application/pdf;base64,JVBERi0xLjQ="
TEXTS = (
    "",
    "hello",
    "Grüße, 世界",
    'a "quote" and \\ backslash',
    "line one\nline two",
    "[tool_call id=x name=y] {}",
    '{"json": true}',
    "  spaced  ",
)
_DETAILS = ("auto", "low", "high")
UNKNOWN_KEY = "x_vendor"
UNKNOWN_VALUE = "provider-state-9d41"


def cases() -> list[tuple[int, dict[str, Any]]]:
    """Every generated request body with its index, in a fixed order."""

    rng = random.Random(SEED)
    return [(index, conversation(rng, index)) for index in range(CASES)]


def conversation(rng: random.Random, index: int) -> dict[str, Any]:
    """One request body: optional tools, an optional leading message, then 1 to 6 turns."""

    tools = _tools(rng)
    names = [tool["function"]["name"] for tool in tools or []] + ["tool_x"]
    messages: list[dict[str, Any]] = []
    if rng.choice([True, False]):
        first = {"role": rng.choice(["system", "developer"]), "content": _text_content(rng)}
        messages.append(_maybe_unknown(rng, first))
    for turn in range(rng.randint(1, 6)):
        messages.extend(_turn(rng, index, turn, names))
    body: dict[str, Any] = {"model": "m", "messages": messages}
    if tools is not None:
        body["tools"] = tools
    return body


def _tools(rng: random.Random) -> list[dict[str, Any]] | None:
    """No tools key, an empty list, or one to three function tools named tool_0 and up."""

    shape = rng.choice(["none", "empty", "some"])
    if shape == "none":
        return None
    if shape == "empty":
        return []
    return [_tool(rng, number) for number in range(rng.randint(1, 3))]


def _tool(rng: random.Random, number: int) -> dict[str, Any]:
    function: dict[str, Any] = {"name": f"tool_{number}"}
    if rng.choice([True, False]):
        function["description"] = rng.choice(TEXTS[1:])
    if rng.choice([True, False]):
        function["parameters"] = {"type": "object", "properties": {"p": {"type": "string"}}}
    return _maybe_unknown(rng, {"type": "function", "function": _maybe_unknown(rng, function)})


def _maybe_unknown(rng: random.Random, value: dict[str, Any]) -> dict[str, Any]:
    """The value, with UNKNOWN_KEY added one time in four."""

    if rng.random() < 0.25:
        value[UNKNOWN_KEY] = {"echo": UNKNOWN_VALUE}
    return value


def without_unknown(value: Any) -> Any:
    """A deep copy of a body with every UNKNOWN_KEY removed, at any depth."""

    if isinstance(value, dict):
        return {key: without_unknown(item) for key, item in value.items() if key != UNKNOWN_KEY}
    if isinstance(value, list):
        return [without_unknown(item) for item in value]
    return copy.deepcopy(value)


def _turn(rng: random.Random, index: int, turn: int, names: list[str]) -> list[dict[str, Any]]:
    return _TURNS[rng.choice(sorted(_TURNS))](rng, index, turn, names)


def _user_turn(rng: random.Random, index: int, turn: int, names: list[str]) -> list[dict[str, Any]]:
    return [_maybe_unknown(rng, {"role": "user", "content": _user_content(rng)})]


def _assistant_turn(
    rng: random.Random, index: int, turn: int, names: list[str]
) -> list[dict[str, Any]]:
    return [_maybe_unknown(rng, {"role": "assistant", "content": _assistant_text(rng)})]


def _tool_alone_turn(
    rng: random.Random, index: int, turn: int, names: list[str]
) -> list[dict[str, Any]]:
    """One tool message with no call before it, as a client may send after a user message."""

    alone = {
        "role": "tool",
        "tool_call_id": f"call_{index}_{turn}_alone",
        "content": _text_content(rng),
    }
    return [_maybe_unknown(rng, alone)]


def _text_part(rng: random.Random) -> dict[str, Any]:
    return _maybe_unknown(rng, {"type": "text", "text": rng.choice(TEXTS)})


def _text_content(rng: random.Random) -> str | list[dict[str, Any]]:
    """A text, or a list of one to three text parts."""

    if rng.choice([True, False]):
        return rng.choice(TEXTS)
    return [_text_part(rng) for _ in range(rng.randint(1, 3))]


def _assistant_text(rng: random.Random) -> str | list[dict[str, Any]] | None:
    if rng.choice([True, False]):
        return None
    return _text_content(rng)


def _user_content(rng: random.Random) -> str | list[dict[str, Any]]:
    """A text, or a list of one to four parts: text, picture or file."""

    if rng.choice([True, False]):
        return rng.choice(TEXTS)
    return [_user_part(rng) for _ in range(rng.randint(1, 4))]


def _user_part(rng: random.Random) -> dict[str, Any]:
    kind = rng.choice(["text", "image", "file"])
    if kind == "text":
        return _text_part(rng)
    if kind == "image":
        return _image_part(rng)
    return _file_part(rng)


def _image_part(rng: random.Random) -> dict[str, Any]:
    image: dict[str, Any] = {"url": PNG}
    if rng.choice([True, False]):
        image["detail"] = rng.choice(_DETAILS)
    return _maybe_unknown(rng, {"type": "image_url", "image_url": _maybe_unknown(rng, image)})


def _file_part(rng: random.Random) -> dict[str, Any]:
    file: dict[str, Any] = {"file_data": PDF}
    if rng.choice([True, False]):
        file["filename"] = "a.pdf"
    return _maybe_unknown(rng, {"type": "file", "file": _maybe_unknown(rng, file)})


def _tool_content(rng: random.Random) -> str | list[dict[str, Any]] | None:
    """None, an empty string, one text, or a list of one to three text parts."""

    shape = rng.choice(["none", "empty", "text", "parts"])
    if shape == "text":
        return rng.choice(TEXTS)
    if shape == "parts":
        return [_text_part(rng) for _ in range(rng.randint(1, 3))]
    return {"none": None, "empty": ""}[shape]


def _tool_turn(rng: random.Random, index: int, turn: int, names: list[str]) -> list[dict[str, Any]]:
    """An assistant message with one to three calls, then one tool message per call."""

    calls = [
        _tool_call(rng, f"call_{index}_{turn}_{number}", names)
        for number in range(rng.randint(1, 3))
    ]
    assistant: dict[str, Any] = {
        "role": "assistant",
        "content": _tool_content(rng),
        "tool_calls": calls,
    }
    replies = [
        _maybe_unknown(
            rng, {"role": "tool", "tool_call_id": call["id"], "content": _text_content(rng)}
        )
        for call in calls
    ]
    return [_maybe_unknown(rng, assistant), *replies]


def _tool_call(rng: random.Random, call_id: str, names: list[str]) -> dict[str, Any]:
    function = {
        "name": rng.choice(names),
        "arguments": json.dumps({"k": rng.choice(TEXTS)}, ensure_ascii=False),
    }
    call = {"id": call_id, "type": "function", "function": _maybe_unknown(rng, function)}
    return _maybe_unknown(rng, call)


_Turn = Callable[[random.Random, int, int, list[str]], list[dict[str, Any]]]
_TURNS: dict[str, _Turn] = {
    "user": _user_turn,
    "assistant_text": _assistant_turn,
    "assistant_tools": _tool_turn,
    "tool_alone": _tool_alone_turn,
}


def known_conversation() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A conversation with tool calls whose every key is one the wire models declare."""

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": [{"type": "text", "text": "Read a.py"}]},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "print(1)"},
    ]
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]
    return messages, tools


def provider_state_conversation() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """known_conversation with the keys an agent echoes back to its provider."""

    messages, tools = known_conversation()
    messages[1]["content"][0]["cache_control"] = {"type": "ephemeral"}
    messages[2]["reasoning_details"] = [{"type": "reasoning.encrypted", "data": "c2lnbmVk"}]
    messages[2]["tool_calls"][0]["extra_content"] = {"google": {"thought_signature": "c2ln"}}
    messages[3]["name"] = "read_file"
    tools[0]["cache_control"] = {"type": "ephemeral"}
    tools[0]["function"]["strict"] = True
    return messages, tools
