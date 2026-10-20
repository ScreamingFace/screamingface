"""The collected-error row is public: a code handler that grades in process writes the same row.

STORY: as a node author whose code mount runs several steps in process, I record a failed step
in the exact shape ``iteration.on_error=collect`` writes, so readers of collected rows need no
second decoder.
"""

from __future__ import annotations

import asyncio
import json

from url4.core.errors import ResolutionError
from url4.dag import collected_error
from url4.peer.server import Url4Node


def test_a_url4_error_keeps_its_code_and_retryability() -> None:
    row = collected_error(ResolutionError("gone", code="benchmark_unavailable", permanent=True))

    assert row == {
        "error": {
            "kind": "ResolutionError",
            "message": "gone",
            "code": "benchmark_unavailable",
            "retryable": False,
        }
    }


def test_a_plain_exception_carries_kind_and_message_only() -> None:
    assert collected_error(ValueError("bad")) == {"error": {"kind": "ValueError", "message": "bad"}}


def test_an_empty_message_falls_back_to_the_repr() -> None:
    assert collected_error(ValueError()) == {
        "error": {"kind": "ValueError", "message": "ValueError()"}
    }


def test_it_is_the_row_iteration_collects() -> None:
    # INVARIANT: one shape for a failed row, whoever writes it.
    node = Url4Node("collect")
    failure = ResolutionError("boom", code="candidate_failed", permanent=True)

    @node.endpoint("/fail")
    async def fail(request: object) -> str:
        raise failure

    result = asyncio.run(node.evaluate("('a')*(x:0.0:/fail?q=('y')!'z')!'$x'"))

    assert json.loads(result.text) == [collected_error(failure)]


def test_a_failed_code_call_is_intent_error_with_its_handlers_cause() -> None:
    # INVARIANT: Spec C §13.6 — a failed intent is intent_error, permanent; the handler's own
    # code and retryability ride beside it as the `cause`, in the raised error and in the row.
    from url4 import RelUrl, expr, render, src, text
    from url4.core.errors import ErrorCause, Url4Error

    node = Url4Node("cause")

    @node.code("/judge")
    def judge(call: object) -> str:
        raise ResolutionError("judge ran dry", code="judge_reply_invalid", permanent=False)

    expression = render(expr(src(text("x"), name="a", weight=0.0), intent=RelUrl("/judge")))
    try:
        asyncio.run(node.evaluate(expression))
    except Url4Error as exc:
        failure = exc
    else:  # pragma: no cover - the call must fail
        raise AssertionError("the code call did not fail")

    assert failure.code == "intent_error"
    assert failure.permanent is True
    assert failure.cause == ErrorCause("judge_reply_invalid", permanent=False)
    assert collected_error(failure)["error"]["cause"] == {
        "code": "judge_reply_invalid",
        "retryable": True,
    }


def test_a_code_call_inside_a_code_call_keeps_the_innermost_cause() -> None:
    from url4.core.errors import ErrorCause, Url4Error
    from url4.dag.nodes.code import _cause

    inner = Url4Error("outer", code="intent_error", cause=ErrorCause("benchmark_unavailable", True))

    assert _cause(inner) == ErrorCause("benchmark_unavailable", True)
    assert _cause(ValueError("no code")) is None


def test_the_terminal_frame_carries_the_cause() -> None:
    from url4.core.errors import ErrorCause, Url4Error
    from url4.streaming.lifecycle import _error_info

    info = _error_info(
        Url4Error("failed", code="intent_error", cause=ErrorCause("benchmark_unavailable", True))
    )

    assert info.code == "intent_error"
    assert info.cause is not None
    assert (info.cause.code, info.cause.permanent) == ("benchmark_unavailable", True)
    assert _error_info(ValueError("plain")).cause is None
