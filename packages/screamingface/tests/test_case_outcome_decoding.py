"""The client decodes the explicit Case outcome the OME-802 Engine publishes.

INVARIANT defended: the `screamingface.candidate-result.v1` Case Result carries
`status` (scored | refused | failed) and `refusal` on every Case — the client
decodes them strictly (unknown keys and unknown statuses still fail loudly) and
exposes them unmodified, never recalculating Benchmark semantics client-side.
"""

from __future__ import annotations

from typing import Any

import pytest

import screamingface as sf
from screamingface._evaluation.results import _case_result


def _scored_payload() -> dict[str, Any]:
    return {
        "status": "scored",
        "case_id": 1,
        "input": "What is two plus two?",
        "output": "Four.",
        "finish_reason": "stop",
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": {"method": "rubric", "score": 1.0, "metrics": {}, "checks": []},
        "failures": [],
        "metadata": {},
    }


def _refused_payload() -> dict[str, Any]:
    return {
        "status": "refused",
        "case_id": 1,
        "input": "A clinical question",
        "output": None,
        "finish_reason": "stop",
        "refusal": "I can't help with that request.",
        "stop_reason": None,
        "rounds_executed": None,
        "grade": {"method": "rubric", "score": 0.0, "metrics": {}, "checks": []},
        "failures": [],
        "metadata": {},
    }


def _failed_payload() -> dict[str, Any]:
    return {
        "status": "failed",
        "case_id": 1,
        "input": "A question",
        "output": None,
        "finish_reason": None,
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": None,
        "grade": None,
        "failures": [
            {
                "stage": "candidate",
                "code": "provider_error",
                "message": "the provider failed",
                "retryable": True,
                "case_id": 1,
                "metadata": {},
            }
        ],
        "metadata": {},
    }


def _ifeval_payload() -> dict[str, Any]:
    payload = _scored_payload()
    payload["input"] = "Write exactly three words."
    payload["output"] = "One two three"
    payload["grade"] = {
        "method": "deterministic",
        "score": 1.0,
        "metrics": {"instructions_followed": 1},
        "checks": [],
    }
    payload["metadata"] = {"benchmark": "ifeval"}
    return payload


def _healthbench_payload() -> dict[str, Any]:
    payload = _scored_payload()
    payload["input"] = (
        '{"schema":"screamingface.candidate-input.v1","messages":'
        '[{"role":"user","content":"I have chest pain."}]}'
    )
    payload["output"] = "Seek urgent medical assessment."
    payload["grade"] = {
        "method": "rubric",
        "score": -0.25,
        "metrics": {"rubrics_judged": 2},
        "checks": [],
    }
    payload["metadata"] = {"benchmark": "healthbench-worst30"}
    return payload


@pytest.mark.parametrize(
    ("payload", "status", "refusal"),
    [
        (_scored_payload(), "scored", None),
        (_refused_payload(), "refused", "I can't help with that request."),
        (_failed_payload(), "failed", None),
    ],
)
def test_every_wire_status_decodes_and_is_exposed_unmodified(
    payload: dict[str, Any], status: str, refusal: str | None
) -> None:
    case = _case_result(payload)

    assert case.status == status
    assert case.refusal == refusal


def test_decoded_outcome_survives_export() -> None:
    exported = _case_result(_refused_payload()).to_dict()

    assert exported["status"] == "refused"
    assert exported["refusal"] == "I can't help with that request."


def test_corrective_execution_telemetry_decodes_and_survives_export() -> None:
    payload = _scored_payload()
    payload.update(stop_reason="passed", rounds_executed=2)

    case = _case_result(payload)

    assert case.stop_reason == "passed"
    assert case.rounds_executed == 2
    assert case.to_dict() == payload


@pytest.mark.parametrize(
    ("stop_reason", "rounds_executed"),
    [("unknown", 1), ("passed", None), (None, 1), ("max_rounds", 0)],
)
def test_malformed_corrective_execution_telemetry_fails_closed(
    stop_reason: object, rounds_executed: object
) -> None:
    payload = _scored_payload()
    payload.update(stop_reason=stop_reason, rounds_executed=rounds_executed)

    with pytest.raises(sf.ExecutionError, match="stop_reason|rounds_executed"):
        _case_result(payload)


