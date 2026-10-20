"""A failed Benchmark code step keeps the code its handler declared (owner decision 2026-10-20).

STORY: as a researcher whose run failed in a Benchmark's aggregate, I read the failure the
Benchmark declared (`benchmark_unavailable`, a retryable judge failure), not url4's generic
`intent_error` — which still heads the error, as Spec C §13.6 requires.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.aggregation import public_error
from screamingface_engine.benchmarks.case_evaluation import aggregate_code
from screamingface_engine.benchmarks.code_calls import run_aggregate
from url4.core.errors import ErrorCause, Url4Error
from url4.peer.server import Url4Node


def test_a_collected_row_reports_its_handlers_cause() -> None:
    projected = public_error(
        {
            "kind": "Url4Error",
            "code": "intent_error",
            "message": "code '/x/aggregate' failed: judge_reply_invalid: empty reply",
            "retryable": False,
            "cause": {"code": "judge_reply_invalid", "retryable": True},
        },
        default_code="grading_failed",
        default_message="grading failed",
    )

    assert (projected.code, projected.retryable) == ("judge_reply_invalid", True)


def test_a_row_without_a_cause_is_projected_as_before() -> None:
    projected = public_error(
        {"kind": "ResolutionError", "code": "benchmark_unavailable", "retryable": False},
        default_code="grading_failed",
        default_message="grading failed",
    )

    assert (projected.code, projected.retryable) == ("benchmark_unavailable", False)


@pytest.mark.asyncio
async def test_a_failed_aggregate_raises_intent_error_with_the_declared_cause() -> None:
    node = Url4Node("aggregate")

    async def missing(raw: str, count: int) -> dict[str, object]:
        raise OSError("answer key unreadable")

    node.code("/b/aggregate")(aggregate_code(label="B", available_case_count=3, aggregate=missing))

    with pytest.raises(Url4Error) as caught:
        await run_aggregate(node, "/b/aggregate", "[]", 1)

    assert caught.value.code == "intent_error"
    assert caught.value.cause == ErrorCause("benchmark_unavailable", permanent=True)
