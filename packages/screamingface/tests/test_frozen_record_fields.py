"""The SDK answer, report-trace and budget records are frozen per schema id (OME-1289 gap, unit 12).

FEATURE: ``data/schemas/<schema id>.json`` pins the field set of ``Answer`` (``answer.v1``), the
report trace (``report-trace.v1``) and the Budget records (``budget.v1``).
STORY: as a maintainer, I change a released record and this test fails unless I also bump the schema
id, so a pinned field set never moves under the same id (RT#3, BU#9, BU-D4).
INVARIANT defended: the pinned file is never overwritten by a run. Regeneration of a MISSING file is
an explicit act (``UPDATE_SCHEMA_SNAPSHOT=1``); it writes only missing files and still fails that
run, as the public surface test does. ``report.v1`` is NOT here: main tests pin it.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, get_args, get_type_hints

import pytest
from _answer_fixtures import bound, fixture_graph
from _combine_contract import COMBINE_CONTRACT, requires_engine_app
from _schema_freeze import check_frozen
from test_report_trace import _candidate

import screamingface as sf
from screamingface import budget
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.answer import (
    ABSTAIN_REASONS,
    ANSWER_REASONS,
    ANSWER_SCHEMA,
    ANSWER_STATUSES,
    MEMBER_STATUSES,
    SIGNAL_ORDERS,
    Answer,
)
from screamingface.case_result import CaseOperation
from screamingface.report_trace import TRACE_FIELDS, TRACE_SCHEMA

SCHEMAS = Path(__file__).parent / "data" / "schemas"
UPDATE = os.environ.get("UPDATE_SCHEMA_SNAPSHOT", "").strip().lower() in {"1", "true"}
_SCHEMA = {"fields": ["a", "b"], "kinds": {"x": ["a"]}}


def _rendered(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


# --- the freeze check itself ------------------------------------------------------------------


def test_the_same_id_and_the_same_field_set_passes(tmp_path: Path) -> None:
    (tmp_path / "x.v1.json").write_text(_rendered(_SCHEMA), encoding="utf-8")

    check_frozen(tmp_path, "x.v1", _SCHEMA, update=False)


def test_the_same_id_and_another_field_set_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.v1.json").write_text(_rendered(_SCHEMA), encoding="utf-8")

    with pytest.raises(AssertionError, match="without a schema id change"):
        check_frozen(tmp_path, "x.v1", {**_SCHEMA, "fields": ["a"]}, update=False)


def test_a_missing_file_names_the_update_variable(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="UPDATE_SCHEMA_SNAPSHOT"):
        check_frozen(tmp_path, "x.v1", _SCHEMA, update=False)

    assert not (tmp_path / "x.v1.json").exists()


def test_update_mode_writes_a_missing_file_and_still_fails(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="written"):
        check_frozen(tmp_path, "x.v1", _SCHEMA, update=True)

    assert (tmp_path / "x.v1.json").read_text(encoding="utf-8") == _rendered(_SCHEMA)


def test_update_mode_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    pinned = tmp_path / "x.v1.json"
    pinned.write_text(_rendered(_SCHEMA), encoding="utf-8")
    before = pinned.read_bytes()

    with pytest.raises(AssertionError, match="without a schema id change"):
        check_frozen(tmp_path, "x.v1", {**_SCHEMA, "fields": ["z"]}, update=True)

    assert pinned.read_bytes() == before


# --- RT#3 and BU#9: the field sets ------------------------------------------------------------


def _names(record: type) -> list[str]:
    return [item.name for item in dataclasses.fields(record)]


def _answer_fields() -> dict[str, Any]:
    return {
        "fields": _names(Answer),
        "status": sorted(ANSWER_STATUSES),
        "member_status": sorted(MEMBER_STATUSES),
        "reason": sorted(ANSWER_REASONS),
        "abstain_reason": sorted(ABSTAIN_REASONS),
        "signal_order": sorted(SIGNAL_ORDERS),
    }


def _trace_fields() -> dict[str, Any]:
    first = _candidate("opus", "run_1")
    document = sf.Report(benchmark=first.benchmark, case_count=2, candidates=(first,)).trace_dict()
    candidate: Any = document["candidates"]
    return {
        "document": list(document),
        "candidate": list(candidate[0]),
        "case": list(candidate[0]["cases"][0]),
        "kinds": {kind: list(fields) for kind, fields in TRACE_FIELDS.items()},
    }


def _budget_fields() -> dict[str, Any]:
    records = (budget.Budget, budget.BudgetCharge, budget.BudgetRefusal, budget.BudgetState)
    return {
        **{record.__name__: _names(record) for record in records},
        "unit": list(get_args(budget.BudgetUnit.__value__)),
        "source": list(get_args(budget.ChargeSource.__value__)),
        "stage": list(get_args(budget.BudgetStage.__value__)),
        "refusal_reason": list(get_args(get_type_hints(budget.BudgetRefusal)["reason"])),
    }


def test_the_schema_ids_are_the_pinned_ones() -> None:
    assert ANSWER_SCHEMA == "screamingface.answer.v1"
    assert TRACE_SCHEMA == "screamingface.report-trace.v1"
    assert budget.BUDGET_SCHEMA == "screamingface.budget.v1"


@pytest.mark.parametrize(
    ("schema_id", "field_set"),
    [
        pytest.param(ANSWER_SCHEMA, _answer_fields, id="answer"),
        pytest.param(TRACE_SCHEMA, _trace_fields, id="report-trace"),
        pytest.param(budget.BUDGET_SCHEMA, _budget_fields, id="budget"),
    ],
)
def test_sdk_records_match_frozen_field_sets(schema_id: str, field_set: Any) -> None:
    check_frozen(SCHEMAS, schema_id, field_set(), update=UPDATE)


# --- the 25 Engine fixtures use the frozen fields ---------------------------------------------


def _engine_cases() -> dict[str, Any]:
    path = COMBINE_CONTRACT / "evidence_cases.json"
    assert path.is_file(), f"missing Engine contract fixture {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_case(name: str, wire: Any) -> tuple[sf.CaseResult, int]:
    evidence = decode_combine_evidence(wire, f"Engine evidence {name}")
    assert evidence is not None
    count = len(evidence.members)
    operations = [
        CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in range(1, count + 1)
    ]
    operations.append(CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence))
    case = sf.CaseResult(
        case_id=1,
        input="Question",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
    )
    return bound(case, fixture_graph(count)), count


@requires_engine_app
def test_fixture_answers_and_traces_use_the_frozen_fields() -> None:
    wires = _engine_cases()

    assert len(wires) == 32
    for name, wire in wires.items():
        case, count = _fixture_case(name, wire)
        answers = case.answers()
        assert len(answers) == count + 1, name
        assert all(list(a.to_dict()) == _names(Answer) for a in answers), name
        trace = [entry.to_dict() for entry in case.trace()]
        assert trace, name
        assert all(list(e) == ["kind", *TRACE_FIELDS[str(e["kind"])]] for e in trace), name


# --- BU-D4 ------------------------------------------------------------------------------------


def test_budget_trace_kind_carries_every_budget_record_field() -> None:
    carried = {"event"} | set(_names(budget.BudgetCharge)) | set(_names(budget.BudgetRefusal))

    assert carried - {"reason"} == set(TRACE_FIELDS["budget"])
