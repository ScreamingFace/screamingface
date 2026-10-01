"""Combine evidence on the Candidate envelope and in attribution (OME-1289 E4a, unit 3).

FEATURE: a reducer Candidate's per-operation record carries its ``CombineEvidence`` to the wire.
STORY: as a reader of a Case result, I see the evidence on ``op_synthesis_N`` and nowhere else,
and an envelope with no reducer is byte for byte what it was before.
INVARIANT defended: the envelope encoder keeps no ``sort_keys``, a null ``combine`` leaves no key,
and attribution copies evidence only when exactly one binding claims the fingerprint.
"""

from __future__ import annotations

import json
from typing import Any

from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.benchmarks.contract import (
    CaseGrade,
    CaseResult,
    OperationAccounting,
    OperationCache,
    OperationOutput,
    OperationUsage,
    decode_candidate_invocation_record,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.graded_results import encode_result
from screamingface_engine.benchmarks.operation_outputs import attribute_operation_outputs
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.combine.evidence import CombineEvidence
from screamingface_engine.operation_calls import OperationCall
from url4 import RelExpr, Text, expr, render, src

_MODEL_ONLY_OPERATION = OperationOutput(
    operation_id="op_model_1", output="A", finish_reason="stop", accounting=None
)
_OPERATION_JSON = (
    '{"operation_id":"op_model_1","output":"A","finish_reason":"stop","accounting":null}'
)


# --- EV-1 (CHAR, passes before any delta) -----------------------------------------------------


def test_envelope_without_reducer_is_byte_identical() -> None:
    encoded = encode_candidate_invocation(
        "answer", "stop", None, operations=[_MODEL_ONLY_OPERATION]
    )

    assert encoded == (
        '{"schema":"screamingface.candidate-invocation.v1","status":"completed",'
        '"output":"answer","finish_reason":"stop","refusal":null,"execution":null,'
        f'"operations":[{_OPERATION_JSON}]}}'
    )


def _case_with_operation() -> CaseResult:
    return CaseResult(
        status="scored",
        case_id=1,
        input="in",
        output="answer",
        finish_reason="stop",
        refusal=None,
        grade=CaseGrade(method="test", score=1.0, metrics={}, checks=[]),
        failures=[],
        metadata={},
        operations=[_MODEL_ONLY_OPERATION],
    )


_CASE_JSON = (
    '{"status":"scored","case_id":1,"input":"in","output":"answer","finish_reason":"stop",'
    '"refusal":null,"stop_reason":null,"rounds_executed":null,'
    '"grade":{"method":"test","score":1.0,"metrics":{},"checks":[]},'
    f'"failures":[],"metadata":{{}},"operations":[{_OPERATION_JSON}]}}'
)


def test_case_result_without_reducer_is_byte_identical() -> None:
    case = _case_with_operation()

    encoded = json.dumps(case.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))

    assert encoded == _CASE_JSON


def test_graded_row_without_reducer_is_byte_identical() -> None:
    """The production encoder (``graded_results.encode_result``) writes the same bytes."""
    encoded = encode_result(_case_with_operation(), benchmark_id="b", revision="r1")

    assert encoded == (
        '{"schema":"screamingface.graded-case.v1","benchmark_id":"b","revision":"r1",'
        f'"result":{_CASE_JSON}}}'
    )


# --- EV-2 (CHAR, passes before any delta) -----------------------------------------------------


def _combine_expression(*bindings: str) -> str:
    """One source per binding, every one a bare combine call with no params."""
    sources = [
        src(
            RelExpr(path=COMBINE_ROUTE, context="$input", intent=Text("spec")),
            name=binding,
            weight=0.0,
        )
        for binding in bindings
    ]
    return render(expr(*sources, intent=Text("$synthesis_1")))


def _call(output: str, evidence: CombineEvidence | None = None) -> OperationCall:
    return OperationCall(
        path=COMBINE_ROUTE,
        params=(),
        output=output,
        finish_reason="stop",
        accounting=None,
        combine=evidence,
    )


def test_ambiguous_fingerprint_stays_null() -> None:
    operations = attribute_operation_outputs(
        _combine_expression("synthesis_1", "synthesis_2"), [_call("first"), _call("second")]
    )

    assert operations is not None
    assert [(op.operation_id, op.output, op.finish_reason) for op in operations] == [
        ("op_synthesis_1", None, None),
        ("op_synthesis_2", None, None),
    ]


# --- EV-5 -------------------------------------------------------------------------------------


def _evidence() -> CombineEvidence:
    """Real evidence: a vote on "x" over three members (member_1 and member_3 hold it)."""
    return run(spec_text(vote_spec(3)), context_text(["a x", "b y", "c x"])).evidence


