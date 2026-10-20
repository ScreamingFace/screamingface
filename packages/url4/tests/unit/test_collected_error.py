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