def test_wire_text_and_string_identity_survive_without_normalization() -> None:
    payload = _refused_payload()
    payload.update(
        {
            "case_id": " case-1 ",
            "input": " prompt with intentional padding ",
            "finish_reason": " content_filter ",
            "refusal": " exact provider refusal ",
        }
    )
    assert _case_result(payload).to_dict() == payload


def test_failure_code_uses_the_engine_open_nonempty_contract() -> None:
    payload = _failed_payload()
    payload["failures"][0]["code"] = "Provider Error"

    assert _case_result(payload).failures[0].code == "Provider Error"


def test_nested_grade_and_evidence_round_trip_the_exact_engine_contract() -> None:
    payload = _scored_payload()
    payload["grade"] = {
        "method": " deterministic ",
        "score": 1.0,
        "metrics": {},
        "checks": [
            {
                "type": " instruction ",
                "id": " check-1 ",
                "label": "",
                "outcome": "MET",
                "score": 1.0,
                "evidence": [
                    {
                        "sequence": 1,
                        "producer": {"type": "sandboxed-python", "id": " checker/custom "},
                        "valid": True,
                        "outcome": "PASS",
                        "explanation": " exact explanation ",
                        "raw_output": {"passed": True},
                        "metadata": {},
                        "accounting": None,
                    }
                ],
                "metadata": {},
            }
        ],
    }

    assert _case_result(payload).to_dict() == payload


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("grade", "score"), 1.1, "Case Grade score must be at most 1"),
        (("grade", "checks", 0, "score"), -0.1, "Check score must be between 0 and 1"),
        (("grade", "checks", 0, "outcome"), "PASS", "Check outcome"),
        (("grade", "checks", 0, "evidence", 0, "outcome"), "MAYBE", "Evidence outcome"),
    ],
)
def test_nested_grade_contract_rejects_values_the_engine_cannot_publish(
    path: tuple[str | int, ...], value: object, message: str
) -> None:
    payload = _scored_payload()
    payload["grade"] = {
        "method": "rubric",
        "score": 1.0,
        "metrics": {},
        "checks": [
            {
                "type": "criterion",
                "id": "check-1",
                "label": "label",
                "outcome": "MET",
                "score": 1.0,
                "evidence": [
                    {
                        "sequence": 1,
                        "producer": {"type": "model", "id": "judge"},
                        "valid": True,
                        "outcome": "PASS",
                        "raw_output": {},
                        "metadata": {},
                        "accounting": None,
                    }
                ],
                "metadata": {},
            }
        ],
    }
    selected: Any = payload
    for part in path[:-1]:
        selected = selected[part]
    selected[path[-1]] = value

    with pytest.raises(sf.ExecutionError, match=message):
        _case_result(payload)


@pytest.mark.parametrize(
    "payload",
    [_scored_payload(), _ifeval_payload(), _healthbench_payload()],
    ids=["draco", "ifeval", "healthbench"],
)
def test_each_benchmark_family_decodes_through_the_same_case_contract(
    payload: dict[str, Any],
) -> None:
    case = _case_result(payload)

    assert case.to_dict() == payload


@pytest.mark.parametrize("key", tuple(_scored_payload()))
def test_a_case_missing_a_contract_key_is_rejected(key: str) -> None:
    payload = {name: value for name, value in _scored_payload().items() if name != key}

    with pytest.raises(sf.ExecutionError, match=f"missing '{key}'"):
        _case_result(payload)


def test_an_unknown_case_key_is_still_rejected() -> None:
    with pytest.raises(sf.ExecutionError, match="unsupported field 'unexpected'"):
        _case_result({**_scored_payload(), "unexpected": True})


def test_an_unsupported_status_is_rejected() -> None:
    with pytest.raises(sf.ExecutionError, match="status is unsupported"):
        _case_result({**_scored_payload(), "status": "skipped"})


def test_blank_refusal_text_is_rejected() -> None:
    with pytest.raises(sf.ExecutionError, match="refusal"):
        _case_result({**_refused_payload(), "refusal": "   "})