def test_operation_output_omits_combine_when_null() -> None:
    assert "combine" not in _MODEL_ONLY_OPERATION.model_dump(by_alias=True)


def test_operation_output_round_trips_combine_evidence() -> None:
    evidence = _evidence()
    operation = OperationOutput(
        operation_id="op_synthesis_1",
        output="a x",
        finish_reason="stop",
        accounting=None,
        combine=evidence,
    )

    decoded = decode_candidate_invocation_record(
        encode_candidate_invocation("a x", "stop", None, operations=[operation])
    )

    assert decoded.operations is not None
    assert decoded.operations[0].combine == evidence
    assert decoded.operations[0].combine is not None
    assert decoded.operations[0].combine.tally is not None


# --- EV-4 and the last-call rule --------------------------------------------------------------


def test_attribution_copies_combine_evidence_to_operation_output() -> None:
    evidence = _evidence()

    operations = attribute_operation_outputs(
        _combine_expression("synthesis_1"), [_call("a x", evidence)]
    )

    assert operations is not None
    assert [(op.operation_id, op.output, op.finish_reason) for op in operations] == [
        ("op_synthesis_1", "a x", "stop")
    ]
    assert operations[0].combine == evidence
    assert operations[0].accounting is None


def test_ambiguous_combine_fingerprint_keeps_combine_null() -> None:
    evidence = _evidence()

    operations = attribute_operation_outputs(
        _combine_expression("synthesis_1", "synthesis_2"),
        [_call("same", evidence), _call("same", evidence)],
    )

    assert operations is not None
    # Identical outputs still attribute to each claimant, but the evidence is never invented.
    assert [(op.output, op.combine) for op in operations] == [("same", None), ("same", None)]


def test_a_repeated_combine_call_keeps_the_last_evidence() -> None:
    first = _evidence()
    last = run(spec_text(vote_spec(3)), context_text(["a y", "b y", "c x"])).evidence
    assert first != last

    operations = attribute_operation_outputs(
        _combine_expression("synthesis_1"), [_call("a x", first), _call("a y", last)]
    )

    assert operations is not None
    assert operations[0].output == "a y"
    assert operations[0].combine == last


# --- EV-9 -------------------------------------------------------------------------------------


def test_judge_and_writer_bindings_are_attributed() -> None:
    operations = attribute_operation_outputs(
        _combine_expression("judge_1", "writer_2", "answer_5"), [_call("only")]
    )

    # Three sources share one fingerprint, but `answer_5` is not a named operation at all.
    assert operations is not None
    assert [(op.operation_id, op.output) for op in operations] == [
        ("op_judge_1", "only"),
        ("op_writer_2", "only"),
    ]


def test_a_judge_binding_alone_takes_its_own_call() -> None:
    operations = attribute_operation_outputs(_combine_expression("judge_1"), [_call("verdict")])

    assert operations is not None
    assert [(op.operation_id, op.output) for op in operations] == [("op_judge_1", "verdict")]


def test_envelope_dump_key_order_is_declaration_order() -> None:
    evidence_dump: dict[str, Any] = _evidence().model_dump(by_alias=True)

    assert list(evidence_dump) == [
        "schema",
        "kind",
        "reducer",
        "operators",
        "members",
        "tally",
        "judge",
        "fields",
        "chosen",
        "built",
        "agreement",
        "tie",
        "median",
        "presentation_order",
        "separator_collision",
        "finish_reason",
    ]


def _accounting(model: str) -> OperationAccounting:
    return OperationAccounting(
        provider="openrouter",
        request_model=model,
        response_model=model,
        usage=OperationUsage(
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=0,
            cost_usd="0.01",
        ),
        provider_latency_ms=25,
        provider_attempts=1,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


def test_judge_and_writer_model_routes_are_attributed_their_own_output_and_accounting() -> None:
    expression = render(
        expr(
            src(
                RelExpr(path="/provider/alpha", context="$input", intent=Text("judge")),
                name="judge_1",
                weight=0.0,
            ),
            src(
                RelExpr(path="/provider/beta", context="$input", intent=Text("write")),
                name="writer_2",
                weight=0.0,
            ),
            intent=Text("$writer_2"),
        )
    )
    calls = [
        OperationCall("/provider/alpha", (), "member_2", "stop", _accounting("provider/alpha")),
        OperationCall("/provider/beta", (), "drafted", "length", _accounting("provider/beta")),
    ]

    operations = attribute_operation_outputs(expression, calls)

    assert operations is not None
    assert [(op.operation_id, op.output, op.finish_reason) for op in operations] == [
        ("op_judge_1", "member_2", "stop"),
        ("op_writer_2", "drafted", "length"),
    ]
    assert [op.accounting.request_model for op in operations if op.accounting] == [
        "provider/alpha",
        "provider/beta",
    ]
    assert [op.combine for op in operations] == [None, None]
