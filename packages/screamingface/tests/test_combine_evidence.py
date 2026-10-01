"""Combine evidence reaches the Report: decode, strictness, export, scoreboard (OME-1289).

STORY: as a researcher, I can read what each deterministic combine step extracted per member,
the tally, the agreement and the choice, on the same operation that carries the combined output.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _reducer_fixtures import FixtureVote, evidence_wire, reducer_fusion
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
    CombineEvidence,
    CombineFieldReading,
    CombineJudgeReading,
    CombineMemberReading,
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
    )


def _scores_variant() -> dict[str, Any]:
    return evidence_wire(
        reducer="judge",
        tally=None,
        judge={
            "raw": "{}",
            "returns": "scores",
            "parsed": {"member_1": 0.2, "member_2": 0.8, "member_3": 0.5},
        },
        presentation_order="author",
        agreement=None,
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
    )


@pytest.mark.parametrize(
    "variant", [evidence_wire, _judge_variant, _scores_variant, _fields_variant]
)
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
    assert [reading.status for reading in evidence.members] == ["voted"] * 3
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
            from _reducer_fixtures import operators_response

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
        [reducer_fusion(), sf.Fusion(["provider/d", "provider/e"], synthesizer=FixtureVote())]
    )
    compiled = compile_candidate(pipeline, operators=_operators())
    sources = [op.id for op in compiled.operations if op.kind == "combine"]
    assert sources == ["op_synthesis_1", "op_synthesis_2"]

    operations = [
        _operation("op_synthesis_1", "12", combine=evidence_wire(3, chosen=["member_1"])),
        _operation(
            "op_synthesis_2",
            "14",
            combine=evidence_wire(2, chosen=["member_2"], reducer="median", agreement=0.5),
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
    assert (second.operation_id, second.combine.reducer, len(second.combine.members)) == (
        "op_synthesis_2",
        "median",
        2,
    )


def _operators() -> Any:
    from _reducer_fixtures import fixture_operators

    return fixture_operators()


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
    wire = evidence_wire(
        64,
        tally=[
            {"value": str(index), "score": 1.0, "holders": [f"member_{index}"]}
            for index in range(1, 65)
        ],
        agreement=1 / 64,
    )

    evidence = decode_combine_evidence(wire, _LABEL)

    assert evidence is not None
    assert len(evidence.members) == 64
    for reading in evidence.members:
        assert list(reading.to_dict()) == ["member", "raw", "value", "status", "weight", "score"]
    exported = json.dumps(
        evidence.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert len(exported.encode("utf-8")) <= 65536
    assert "text" not in json.loads(exported)


def test_evidence_values_validate_their_own_construction() -> None:
    reading = CombineMemberReading(member="member_1", raw=None, value=None, status="empty")
    row = CombineTallyRow(value="12", score=2, holders=("member_1",))
    assert (reading.weight, row.score) == (None, 2.0)
    with pytest.raises(TypeError, match="finite number"):
        CombineTallyRow(value="12", score=None, holders=("member_1",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be empty"):
        CombineTallyRow(value="12", score=1.0, holders=())
    with pytest.raises(TypeError, match="number or None"):
        CombineMemberReading(member="member_1", raw=None, value=None, status="empty", weight=True)
    with pytest.raises(ValueError, match="finite"):
        CombineMemberReading(
            member="member_1", raw=None, value=None, status="empty", score=float("inf")
        )
    with pytest.raises(TypeError, match="text or None"):
        CombineMemberReading(member="member_1", raw=3, value=None, status="empty")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="finite|number"):
        CombineMemberReading(member="member_1", raw=None, value=None, status="empty", weight="1")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be one of"):
        CombineJudgeReading(raw="x", returns="rank", parsed="member_1")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="object"):
        CombineJudgeReading(raw="x", returns="scores", parsed="member_1")
    with pytest.raises(ValueError, match="must not be blank"):
        CombineFieldReading(field=" ", rule="r", values={}, result=None)
    base: dict[str, Any] = {
        "kind": "answer",
        "reducer": "vote",
        "operators": ("mode@1",),
        "members": (reading,),
        "chosen": ("member_1",),
        "built": False,
        "tie": False,
        "finish_reason": "stop",
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
        ({"agreement": "1"}, TypeError),
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