def test_a_status_contradicting_the_grade_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="status"):
        sf.CaseResult(
            status="failed",
            case_id=1,
            input="question",
            output="answer",
            finish_reason="stop",
            grade=sf.CaseGrade(method="rubric", score=1.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        )


def test_a_scored_case_cannot_carry_refusal_text() -> None:
    with pytest.raises(ValueError, match="refusal"):
        sf.CaseResult(
            status="scored",
            case_id=1,
            input="question",
            output=None,
            finish_reason="stop",
            refusal="I refuse.",
            grade=sf.CaseGrade(method="rubric", score=1.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        )


def test_a_refused_case_cannot_carry_output() -> None:
    # INVARIANT: mirrors contract.py _enforce_status — a refused Case has no output,
    # so a locally built value can never round-trip into a contract-invalid payload.
    with pytest.raises(ValueError, match="refused"):
        sf.CaseResult(
            case_id=1,
            input="question",
            output="an answer the engine would reject",
            finish_reason="stop",
            refusal="I can't help with that request.",
            grade=sf.CaseGrade(method="rubric", score=0.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        )


def test_a_refused_case_requires_a_grade() -> None:
    with pytest.raises(ValueError, match="refused"):
        sf.CaseResult(
            case_id=1,
            input="question",
            output=None,
            finish_reason="stop",
            refusal="I can't help with that request.",
            grade=None,
            failures=(),
            metadata={},
        )


def test_a_locally_built_case_derives_status_without_weakening_wire_decoding() -> None:
    refused = sf.CaseResult(
        case_id=1,
        input="question",
        output=None,
        finish_reason=None,
        refusal="I can't help with that request.",
        grade=sf.CaseGrade(method="rubric", score=0.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )

    assert refused.status == "refused"


# FEATURE: OME-843 member-output capture — the optional `operations` case key carries
# each member/synthesis operation's output so Fusion contribution analysis works offline.
def _operations_payload() -> dict[str, Any]:
    payload = _scored_payload()
    payload["operations"] = [
        {
            "operation_id": "op_model_1",
            "output": "Member one answer.",
            "finish_reason": "stop",
            "accounting": None,
        },
        {
            "operation_id": "op_model_2",
            "output": None,
            "finish_reason": "length",
            "accounting": None,
        },
        {
            "operation_id": "op_synthesis_1",
            "output": "Four.",
            "finish_reason": "stop",
            "accounting": None,
        },
    ]
    return payload


def test_operations_decode_in_wire_order_and_survive_export() -> None:
    # INVARIANT: `operations` is optional, ordered, and round-trips exactly — the client
    # never reorders, drops, or invents member outputs.
    payload = _operations_payload()

    case = _case_result(payload)

    assert case.operations is not None
    assert [item.operation_id for item in case.operations] == [
        "op_model_1",
        "op_model_2",
        "op_synthesis_1",
    ]
    assert case.operations[0].output == "Member one answer."
    assert case.operations[1].output is None
    assert case.operations[1].finish_reason == "length"
    assert case.to_dict() == payload


def test_a_case_without_operations_exports_byte_identically() -> None:
    # INVARIANT: absence stays absence — a solo Candidate's artifact gains no member
    # section, so pre-OME-843 reports and new solo reports stay byte-identical.
    payload = _scored_payload()

    case = _case_result(payload)

    assert case.operations is None
    assert "operations" not in case.to_dict()


def test_a_null_operations_key_decodes_as_absent() -> None:
    case = _case_result({**_scored_payload(), "operations": None})

    assert case.operations is None
    assert "operations" not in case.to_dict()


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"output": "x", "finish_reason": None, "accounting": None}, "missing 'operation_id'"),
        (
            {
                "operation_id": "op_model_1",
                "output": "x",
                "finish_reason": None,
                "accounting": None,
                "extra": 1,
            },
            "unsupported field 'extra'",
        ),
        (
            {"operation_id": "  ", "output": "x", "finish_reason": None, "accounting": None},
            "operation_id",
        ),
        (
            {"operation_id": "op_model_1", "output": 7, "finish_reason": None, "accounting": None},
            "output",
        ),
    ],
)
def test_a_malformed_operation_entry_fails_closed(entry: dict[str, Any], message: str) -> None:
    # INVARIANT: tolerance is for the key's absence, not for malformed content — a
    # present `operations` list still decodes strictly, like every other contract field.
    with pytest.raises(sf.ExecutionError, match=message):
        _case_result({**_scored_payload(), "operations": [entry]})


def test_operations_must_be_a_list_when_present() -> None:
    with pytest.raises(sf.ExecutionError, match="operations"):
        _case_result({**_scored_payload(), "operations": {"op_model_1": "answer"}})
