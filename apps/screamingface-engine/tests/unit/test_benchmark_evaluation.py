"""Installed evaluation capabilities adapt distinct Benchmark semantics to URL4 routes."""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.evaluation import (
    aggregate_endpoint,
    candidate_answer,
    case_evaluation_endpoint,
)
from url4 import RelExpr, Text, render
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


def _call(path: str, context: str, intent: str) -> str:
    return render(RelExpr(path=path, context=context, intent=Text(intent)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "item_name", "marker"),
    (
        ("/draco/case", "Criterion evaluation", "criterion"),
        ("/healthbench/case", "Rubric evaluation", "rubric"),
    ),
)
async def test_case_evaluation_endpoint_adapts_two_benchmark_binders(
    route: str,
    item_name: str,
    marker: str,
) -> None:
    node = Url4Node("case-evaluation")

    def bind(case_id: int, items: list[dict[str, object]]) -> dict[str, object]:
        return {"case_id": case_id, "kind": marker, "items": items}

    node.endpoint(route)(
        case_evaluation_endpoint(
            label=f"{marker} Case evaluation",
            item_name=item_name,
            bind=bind,
        )
    )
    context = json.dumps([json.dumps({"value": 1}), {"value": 2}])

    result = json.loads((await node.evaluate(_call(route, context, "7"))).text)

    assert result == {
        "case_id": 7,
        "kind": marker,
        "items": [{"value": 1}, {"value": 2}],
    }


@pytest.mark.asyncio
async def test_aggregate_endpoint_validates_selection_and_passes_case_evaluations_as_context() -> (
    None
):
    node = Url4Node("aggregate")

    def aggregate(case_evaluations: str, selected_case_count: int) -> dict[str, object]:
        return {
            "selected_case_count": selected_case_count,
            "case_evaluations": json.loads(case_evaluations),
        }

    node.endpoint("/benchmark/aggregate")(
        aggregate_endpoint(label="Example", available_case_count=3, aggregate=aggregate)
    )

    result = json.loads(
        (await node.evaluate(_call("/benchmark/aggregate", '[{"case_id":1}]', "aggregate:1"))).text
    )
    assert result == {
        "selected_case_count": 1,
        "case_evaluations": [{"case_id": 1}],
    }

    for intent in ("aggregate:0", "aggregate:4", "aggregate:invalid", "aggregate:²"):
        with pytest.raises(ResolutionError) as caught:
            await node.evaluate(_call("/benchmark/aggregate", "[]", intent))
        assert caught.value.code == "benchmark_unavailable"

    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(_call("/benchmark/aggregate", "[]", "summarize:1"))
    assert caught.value.code == "benchmark_operation_unsupported"


def test_candidate_answer_preserves_completion_and_exposes_exact_refusal_for_grading() -> None:
    answer = candidate_answer(encode_candidate_invocation("answer", "length", None))
    assert (answer.output, answer.finish_reason) == ("answer", "length")

    refused = candidate_answer(encode_candidate_invocation("", "content_filter", "exact refusal"))
    assert refused.text == "exact refusal"
    assert refused.output is None
    assert refused.refusal == "exact refusal"
    assert refused.finish_reason == "content_filter"


# --- OME-993: a collected upstream failure must propagate, never misdiagnose ---------


@pytest.mark.asyncio
async def test_a_collected_error_item_reraises_the_original_failure() -> None:
    # INVARIANT: an `{"error": ...}` row that url4's `on_error=collect` put into the
    # evaluator-record array is an UPSTREAM failure (e.g. a Judge call that 429'd),
    # not an evaluator record — the route must surface that original cause verbatim
    # instead of rejecting the row's shape ("invalid Criterion envelope", GH #740).
    node = Url4Node("case-evaluation")
    bound: list[object] = []

    def bind(case_id: int, items: list[dict[str, object]]) -> dict[str, object]:
        bound.append(items)
        return {"case_id": case_id}

    node.endpoint("/draco/case")(
        case_evaluation_endpoint(
            label="DRACO Case evaluation",
            item_name="Criterion evaluation",
            bind=bind,
        )
    )
    context = json.dumps(
        [
            {"value": 1},
            {
                "error": {
                    "kind": "ResolutionError",
                    "message": "aigateway request failed with status 429",
                    "code": "aigateway_http_429",
                    "retryable": True,
                }
            },
        ]
    )

    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(_call("/draco/case", context, "7"))

    assert caught.value.code == "aigateway_http_429"
    assert caught.value.permanent is False
    assert "aigateway request failed with status 429" in str(caught.value)
    assert "Criterion evaluation 2" in str(caught.value)
    assert "envelope" not in str(caught.value)
    assert bound == []


@pytest.mark.asyncio
async def test_a_lean_error_item_still_propagates_message_with_a_default_code() -> None:
    # A collected row from a non-Url4Error carries only kind+message; the route still
    # propagates the message and stays retryable (the upstream cause is unknown).
    node = Url4Node("case-evaluation")
    node.endpoint("/hb/case")(
        case_evaluation_endpoint(
            label="HealthBench Case evaluation",
            item_name="Rubric evaluation",
            bind=lambda case_id, items: {"case_id": case_id},
        )
    )
    context = json.dumps([{"error": {"kind": "ValueError", "message": "boom"}}])

    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(_call("/hb/case", context, "3"))

    assert caught.value.code == "grading_dependency_failed"
    assert caught.value.permanent is False
    assert "boom" in str(caught.value)


@pytest.mark.asyncio
async def test_an_item_merely_containing_an_error_key_is_not_an_error_row() -> None:
    # Same strictness as the case-execution decoder: ONLY the exact one-key
    # `{"error": {...}}` shape is a collected failure; anything else stays an
    # evaluator record for the binder to judge.
    node = Url4Node("case-evaluation")
    node.endpoint("/draco/case")(
        case_evaluation_endpoint(
            label="DRACO Case evaluation",
            item_name="Criterion evaluation",
            bind=lambda case_id, items: {"case_id": case_id, "items": items},
        )
    )
    context = json.dumps([{"error": {"kind": "X"}, "value": 2}, {"error": "text"}])

    result = json.loads((await node.evaluate(_call("/draco/case", context, "7"))).text)

    assert result == {
        "case_id": 7,
        "items": [{"error": {"kind": "X"}, "value": 2}, {"error": "text"}],
    }
