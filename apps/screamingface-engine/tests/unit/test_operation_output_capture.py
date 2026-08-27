"""Per-operation output capture in the Candidate Invocation envelope (OME-843).

INVARIANT defended: a Fusion Case artifact carries each member and synthesis
operation's terminal output keyed by its stable operation id — attributed by the
resolved request fingerprint (path + params), never by position. A solo Model gains
its one natural named operation; an unattributed shape keeps the legacy envelope.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from screamingface_engine.benchmarks.contract import (
    OperationAccounting,
    OperationCache,
    OperationOutput,
    OperationUsage,
    decode_candidate_invocation_record,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.operation_outputs import attribute_operation_outputs
from screamingface_engine.operation_calls import (
    OperationCall,
    capture_operation_calls,
    operation_call_identity,
    record_operation_call,
)
from url4 import RelExpr, expr, render, src, text


def _fusion_expression(*, duplicate_members: bool = False) -> str:
    """Render the compiled Fusion shape: named member sources plus a synthesis source."""

    member_2_path = "/provider/alpha" if duplicate_members else "/provider/beta"
    member_2_params: tuple[tuple[str, str], ...] = (
        (("temperature", "0.0"),) if duplicate_members else ()
    )
    return render(
        expr(
            src(
                RelExpr(
                    path="/provider/alpha",
                    context="$input",
                    intent=text("Answer plainly."),
                    params=(("temperature", "0.0"),),
                ),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path=member_2_path,
                    context="$input",
                    intent=text("Answer plainly."),
                    params=member_2_params,
                ),
                name="model_2",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path="/provider/alpha",
                    context="$model_1 / $model_2",
                    intent=text("Fuse the answers."),
                    params=(("temperature", "0.5"),),
                ),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )


def _call(
    path: str,
    params: tuple[tuple[str, str], ...],
    output: str,
    finish_reason: str | None = "stop",
    accounting: OperationAccounting | None = None,
) -> OperationCall:
    return OperationCall(
        path=path,
        params=params,
        output=output,
        finish_reason=finish_reason,
        accounting=accounting,
    )


def _accounting(*, cost: str = "0.01") -> OperationAccounting:
    return OperationAccounting(
        provider="openrouter",
        request_model="provider/alpha",
        response_model="provider/served",
        usage=OperationUsage(
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=1,
            cost_usd=cost,
        ),
        provider_latency_ms=25,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


# --- contract envelope -----------------------------------------------------------------


def test_invocation_without_operations_keeps_the_exact_legacy_shape() -> None:
    encoded = encode_candidate_invocation("answer", "stop", None)

    assert set(json.loads(encoded)) == {
        "schema",
        "status",
        "output",
        "finish_reason",
        "refusal",
        "execution",
    }
    assert decode_candidate_invocation_record(encoded).operations is None


def test_invocation_operations_round_trip_in_order() -> None:
    operations = [
        OperationOutput(
            operation_id="op_model_1", output="alpha", finish_reason="stop", accounting=None
        ),
        OperationOutput(
            operation_id="op_model_2", output=None, finish_reason=None, accounting=None
        ),
        OperationOutput(
            operation_id="op_synthesis_1",
            output="fused",
            finish_reason="stop",
            accounting=None,
        ),
    ]

    decoded = decode_candidate_invocation_record(
        encode_candidate_invocation("fused", "stop", None, operations=operations)
    )

    assert decoded.operations == operations


def test_invocation_rejects_a_malformed_operations_entry() -> None:
    encoded = encode_candidate_invocation("answer", "stop", None)
    payload = json.loads(encoded)
    payload["operations"] = [{"operation_id": "", "output": None, "finish_reason": None}]

    with pytest.raises(ValueError, match="operation"):
        decode_candidate_invocation_record(json.dumps(payload))


# --- attribution -----------------------------------------------------------------------


def test_each_operation_receives_its_own_fingerprinted_output() -> None:
    calls = [
        _call("/provider/alpha", (("temperature", "0.0"),), "alpha answer"),
        _call("/provider/beta", (), "beta answer"),
        _call("/provider/alpha", (("temperature", "0.5"),), "fused answer"),
    ]

    operations = attribute_operation_outputs(_fusion_expression(), calls)

    assert operations is not None
    assert [(op.operation_id, op.output) for op in operations] == [
        ("op_model_1", "alpha answer"),
        ("op_model_2", "beta answer"),
        ("op_synthesis_1", "fused answer"),
    ]


def test_byte_identical_members_share_only_an_identical_output() -> None:
    # INVARIANT: two members with the same path AND params are indistinguishable —
    # identical recorded outputs attribute to both, anything else stays null. Never
    # a positional guess.
    identical = [
        _call("/provider/alpha", (("temperature", "0.0"),), "same answer"),
        _call("/provider/alpha", (("temperature", "0.0"),), "same answer"),
        _call("/provider/alpha", (("temperature", "0.5"),), "fused answer"),
    ]
    divergent = [
        _call("/provider/alpha", (("temperature", "0.0"),), "first answer"),
        _call("/provider/alpha", (("temperature", "0.0"),), "second answer"),
        _call("/provider/alpha", (("temperature", "0.5"),), "fused answer"),
    ]

    shared = attribute_operation_outputs(_fusion_expression(duplicate_members=True), identical)
    nulled = attribute_operation_outputs(_fusion_expression(duplicate_members=True), divergent)

    assert shared is not None and nulled is not None
    assert [op.output for op in shared] == ["same answer", "same answer", "fused answer"]
    assert [op.output for op in nulled] == [None, None, "fused answer"]


def test_a_member_that_never_called_stays_null() -> None:
    calls = [
        _call("/provider/alpha", (("temperature", "0.0"),), "alpha answer"),
        _call("/provider/alpha", (("temperature", "0.5"),), "fused answer"),
    ]

    operations = attribute_operation_outputs(_fusion_expression(), calls)

    assert operations is not None
    assert [(op.operation_id, op.output) for op in operations] == [
        ("op_model_1", "alpha answer"),
        ("op_model_2", None),
        ("op_synthesis_1", "fused answer"),
    ]


def test_a_solo_nested_recipe_without_an_attributed_call_keeps_operations_absent() -> None:
    nested = expr(
        src(
            RelExpr(path="/provider/alpha", context="$input", intent=text("Answer plainly.")),
            name="model_1",
            weight=0.0,
        ),
        intent=text("$model_1"),
    )
    candidate = render(
        expr(
            src(nested, name="model_1", weight=0.0),
            intent=text("$model_1"),
        )
    )

    assert attribute_operation_outputs(candidate, []) is None


def test_an_unattributed_multi_operation_candidate_keeps_explicit_null_entries() -> None:
    operations = attribute_operation_outputs(_fusion_expression(), [])

    assert operations is not None
    assert [
        (operation.operation_id, operation.output, operation.finish_reason, operation.accounting)
        for operation in operations
    ] == [
        ("op_model_1", None, None, None),
        ("op_model_2", None, None, None),
        ("op_synthesis_1", None, None, None),
    ]


def test_unique_operation_receives_all_of_its_call_accounting() -> None:
    calls = [
        _call(
            "/provider/alpha",
            (("temperature", "0.0"),),
            "alpha answer",
            accounting=_accounting(cost="0.01"),
        ),
        _call(
            "/provider/beta",
            (),
            "beta answer",
            accounting=_accounting(cost="0.02"),
        ),
        _call(
            "/provider/alpha",
            (("temperature", "0.5"),),
            "fused answer",
            accounting=_accounting(cost="0.03"),
        ),
    ]

    operations = attribute_operation_outputs(_fusion_expression(), calls)

    assert operations is not None
    assert [
        operation.accounting.usage.cost_usd for operation in operations if operation.accounting
    ] == ["0.01", "0.02", "0.03"]


def test_ambiguous_operations_never_copy_one_call_ledger_to_several_owners() -> None:
    calls = [
        _call(
            "/provider/alpha",
            (("temperature", "0.0"),),
            "same answer",
            accounting=_accounting(),
        ),
        _call(
            "/provider/alpha",
            (("temperature", "0.0"),),
            "same answer",
            accounting=_accounting(),
        ),
        _call(
            "/provider/alpha",
            (("temperature", "0.5"),),
            "fused answer",
            accounting=_accounting(),
        ),
    ]

    operations = attribute_operation_outputs(_fusion_expression(duplicate_members=True), calls)

    assert operations is not None
    assert [operation.output for operation in operations[:2]] == ["same answer", "same answer"]
    assert [operation.accounting for operation in operations[:2]] == [None, None]
    assert operations[2].accounting is not None


def test_a_solo_candidate_retains_its_natural_model_operation() -> None:
    solo = render(
        expr(
            src(
                RelExpr(
                    path="/provider/alpha",
                    context="$input",
                    intent=text("Answer plainly."),
                ),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )

    operations = attribute_operation_outputs(
        solo,
        [_call("/provider/alpha", (), "answer", accounting=_accounting())],
    )

    assert operations is not None
    assert [(operation.operation_id, operation.output) for operation in operations] == [
        ("op_model_1", "answer")
    ]
    assert operations[0].accounting is not None


def test_an_unparseable_expression_records_no_operations() -> None:
    assert attribute_operation_outputs("!!not url4", [_call("/p", (), "x")]) is None


# --- task-local recorder ---------------------------------------------------------------


def test_operation_calls_record_identity_only_inside_a_capture_scope() -> None:
    with capture_operation_calls() as calls:
        with operation_call_identity("/provider/alpha", {"temperature": "0.0"}):
            record_operation_call("captured", "stop")
        record_operation_call("no identity — dropped", "stop")
    record_operation_call("no scope — dropped", "stop")

    assert calls == [
        OperationCall(
            path="/provider/alpha",
            params=(("temperature", "0.0"),),
            output="captured",
            finish_reason="stop",
            accounting=None,
        )
    ]


# --- end to end through the real connector ---------------------------------------------


def _per_model_response() -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "provider/beta":
            content = "beta answer"
        elif body.get("temperature") == 0.5:
            content = "fused answer"
        else:
            content = "alpha answer"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    return respond


@pytest.mark.asyncio
async def test_a_fusion_invocation_carries_every_member_and_synthesis_output() -> None:
    from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
    from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
    from screamingface_engine.world_config import ModelSpec

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_per_model_response()),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha",
            models=(ModelSpec(id="provider/alpha"), ModelSpec(id="provider/beta")),
        ),
        client=client,
    )
    try:
        encoded = await evaluate_candidate_recipe(
            world.node, _fusion_expression(), "why is the sky blue?"
        )
    finally:
        await world.aclose()
        await client.aclose()

    decoded = decode_candidate_invocation_record(encoded)

    assert decoded.output == "fused answer"
    assert decoded.operations is not None
    assert [(op.operation_id, op.output, op.finish_reason) for op in decoded.operations] == [
        ("op_model_1", "alpha answer", "stop"),
        ("op_model_2", "beta answer", "stop"),
        ("op_synthesis_1", "fused answer", "stop"),
    ]
    assert [
        (
            operation.accounting.request_model,
            operation.accounting.usage.input_tokens,
            operation.accounting.usage.output_tokens,
            operation.accounting.cache.unknown,
        )
        for operation in decoded.operations
        if operation.accounting is not None
    ] == [
        ("provider/alpha", 4, 2, 1),
        ("provider/beta", 4, 2, 1),
        ("provider/alpha", 4, 2, 1),
    ]


# --- case artifact threading -----------------------------------------------------------


def test_case_record_carries_operations_only_when_attributed() -> None:
    from screamingface_engine.benchmarks.case_records import bind_case_record
    from screamingface_engine.benchmarks.evaluation import CandidateAnswer

    cases = json.dumps([{"id": 1, "input": "Explain DiD estimators."}])
    base = {
        "status": "completed",
        "text": "fused",
        "output": "fused",
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
    }
    attributed = bind_case_record(
        cases,
        case_id=1,
        candidate=CandidateAnswer(
            **base,
            operations=(
                OperationOutput(
                    operation_id="op_model_1",
                    output="alpha",
                    finish_reason="stop",
                    accounting=None,
                ),
            ),
        ),
        schema="example.case.v1",
        benchmark="EXAMPLE",
    )
    solo = bind_case_record(
        cases,
        case_id=1,
        candidate=CandidateAnswer(**base, operations=None),
        schema="example.case.v1",
        benchmark="EXAMPLE",
    )

    assert attributed["operations"] == [
        {
            "operation_id": "op_model_1",
            "output": "alpha",
            "finish_reason": "stop",
            "accounting": None,
        }
    ]
    # INVARIANT: absence stays absence — an unattributed Candidate keeps the legacy shape.
    assert "operations" not in solo


def test_scored_case_result_exports_operations_only_when_present() -> None:
    from screamingface_engine.benchmarks.aggregation import SelectedCase, scored_case_result

    selected = SelectedCase(case_id=1, input="Explain DiD estimators.", metadata={})
    grade = {"method": "rubric", "score": 1.0, "metrics": {}, "checks": []}

    attributed = scored_case_result(
        selected_case=selected,
        output="fused",
        finish_reason="stop",
        grade=grade,
        operations=[
            {
                "operation_id": "op_model_1",
                "output": "alpha",
                "finish_reason": "stop",
                "accounting": None,
            }
        ],
    ).model_dump(by_alias=True)
    solo = scored_case_result(
        selected_case=selected,
        output="fused",
        finish_reason="stop",
        grade=grade,
    ).model_dump(by_alias=True)

    assert attributed["operations"] == [
        {
            "operation_id": "op_model_1",
            "output": "alpha",
            "finish_reason": "stop",
            "accounting": None,
        }
    ]
    assert "operations" not in solo
