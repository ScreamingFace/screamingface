"""Tool calls are turned off on POST /v1/chat/completions (prd/tool-calls.md section 0, TC-23).

FEATURE: OpenAI-compatible Engine API. Owner decision of 2026-11-24: a request that declares or
uses a tool is refused with HTTP 400 `tools_not_available`, before a run, a blob write and a
catalogue read. The check is fixed: no setting turns it off.
STORY: as a developer with an OpenAI client, I send tools and I get one clear error in the OpenAI
envelope, with no run and no cost.
"""

from __future__ import annotations

from typing import Any

import pytest
from _chat_app import MESSAGES, ChatApp, answered, body, chat_app, error, post

from screamingface_engine.config import Settings
from screamingface_engine.rest import chat_body
from screamingface_engine.rest.chat_errors import FIXED_MESSAGES

pytestmark = pytest.mark.asyncio

CODE = "tools_not_available"
TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}
CALL = {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}
ASSISTANT = {"role": "assistant", "content": None, "tool_calls": [CALL]}
RESULT = {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"}
REFUSED: list[tuple[str, dict[str, Any], str]] = [
    ("tools", {"tools": [TOOL]}, "tools"),
    ("tools-and-stream", {"tools": [TOOL], "stream": True}, "tools"),
    ("functions", {"functions": [{"name": "get_weather"}]}, "functions"),
    (
        "assistant-tool-calls",
        {"messages": [*MESSAGES, ASSISTANT, RESULT]},
        "messages[1].tool_calls",
    ),
    ("tool-message", {"messages": [*MESSAGES, RESULT]}, "messages[1]"),
    ("tools-before-messages", {"tools": [TOOL], "messages": [*MESSAGES, RESULT]}, "tools"),
]


def _no_work(ca: ChatApp) -> None:
    assert ca.runner.scheduled == []
    assert ca.objects.objects == {}
    assert ca.source is not None and ca.source.calls == []


@pytest.mark.parametrize(
    ("extra", "param"), [item[1:] for item in REFUSED], ids=[item[0] for item in REFUSED]
)
async def test_tool_use_is_400_tools_not_available_before_any_work(
    extra: dict[str, Any], param: str
) -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(**extra))

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["x-should-retry"] == "false"
    assert error(resp) == {
        "message": FIXED_MESSAGES[CODE],
        "type": "invalid_request_error",
        "param": param,
        "code": CODE,
    }
    assert "not available yet" in error(resp)["message"]
    _no_work(ca)


@pytest.mark.parametrize(
    "extra",
    [
        {"tools": []},
        {"tools": None},
        {"functions": []},
        {"tool_choice": "auto", "function_call": "none", "parallel_tool_calls": False},
        {"messages": [*MESSAGES, {"role": "assistant", "content": "Paris", "tool_calls": None}]},
        {"messages": [*MESSAGES, {"role": "assistant", "content": "Paris", "tool_calls": []}]},
    ],
    ids=[
        "empty-tools",
        "null-tools",
        "empty-functions",
        "choice-fields",
        "null-tool-calls",
        "empty-tool-calls",
    ],
)
async def test_a_request_with_no_tool_is_not_refused(extra: dict[str, Any]) -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(**extra))

    assert resp.status_code == 200
    assert len(ca.runner.scheduled) == 1


async def test_an_invalid_tool_shape_is_still_invalid_request() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(tools=[{"type": "function"}]))

    assert resp.status_code == 400
    assert error(resp)["code"] == "invalid_request"
    assert error(resp)["param"] == "tools"
    _no_work(ca)


async def test_an_unsupported_parameter_is_named_before_the_tools() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(tools=[TOOL], n=2))

    assert error(resp)["code"] == "unsupported_parameter"
    assert error(resp)["param"] == "n"
    _no_work(ca)


def test_no_setting_turns_the_refusal_off() -> None:
    """INVARIANT: the refusal is fixed. A setting with a tools name would be a switch."""
    assert [name for name in Settings.model_fields if "tool" in name and "chat" in name] == []
    request = chat_body.ChatCompletionRequest.model_validate(body(tools=[TOOL]))
    assert chat_body._tool_use(request) == "tools"
