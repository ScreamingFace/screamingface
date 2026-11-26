"""The retry flag of the stream error event, and one reply shape for the stream and the plain route.

FEATURE: SDK model inference, tests SE-1 to SE-7 of
docs/spec/2026-11-18-sdk-model-inference/prd/stream-error-retry-flag.md. The SDK sends each call
as a stream and builds the reply from the chunks, so the stream must say when a retry is safe, and
the reply that a client builds from the chunks must be equal to the plain reply of the Engine for
the same run.
STORY: as a client that reads the stream, I know from the error event if a retry is safe, as I
know it from the x-should-retry header of a plain answer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from _chat_app import (
    ChatApp,
    answered,
    body,
    chat_app,
    chat_result,
    ended,
    post,
)
from _chat_stream import (
    data_payloads,
    stream_body,
)
from test_chat_completions_answer import SUCCESS_ROWS, TERMINAL_ROWS

from screamingface_engine.chat.result import ChatResult
from screamingface_engine.chat.sse import error_event
from screamingface_engine.chat.wire import ToolCall

pytestmark = pytest.mark.asyncio


def _event(payloads: list[dict[str, Any] | str]) -> dict[str, Any]:
    """The error object of the one error event of a stream."""
    events = [p for p in payloads if isinstance(p, dict) and "error" in p]
    assert len(events) == 1
    assert "[DONE]" not in payloads
    return events[0]["error"]


def _calls() -> list[ToolCall]:
    return [
        ToolCall.model_validate(
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
            }
        )
    ]


# --- SE-1, SE-4: the retry values of the event ---------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "permanent", "http_status", "error_code", "retry", "retry_after"),
    TERMINAL_ROWS,
)
async def test_stream_error_event_has_the_retry_values_of_the_plain_answer(
    status: Any,
    code: str,
    permanent: bool,
    http_status: int,
    error_code: str,
    retry: str,
    retry_after: str | None,
) -> None:
    """SE-1 / SE-S4: for each terminal row, the event says what the plain answer headers say."""
    script = ended(status, code, permanent=permanent)
    plain = await post(chat_app(script).app, body())
    streamed = await post(chat_app(script).app, stream_body())

    event = _event(data_payloads(streamed.content))
    assert plain.status_code == http_status
    assert event["code"] == plain.json()["error"]["code"] == error_code
    assert event["should_retry"] is (plain.headers["x-should-retry"] == "true")
    assert plain.headers["x-should-retry"] == retry
    if retry_after is None:
        assert "retry_after" not in event
        assert "retry-after" not in plain.headers
    else:
        assert event["retry_after"] == int(plain.headers["retry-after"]) == int(retry_after)


@pytest.mark.parametrize(("name", "script", "http_status", "error_code"), SUCCESS_ROWS)
async def test_stream_error_event_of_a_run_with_no_usable_result_matches_the_plain_answer(
    name: str, script: Any, http_status: int, error_code: str
) -> None:
    """SE-S4: a succeeded run with no usable result gives the same code and flag on both routes."""
    plain = await post(chat_app(script).app, body())
    streamed = await post(chat_app(script).app, stream_body())

    event = _event(data_payloads(streamed.content))
    assert plain.status_code == http_status
    assert event["code"] == plain.json()["error"]["code"] == error_code, name
    assert event["should_retry"] is (plain.headers["x-should-retry"] == "true")
    assert "retry_after" not in event


async def test_error_event_keeps_message_type_code_and_adds_the_flag() -> None:
    """SE-4 / SE-S6: the three keys of today stay; the flag is added; retry_after only when set."""
    plain = data_payloads(error_event("failed", "server_error", "timeout", should_retry=False))[0]
    retried = data_payloads(
        error_event(
            "restart", "server_error", "server_restarting", should_retry=True, retry_after=5
        )
    )[0]
    assert isinstance(plain, dict)
    assert isinstance(retried, dict)

    assert plain == {
        "error": {
            "message": "failed",
            "type": "server_error",
            "code": "timeout",
            "should_retry": False,
        }
    }
    assert retried["error"]["should_retry"] is True
    assert retried["error"]["retry_after"] == 5


# --- SE-3: an unexpected error (SE-2 is in test_chat_stream_route.py) -------------------


async def test_unexpected_error_event_is_not_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    """SE-3 / SE-S5: an error that no stage expected is internal_error, with no retry."""
    ca = chat_app(None)

    async def broken(topic: str, from_sequence: int | None = None) -> AsyncIterator[Any]:
        raise RuntimeError("scan failed")
        yield

    monkeypatch.setattr(ca.stream, "subscribe", broken)
    resp = await post(ca.app, stream_body())

    event = _event(data_payloads(resp.content))
    assert event["code"] == "internal_error"
    assert event["should_retry"] is False
    assert "retry_after" not in event


# --- SE-5, SE-7: one reply shape -------------------------------------------------------------


def _reply_from_chunks(payloads: list[dict[str, Any] | str]) -> dict[str, Any]:
    """The reply that a client builds from the chunks (contracts C2.3): the reference rule.

    WHY here and not in the Engine: the Engine has no such builder; the SDK has one. This one
    pins the rule that the SDK copies, so the two cannot drift without a red test.
    """
    assert payloads[-1] == "[DONE]"
    chunks = [p for p in payloads if isinstance(p, dict)]
    message: dict[str, Any] = {"role": "assistant", "content": None, "refusal": None}
    tool_calls: list[dict[str, Any]] = []
    finish_reason = None
    usage = info = None
    for chunk in chunks:
        for choice in chunk["choices"]:
            delta = choice["delta"]
            if "content" in delta:
                message["content"] = delta["content"]
            if "refusal" in delta:
                message["refusal"] = delta["refusal"]
            for call in delta.get("tool_calls", []):
                tool_calls.append({k: v for k, v in call.items() if k != "index"})
            if choice["finish_reason"] is not None:
                finish_reason = choice["finish_reason"]
        usage = chunk.get("usage", usage)
        info = chunk.get("screamingface", info)
    message["tool_calls"] = tool_calls or None
    return {
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
        "screamingface": info,
    }


_RESULTS: list[tuple[str, ChatResult, bool]] = [
    ("text", chat_result(), True),
    ("text-no-cost", chat_result(), False),
    (
        "refusal",
        chat_result(status="refused", content="", refusal="no", finish_reason="content_filter"),
        True,
    ),
    (
        "tool-calls-with-text",
        chat_result(content="Let me check.", tool_calls=_calls(), finish_reason="tool_calls"),
        True,
    ),
    (
        "tool-calls-no-text",
        chat_result(content="", tool_calls=_calls(), finish_reason="tool_calls"),
        True,
    ),
    (
        "abstained",
        chat_result(
            status="abstained", content="", finish_reason="stop", abstain_reason="budget_refused"
        ),
        True,
    ),
]


@pytest.mark.parametrize(("name", "result", "cost"), _RESULTS, ids=[r[0] for r in _RESULTS])
async def test_reply_built_from_the_frames_equals_the_plain_reply(
    name: str, result: ChatResult, cost: bool
) -> None:
    """SE-5 (risk R4): choices, usage and screamingface are equal; id and created are not
    compared."""
    ca: ChatApp = chat_app(answered(result, cost=cost))
    plain = (await post(ca.app, body())).json()
    streamed = await post(ca.app, stream_body(stream_options={"include_usage": True}))

    built = _reply_from_chunks(data_payloads(streamed.content))
    assert built["choices"] == plain["choices"], name
    assert built["usage"] == plain["usage"], name
    assert built["screamingface"] == plain["screamingface"], name


async def test_plain_reply_with_tool_calls_and_no_text_has_null_content() -> None:
    """SE-7 / SE-S7: as OpenAI sends it; a reply with text keeps its text."""
    no_text = chat_result(content="", tool_calls=_calls(), finish_reason="tool_calls")
    with_text = chat_result(
        content="Let me check.", tool_calls=_calls(), finish_reason="tool_calls"
    )

    empty = (await post(chat_app(answered(no_text)).app, body())).json()
    kept = (await post(chat_app(answered(with_text)).app, body())).json()

    assert empty["choices"][0]["message"]["content"] is None
    assert empty["choices"][0]["message"]["tool_calls"][0]["id"] == "call_1"
    assert kept["choices"][0]["message"]["content"] == "Let me check."
