"""The Report shows the raw judge reply, the parsed choice and the judge's cost (OME-1289).

STORY: as a researcher, I can read the judge's own words and the member the Fusion copied from
the Case operations, and the judge call is accounted as a synthesis row.
"""

from __future__ import annotations

from typing import Any

import httpx
from _combine_flow_fixtures import flow_operators_response, judge_fusion
from _reducer_fixtures import evidence_wire
from test_client_run import _engine
from test_combine_evidence import _operation, _OperationsTransport
from test_operation_accounting_decode import _accounting_wire

import screamingface as sf


def _evaluate(recipe: sf.Recipe, operations: list[dict[str, Any]]) -> sf.Report:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/operators":
            return flow_operators_response()
        return _engine(request)

    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
        run_transport=_OperationsTransport(operations),
    )
    with client:
        return client.evaluate(recipe, benchmark="draco", progress=False)


def _judge_evidence() -> dict[str, Any]:
    members = [
        {"member": f"member_{index}", "raw": None, "value": None, "status": "voted"}
        | {"weight": None, "score": None}
        for index in (1, 2, 3)
    ]
    return evidence_wire(
        reducer="judge",
        operators=["label@1", "by_label@1"],
        members=members,
        tally=None,
        judge={"raw": "member_2", "returns": "label", "parsed": "member_2"},
        chosen=["member_2"],
        agreement=None,
        presentation_order="author",
    )


def _operations(**judge: Any) -> list[dict[str, Any]]:
    return [
        _operation("op_model_1", "answer one"),
        _operation("op_model_2", "answer two"),
        _operation("op_model_3", "answer three"),
        _operation("op_judge_1", "member_2", **judge),
        _operation("op_synthesis_1", "answer two", combine=_judge_evidence()),
    ]


def test_report_shows_raw_judge_output_and_parsed_label() -> None:
    report = _evaluate(judge_fusion(), _operations())

    case = report.candidates[0].cases.by_id(1)
    assert case.operations is not None
    assert [operation.operation_id for operation in case.operations] == [
        "op_model_1",
        "op_model_2",
        "op_model_3",
        "op_judge_1",
        "op_synthesis_1",
    ]
    assert case.operations[3].output == "member_2"
    combine = case.operations[4].combine
    assert combine is not None
    assert combine.judge is not None
    assert combine.judge.raw == "member_2"
    assert combine.judge.parsed == "member_2"
    assert combine.presentation_order == "author"
    assert combine.chosen == ("member_2",)
    operation_kinds = {
        operation.id: operation.kind for operation in report.candidates[0].operations
    }
    assert operation_kinds["op_judge_1"] == "judge"
    assert operation_kinds["op_synthesis_1"] == "combine"


def test_judge_operation_accounting_is_a_synthesis_row() -> None:
    report = _evaluate(judge_fusion(), _operations(accounting=_accounting_wire()))

    rows = report.candidates[0].accounting.rows
    judge_rows = [row for row in rows if row.operation_id == "op_judge_1"]
    assert len(judge_rows) == 1
    assert judge_rows[0].stage == "synthesis"
    assert judge_rows[0].label == "a+b+c judge"
    assert judge_rows[0].member_id is None
    assert judge_rows[0].accounting is not None
    assert judge_rows[0].accounting.provider == "openrouter"
    assert all(row.operation_id != "op_synthesis_1" for row in rows)
    assert {row.operation_id: row.stage for row in rows if row.operation_id != "op_judge_1"} == {
        "op_model_1": "generation",
        "op_model_2": "generation",
        "op_model_3": "generation",
    }
