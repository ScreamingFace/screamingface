"""Combine evidence reaches the Report: decode, strictness, export, scoreboard (OME-1289).

STORY: as a researcher, I can read what each deterministic combine step extracted per member,
the tally, the agreement and the choice, on the same operation that carries the combined output.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from _nodes import fusion_node
from _reducer_fixtures import (
    FixtureVote,
    evidence_wire,
    fixture_operators,
    operators_response,
    reducer_fusion,
)
from test_client_run import _engine, _ReplayTransport
from test_leaderboards import _candidate_result

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._evaluation.results import _case_operation
from screamingface._scoreboard.leaderboards import _submission
from screamingface.case_result import CaseOperation
from screamingface.combine_evidence import (
    CombineAnswerRow,
    CombineEvidence,
    CombineFieldReading,
    CombineJudgeReading,
    CombineResult,
    CombineSignal,
    CombineTallyRow,
)
from screamingface.errors import ExecutionError

_LABEL = "Case Operation combine"


def _operation_wire(**combine: Any) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "operation_id": "op_synthesis_1",
        "output": "12",
        "finish_reason": "stop",
        "accounting": None,
    }
    if combine:
        wire["combine"] = combine["evidence"]
    return wire


def test_case_operation_without_combine_keeps_its_exact_dict() -> None:
    operation = CaseOperation("op_model_1", "x", "stop")

    assert operation.to_dict() == {
        "operation_id": "op_model_1",
        "output": "x",
        "finish_reason": "stop",
        "accounting": None,
    }
    assert operation.combine is None
    assert _case_operation(_operation_wire()).combine is None


def _judge_variant() -> dict[str, Any]:
    return evidence_wire(
        kind="selection",
        reducer="judge",
        operators=["label@1", "first_holder@1"],
        tally=None,
        judge={"raw": "Answer: 2", "returns": "label", "parsed": "member_2"},
        presentation_order="author",
        chosen=["member_2"],
        agreement=None,
        result={"member_id": "member_2", "value": "12", "status": "answered", "reason": None},
    )


def _fields_variant() -> dict[str, Any]:
    return evidence_wire(
        kind="projection",
        reducer="merge",
        tally=None,
        fields=[
            {
                "field": "answer",
                "rule": "majority",
                "values": {"member_1": {"x": [1, 2]}, "member_2": None},
                "result": {"x": [1, 2]},
            }
        ],
        agreement=None,
        separator_collision=False,
        median="9",
        tie=True,
        built=True,
        result={"member_id": None, "value": "12", "status": "answered", "reason": None},
    )


@pytest.mark.parametrize("variant", [evidence_wire, _judge_variant, _fields_variant])
def test_sdk_decodes_combine_evidence_into_case_operation(variant: Any) -> None:
    wire = variant()
    operation = _case_operation(_operation_wire(evidence=wire))

    assert isinstance(operation.combine, CombineEvidence)
    assert json.dumps(operation.to_dict()["combine"], sort_keys=True) == json.dumps(
        wire, sort_keys=True
    )
    assert json.dumps(operation.to_dict(), sort_keys=True) == json.dumps(
        _operation_wire(evidence=wire), sort_keys=True
    )


def test_decoded_readings_expose_typed_values() -> None:
    evidence = decode_combine_evidence(evidence_wire(), _LABEL)

    assert evidence is not None
    assert evidence.agreement == 1.0
    assert evidence.chosen == ("member_1",)
    assert evidence.tally is not None
    assert evidence.tally[0].holders == ("member_1", "member_2", "member_3")
    assert [reading.status for reading in evidence.members] == ["answered"] * 3
    judge = decode_combine_evidence(_judge_variant(), _LABEL)
    assert judge is not None
    assert isinstance(judge.judge, CombineJudgeReading)
    assert judge.judge.parsed == "member_2"
    fields = decode_combine_evidence(_fields_variant(), _LABEL)
    assert fields is not None
    assert isinstance(fields.fields, tuple)
    assert isinstance(fields.fields[0], CombineFieldReading)
    assert fields.fields[0].values["member_1"] == {"x": (1, 2)}
    assert decode_combine_evidence(None, _LABEL) is None


def _case_body(operations: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "schema": "screamingface.candidate-result.v1",
            "benchmark_id": "draco",
            "benchmark_revision": "fixture-revision",
            "case_count": 1,
            "score": 1.0,
            "coverage": 1.0,
            "metrics": {},
            "cases": [
                {
                    "status": "scored",
                    "case_id": 1,
                    "input": "Fixture question",
                    "output": "12",
                    "finish_reason": "stop",
                    "refusal": None,
                    "stop_reason": None,
                    "rounds_executed": None,
                    "grade": {"method": "fixture", "score": 1.0, "metrics": {}, "checks": []},
                    "failures": [],
                    "metadata": {},
                    "operations": operations,
                }
            ],
            "failures": [],
        }
    )


class _OperationsTransport(_ReplayTransport):
    def __init__(self, operations: list[dict[str, Any]]) -> None:
        super().__init__()
        self._operations = operations

    def run(self, candidate: Any, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)
        now = datetime.now(UTC)
        return _RunOutcome(
            run_id=outcome.run_id,
            started_at=now,
            completed_at=now,
            result_body=_case_body(self._operations),
            media_type="application/json",
            root_usage=None,
        )


def _operation(operation_id: str, output: str, **extra: Any) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "output": output,
        "finish_reason": "stop",
        "accounting": None,
        **extra,
    }


def _evaluate(recipe: sf.Recipe, operations: list[dict[str, Any]]) -> sf.Report:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/operators":
            return operators_response()
        return _engine(request)

    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
        run_transport=_OperationsTransport(operations),
    )
    with client:
        return client.evaluate(recipe, benchmark="draco", progress=False)


def test_the_report_carries_combine_evidence_beside_the_combined_output() -> None:
    operations = [
        _operation("op_model_1", "12"),
        _operation("op_model_2", "12"),
        _operation("op_model_3", "13"),
        _operation("op_synthesis_1", "12", combine=evidence_wire()),
    ]

    report = _evaluate(reducer_fusion(), operations)

    case = report.candidates[0].cases.by_id(1)
    assert case.operations is not None
    combine = case.operations[-1].combine
    assert combine is not None
    assert combine.chosen == ("member_1",)
    assert case.operations[0].combine is None
    # a combine step makes no model call: it must not read as a paid operation with unknown cost
    rows = report.candidates[0].accounting.rows
    assert all(row.operation_id != "op_synthesis_1" for row in rows)
    assert {row.operation_id for row in rows} == {"op_model_1", "op_model_2", "op_model_3"}


def test_two_reducers_keep_separate_evidence() -> None:
    pipeline = sf.Pipeline(
        [reducer_fusion(), fusion_node(["provider/d", "provider/e"], FixtureVote())]
    )
    compiled = compile_candidate(pipeline, operators=fixture_operators())
    sources = [op.id for op in compiled.operations if op.kind == "combine"]
    assert sources == ["op_synthesis_1", "op_synthesis_2"]

    operations = [
        _operation("op_synthesis_1", "12", combine=evidence_wire(3, chosen=["member_1"])),
        _operation(
            "op_synthesis_2",
            "14",
            combine=evidence_wire(
                2,
                chosen=["member_2"],
                agreement=0.5,
                result={
                    "member_id": "member_2",
                    "value": "12",
                    "status": "answered",
                    "reason": None,
                },
            ),
        ),
    ]
    report = _evaluate(pipeline, operations)

    case = report.candidates[0].cases.by_id(1)
    assert case.operations is not None
    first, second = case.operations
    assert first.combine is not None and second.combine is not None
    assert (first.operation_id, first.combine.chosen, len(first.combine.members)) == (
        "op_synthesis_1",
        ("member_1",),
        3,
    )
    assert (second.operation_id, second.combine.chosen, len(second.combine.members)) == (
        "op_synthesis_2",
        ("member_2",),
        2,
    )
    assert (first.combine.reducer, second.combine.reducer) == ("vote", "vote")
    assert (first.combine.agreement, second.combine.agreement) == (1.0, 0.5)


def _mutated(mutation: Any) -> dict[str, Any]:
    wire = evidence_wire()
    mutation(wire)
    return wire


def _bad_evidence() -> dict[str, tuple[Any, str]]:
    def drop(key: str) -> Any:
        return lambda wire: wire.pop(key)

    def put(key: str, value: Any) -> Any:
        return lambda wire: wire.__setitem__(key, value)

    def member(key: str, value: Any) -> Any:
        return lambda wire: wire["members"][0].__setitem__(key, value)

    return {
        "unknown top key": (put("extra", 1), "unsupported field 'extra'"),
        "missing key": (drop("tie"), "missing 'tie'"),
        "schema v2": (
            put("schema", "screamingface.combine-evidence.v2"),
            "schema must be 'screamingface.combine-evidence.v1'",
        ),
        "unknown reading key": (member("extra", 1), "members\\[0\\] contains unsupported field"),
        "missing reading key": (lambda wire: wire["members"][0].pop("score"), "missing 'score'"),
        "bad status": (member("status", "maybe"), "status must be one of"),
        "chosen not a member": (put("chosen", ["member_9"]), "'member_9', which is not a member"),
        "unknown tally holder": (
            lambda wire: wire["tally"][0].__setitem__("holders", ["member_7"]),
            "'member_7', which is not a member",
        ),
        "tally with an extra key": (
            lambda wire: wire["tally"][0].__setitem__("extra", 1),
            "tally\\[0\\] contains unsupported field",
        ),
        "agreement above one": (put("agreement", 1.5), "between 0 and 1"),
        "built as text": (put("built", "false"), "built must be a bool"),
        "judge with an extra key": (
            put("judge", {"raw": "x", "returns": "label", "parsed": "member_1", "extra": 1}),
            "judge contains unsupported field",
        ),
        "judge label that is not text": (
            put("judge", {"raw": "x", "returns": "label", "parsed": 3}),
            "member label",
        ),
        "field reading without result": (
            put("fields", [{"field": "a", "rule": "r", "values": {}}]),
            "missing 'result'",
        ),
        "unpinned operator": (put("operators", ["mode"]), "pinned ids"),
        "no members": (put("members", []), "non-empty"),
        "duplicate members": (
            lambda wire: wire.__setitem__("members", [wire["members"][0], wire["members"][0]]),
            "unique",
        ),
        "members not a list": (put("members", {}), "members must be a list"),
        "tally not a list": (put("tally", {}), "tally must be a list"),
        "evidence not an object": (lambda wire: None, "must be an object"),
    }


@pytest.mark.parametrize("case", sorted(_bad_evidence()))
def test_sdk_rejects_unknown_keys_and_schema(case: str) -> None:
    mutation, message = _bad_evidence()[case]
    wire: Any = evidence_wire()
    mutation(wire)
    if case == "evidence not an object":
        wire = ["not", "an", "object"]

    with pytest.raises(ExecutionError, match=message):
        decode_combine_evidence(wire, _LABEL)
    with pytest.raises(ExecutionError):
        _case_operation(_operation_wire(evidence=wire))


def test_evidence_for_64_members_has_no_text_and_fits_64kib() -> None:
    # Each member answered with a long text that ends in its number; the evidence may hold
    # the extracted number but never the text around it.
    outputs = {
        f"member_{i}": f"I worked through the problem step by step. Final answer: {i}"
        for i in range(1, 65)
    }
    wire = evidence_wire(
        64,
        tally=[
            {"value": str(index), "score": 1.0, "holders": [f"member_{index}"]}
            for index in range(1, 65)
        ],
        agreement=1 / 64,
    )
    for reading in wire["members"]:
        index = reading["member_id"].removeprefix("member_")
        reading["raw"] = reading["value"] = index

    evidence = decode_combine_evidence(wire, _LABEL)

    assert evidence is not None
    assert len(evidence.members) == 64
    for reading in evidence.members:
        assert list(reading.to_dict()) == [
            "member_id",
            "raw",
            "value",
            "status",
            "reason",
            "signals",
            "weight",
            "score",
        ]
    exported = json.dumps(
        evidence.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert len(exported.encode("utf-8")) <= 65536
    for member, text in outputs.items():
        assert text not in exported
        reading = next(item for item in evidence.members if item.member_id == member)
        assert reading.raw != text
        assert reading.value != text
    assert all(row.value != text for row in evidence.tally or () for text in outputs.values())


def test_blank_text_in_a_reading_does_not_make_the_evidence_undecodable() -> None:
    # The Engine model carries these as plain strings: a judge may reply with nothing.
    judge = evidence_wire(
        reducer="judge",
        tally=None,
        judge={"raw": "", "returns": "label", "parsed": "member_1"},
        fields=[{"field": "", "rule": " ", "values": {}, "result": None}],
    )
    evidence = decode_combine_evidence(judge, _LABEL)
    assert evidence is not None
    assert evidence.judge is not None and evidence.judge.raw == ""
    assert evidence.fields is not None and (evidence.fields[0].field, evidence.fields[0].rule) == (
        "",
        " ",
    )
    row = CombineTallyRow(value="", score=1.0, holders=("member_1",))
    assert row.value == ""


def _fail_row(**change: Any) -> CombineAnswerRow:
    values: dict[str, Any] = {
        "member_id": "member_1",
        "raw": None,
        "value": None,
        "status": "fail",
        "reason": "empty",
        "signals": {},
    }
    return CombineAnswerRow(**{**values, **change})


def test_evidence_values_validate_their_own_construction() -> None:
    reading = _fail_row()
    row = CombineTallyRow(value="12", score=2, holders=("member_1",))
    assert (reading.weight, row.score) == (None, 2.0)
    with pytest.raises(TypeError, match="finite number"):
        CombineTallyRow(value="12", score=None, holders=("member_1",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be empty"):
        CombineTallyRow(value="12", score=1.0, holders=())
    with pytest.raises(TypeError, match="finite number"):
        _fail_row(weight=True)
    with pytest.raises(ValueError, match="finite"):
        _fail_row(score=float("inf"))
    with pytest.raises(TypeError, match="must be text"):
        _fail_row(raw=3)
    with pytest.raises(TypeError, match="finite|number"):
        _fail_row(weight="1")
    with pytest.raises(ValueError, match="must be one of"):
        CombineJudgeReading(raw="x", returns="rank", parsed="member_1")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="object"):
        CombineJudgeReading(raw="x", returns="scores", parsed="member_1")
    with pytest.raises(TypeError, match="must be text"):
        CombineFieldReading(field=3, rule="r", values={}, result=None)  # type: ignore[arg-type]
    answered = CombineAnswerRow(
        member_id="member_1", raw="1", value="1", status="answered", reason=None, signals={}
    )
    base: dict[str, Any] = {
        "kind": "answer",
        "reducer": "vote",
        "operators": ("mode@1",),
        "members": (answered,),
        "chosen": ("member_1",),
        "built": False,
        "tie": False,
        "finish_reason": "stop",
        "result": CombineResult("member_1", "1", "answered", None),
        "dropped": 0,
    }
    assert CombineEvidence(**base).to_dict()["tally"] is None
    for change, error in (
        ({"kind": "other"}, ValueError),
        ({"reducer": "other"}, ValueError),
        ({"operators": "mode@1"}, TypeError),
        ({"members": "x"}, TypeError),
        ({"members": ("x",)}, TypeError),
        ({"tally": ("x",)}, TypeError),
        ({"judge": "x"}, TypeError),
        ({"chosen": "member_1"}, TypeError),
        ({"chosen": ("member_1", "member_1")}, ValueError),
        ({"tie": 1}, TypeError),
        ({"separator_collision": "no"}, TypeError),
        ({"presentation_order": "random"}, ValueError),
        ({"median": 9}, TypeError),
        ({"finish_reason": " "}, ValueError),
        ({"finish_reason": None}, ValueError),
        ({"agreement": "1"}, TypeError),
        ({"result": "x"}, TypeError),
        ({"signal": "x"}, TypeError),
        ({"dropped": True}, TypeError),
        ({"dropped": -1}, ValueError),
        ({"dropped": 1}, ValueError),
    ):
        with pytest.raises(error):
            CombineEvidence(**{**base, **change})


def test_case_operation_rejects_a_foreign_combine_value() -> None:
    with pytest.raises(TypeError, match="CombineEvidence"):
        CaseOperation("op_synthesis_1", "x", "stop", combine={"x": 1})  # type: ignore[arg-type]


def _scoreboard_result(operations: tuple[CaseOperation, ...]) -> sf.CandidateResult:
    base = _candidate_result()
    cases = tuple(
        sf.CaseResult(
            case_id=case.case_id,
            input=case.input,
            output=case.output,
            finish_reason=case.finish_reason,
            grade=case.grade,
            failures=case.failures,
            metadata=case.metadata,
            operations=operations,
        )
        for case in base.cases
    )
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id=base.run_id,
        started_at=base.started_at,
        completed_at=base.completed_at,
        name=base.name,
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=base.operations,
        score=base.score,
        coverage=base.coverage,
        metrics=dict(base.metrics),
        cases=cases,
        members=base.members,
        failures=base.failures,
        usage=sf.Usage(),
    )


def test_scoreboard_submission_ignores_combine_evidence() -> None:
    evidence = decode_combine_evidence(copy.deepcopy(evidence_wire()), _LABEL)
    with_evidence = _scoreboard_result((CaseOperation("op-a", "12", "stop", combine=evidence),))
    without = _scoreboard_result((CaseOperation("op-a", "12", "stop"),))

    assert _submission(with_evidence) == _submission(without)


_CASES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "data" / "combine_evidence_cases.json").read_text(encoding="utf-8")
)


def _decode_case(name: str) -> Any:
    evidence = decode_combine_evidence(copy.deepcopy(_CASES[name]), _LABEL)
    assert evidence is not None
    return evidence


def test_decoded_fixture_values_are_typed() -> None:
    one_failed = _decode_case("vote_one_failed")
    assert one_failed.members[1] == CombineAnswerRow(
        member_id="member_2",
        raw=None,
        value=None,
        status="fail",
        reason="empty",
        signals={},
    )
    assert one_failed.dropped == 1
    assert one_failed.result == CombineResult("member_1", "42", "answered", None)

    abstain = _decode_case("vote_abstain")
    assert abstain.result.status == "abstain"
    assert abstain.result.reason == "no_votes"
    assert abstain.chosen == ()

    field_signal = _decode_case("vote_field_signal")
    assert field_signal.signal == CombineSignal("field:confidence", None)
    assert [row.signals["field:confidence"] for row in field_signal.members] == [0.9, 0.3, 0.4]

    median_value = _decode_case("median_value")
    assert median_value.built is True
    assert median_value.result.member_id is None


def _mutated_case(name: str, mutation: Any) -> dict[str, Any]:
    wire = copy.deepcopy(_CASES[name])
    mutation(wire)
    return wire


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda w: w["members"][0].__setitem__("status", "voted"), "members\\[0\\] status"),
        (lambda w: w["members"][1].__setitem__("reason", "bogus"), "members\\[1\\] reason"),
        (lambda w: w["result"].__setitem__("status", "fail"), "result status"),
        (lambda w: w.__setitem__("dropped", 2), "is invalid"),
        (lambda w: w["result"].__setitem__("reason", "bogus"), "result reason"),
        (
            lambda w: w["signal"] or w.__setitem__("signal", {"key": "x", "order": None}),
            "signal key must be",
        ),
        (lambda w: w["members"][0].__setitem__("signals", {"cost_usd": "1"}), "signals"),
        (lambda w: w["members"][0].__setitem__("signals", []), "signals"),
        (lambda w: w.pop("result"), "missing 'result'"),
        (lambda w: w["result"].__setitem__("extra", 1), "result contains unsupported field"),
        (lambda w: w.__setitem__("dropped", True), "dropped must be an integer"),
    ],
)
def test_decoder_names_the_field_of_an_unknown_status_or_reason(
    mutation: Any, message: str
) -> None:
    with pytest.raises(ExecutionError, match=message):
        decode_combine_evidence(_mutated_case("vote_one_failed", mutation), _LABEL)


def test_decoder_refuses_inconsistent_results() -> None:
    abstain_with_chosen = _mutated_case(
        "vote_abstain", lambda w: w.__setitem__("chosen", ["member_1"])
    )
    built_member = _mutated_case(
        "median_value", lambda w: w["result"].__setitem__("member_id", "member_1")
    )
    wrong_chosen = _mutated_case("vote_one_failed", lambda w: w.__setitem__("chosen", ["member_3"]))
    for wire in (abstain_with_chosen, built_member, wrong_chosen):
        with pytest.raises(ExecutionError, match="is invalid"):
            decode_combine_evidence(wire, _LABEL)


@pytest.mark.parametrize("reason", ["no_votes", "cut_not_met"])
def test_decoder_refuses_a_failed_member_with_an_abstain_reason(reason: str) -> None:
    def put(wire: dict[str, Any]) -> None:
        wire["members"][1]["reason"] = reason

    with pytest.raises(ExecutionError, match="is invalid: .*failed member.*reason"):
        decode_combine_evidence(_mutated_case("vote_one_failed", put), _LABEL)


def test_answer_row_invariants() -> None:
    def row(**change: Any) -> CombineAnswerRow:
        values: dict[str, Any] = {
            "member_id": "member_1",
            "raw": "1",
            "value": "1",
            "status": "answered",
            "reason": None,
            "signals": {},
        }
        return CombineAnswerRow(**{**values, **change})

    assert row(signals={"cost_usd": 1}).signals == {"cost_usd": 1.0}
    for change, error in (
        ({"reason": "empty"}, ValueError),
        ({"status": "fail"}, ValueError),
        ({"status": "fail", "reason": "empty"}, ValueError),
        ({"status": "abstain"}, ValueError),
        ({"reason": 3, "status": "fail", "value": None}, ValueError),
        ({"signals": {1: 1.0}}, TypeError),
        ({"signals": {"a": float("nan")}}, ValueError),
        ({"member_id": "m1"}, ValueError),
    ):
        with pytest.raises(error):
            row(**change)
    with pytest.raises(ValueError, match="abstain"):
        CombineResult("member_1", None, "abstain", "no_votes")
    with pytest.raises(ValueError, match="reason"):
        CombineResult(None, None, "abstain", None)
    with pytest.raises(ValueError, match="reason"):
        CombineResult("member_1", "1", "answered", "no_votes")
    with pytest.raises(ValueError, match="order"):
        CombineSignal("cost_usd", "up")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="signal key"):
        CombineSignal("cost", None)
