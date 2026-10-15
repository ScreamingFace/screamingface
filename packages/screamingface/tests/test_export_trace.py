"""The Case trace in the report.v1 export (E4b part 4, export-trace PRD, XT#1-13).

FEATURE: each exported Case that has combine evidence gets a last key ``trace``: its
``screamingface.report-trace.v1`` entries, built with the Candidate's own operation graph.
STORY: as a researcher who shares or archives ``report.json``, I read which operation was which
member, what each member gave and how the step decided, without the SDK and without the live report.
INVARIANT defended: ``case.to_dict()`` never changes (it mirrors the Engine wire, and the strict
decoder refuses an unknown key); every other Case and every other key keeps its bytes; the export
paths (``to_dict``, ``to_json``, ``export``, the download link) agree; the exported entries are the
``trace_dict()`` entries (one builder, ``_case_entries``, P20).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from _answer_fixtures import evidence_cases, fixture_case, fixture_graph
from test_case_attempts import _attempt
from test_case_attempts import _case as _attempts_case
from test_report import candidate
from test_report_v1_identity import COMBINE_GOLDEN, combine_report
from test_report_v1_vote_identity import GOLDEN as VOTE_MEDIAN_GOLDEN
from test_report_v1_vote_identity import vote_median_report

import screamingface as sf
from screamingface._report_export import inline_json
from screamingface.case_result import CaseOperation
from screamingface.operation import OperationInfo
from screamingface.report_trace import TRACE_FIELDS

_CASE_KEYS = [
    "status",
    "case_id",
    "input",
    "output",
    "finish_reason",
    "refusal",
    "stop_reason",
    "rounds_executed",
    "grade",
    "failures",
    "metadata",
    "operations",
]
_NO_RESULT = {"member_id": None, "value": None, "status": "abstain", "reason": "no_votes"}


# --- builders ----------------------------------------------------------------------------------


def _candidate(
    cases: Sequence[sf.CaseResult], operations: Sequence[OperationInfo] | None = None
) -> sf.CandidateResult:
    """``test_report_trace._candidate`` with ``cases`` and ``operations`` parameters."""

    base = candidate("opus")
    graded = sum(case.grade is not None and case.grade.score is not None for case in cases)
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id="run_1",
        started_at=base.started_at,
        completed_at=base.completed_at,
        name="opus",
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=fixture_graph(4) if operations is None else tuple(operations),
        score=1.0,
        coverage=round(graded / len(cases), 4),
        metrics={},
        cases=tuple(cases),
        members=(),
        failures=(),
        usage=base.usage,
    )


def _report(*cases: sf.CaseResult, operations: Sequence[OperationInfo] | None = None) -> sf.Report:
    result = _candidate(cases, operations)
    return sf.Report(benchmark=result.benchmark, case_count=len(cases), candidates=(result,))


def _exported(report: sf.Report) -> list[dict[str, Any]]:
    """Every exported Case object of ``report.to_dict()``, Candidate by Candidate."""

    value: Any = report.to_dict()
    return [case for result in value["candidates"] for case in result["cases"]]


def _plain_case(case_id: int) -> sf.CaseResult:
    """A scored Case with no operations (a solo model Candidate)."""

    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output=f"Answer {case_id}",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )


def _no_evidence_case(case_id: int) -> sf.CaseResult:
    """A Case whose operations hold no combine evidence (a pre-E4a Engine)."""

    operations = [CaseOperation(f"op_model_{k}", f"text {k}", "stop") for k in (1, 2, 3)]
    operations.append(CaseOperation("op_synthesis_1", "42", "stop"))
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output="42",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
    )


def _failed_case(case_id: int) -> sf.CaseResult:
    """A failed Case, as ``test_report_trace.test_failed_case_trace_is_empty`` builds it."""

    return sf.CaseResult(
        case_id=case_id,
        input="q",
        output=None,
        finish_reason=None,
        grade=None,
        failures=(
            sf.Failure(
                stage="candidate", code="candidate_failed", message="failed", case_id=case_id
            ),
        ),
        metadata={},
    )


def _abstained_case(case_id: int) -> sf.CaseResult:
    """The abstained Case: empty output, score 0.0, and the ``vote_abstain`` evidence."""

    operations = [CaseOperation(f"op_model_{k}", "", "stop") for k in (1, 2, 3)]
    operations.append(
        CaseOperation("op_synthesis_1", "", "stop", combine=evidence_cases()["vote_abstain"])
    )
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output="",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=0.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
        abstained=True,
    )


def _attempts_with_evidence() -> sf.CaseResult:
    """A Case with two Attempts; each Attempt's operations hold combine evidence (P15)."""

    evidence = evidence_cases()["vote_one_failed"]
    operations = (
        *(CaseOperation(f"op_model_{k}", f"text {k}", "stop") for k in (1, 2, 3)),
        CaseOperation("op_synthesis_1", "42", "stop", combine=evidence),
    )
    return _attempts_case(
        (
            _attempt(1, "41", 0.0, operations=operations),
            _attempt(2, "42", 1.0, operations=operations),
        )
    )


def _kinds(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["kind"] for entry in entries]


# --- XT#1-3: CHAR, today's export ----------------------------------------------------------------


def test_case_to_dict_of_a_combine_case_has_no_trace_key() -> None:
    report = _report(fixture_case("vote_one_failed", case_id=1))
    report.to_dict()
    report.to_json()
    case = report.candidates[0].cases[0]

    assert list(case.to_dict()) == _CASE_KEYS
    assert "trace" not in case.to_dict()


def test_json_export_equals_to_dict_for_a_combine_report(tmp_path: Path) -> None:
    report = _report(fixture_case("vote_one_failed", case_id=1))
    text = report.to_json()

    assert json.loads(text) == report.to_dict()
    assert report.export(tmp_path / "report.json").read_text(encoding="utf-8") == text


def test_case_without_combine_evidence_exports_its_to_dict() -> None:
    cases = (_plain_case(1), _no_evidence_case(2))
    report = _report(*cases, operations=fixture_graph(3))

    assert _exported(report) == [case.to_dict() for case in cases]


# --- XT#4-9: the trace key -----------------------------------------------------------------------


def test_combine_case_export_carries_its_trace() -> None:
    report = _report(fixture_case("vote_one_failed", case_id=1))
    (exported,) = _exported(report)

    assert list(exported) == [*_CASE_KEYS, "trace"]
    trace = exported["trace"]
    assert _kinds(trace) == ["model_call"] * 3 + ["extract"] * 3 + ["reduce"]
    assert [e["member_id"] for e in trace if e["kind"] == "model_call"] == [
        "member_1",
        "member_2",
        "member_3",
    ]
    reduce_entry = trace[-1]
    assert reduce_entry["op"] == "vote"
    assert reduce_entry["mode"] == "select"
    assert reduce_entry["chosen"] == ["member_1"]
    assert reduce_entry["dropped"] == 1
    assert reduce_entry["judge_operation_id"] is None
    assert reduce_entry["judge_model"] is None
    assert reduce_entry["tally"] == [
        {"value": "42", "score": 2.0, "holders": ["member_1", "member_3"]}
    ]


def test_trace_is_the_last_key_after_abstained() -> None:
    report = _report(_abstained_case(1), operations=fixture_graph(3))
    (exported,) = _exported(report)

    assert list(exported)[-2:] == ["abstained", "trace"]
    assert exported["abstained"] is True
    reduce_entry = exported["trace"][-1]
    assert reduce_entry["kind"] == "reduce"
    assert reduce_entry["result"] == _NO_RESULT
    assert reduce_entry["chosen"] == []
    assert reduce_entry["dropped"] == 3


def test_to_json_export_file_and_to_dict_carry_the_same_trace(tmp_path: Path) -> None:
    report = _report(fixture_case("vote_one_failed", case_id=1))
    text = report.to_json()
    streamed: Any = json.loads(text)
    (exported,) = streamed["candidates"][0]["cases"]

    assert "trace" in exported
    assert _kinds(exported["trace"]) == ["model_call"] * 3 + ["extract"] * 3 + ["reduce"]
    assert streamed == report.to_dict()
    assert report.export(tmp_path / "report.json").read_text(encoding="utf-8") == text
    assert inline_json(report, limit=1_000_000) == text


def test_case_without_operations_or_combine_or_failed_has_no_trace() -> None:
    cases = (
        _plain_case(1),
        _no_evidence_case(2),
        _failed_case(3),
        fixture_case("vote_one_failed", case_id=4),
    )
    report = _report(*cases)
    exported = _exported(report)

    assert ["trace" in item for item in exported] == [False, False, False, True]
    assert exported[:3] == [case.to_dict() for case in cases[:3]]


def test_case_with_attempts_has_no_trace_key() -> None:
    attempts = _attempts_with_evidence()
    report = _report(
        fixture_case("vote_one_failed", case_id=2), attempts, operations=fixture_graph(3)
    )
    exported = _exported(report)

    assert attempts.operations is None
    assert ["trace" in item for item in exported] == [True, False]
    assert exported[1] == attempts.to_dict()


def test_exported_trace_holds_no_member_output_text() -> None:
    outputs = [f"I worked it out. The number is 42 SENTINEL-{k}" for k in (1, 2, 3)]
    report = _report(
        fixture_case("vote_one_failed", outputs=outputs, case_id=1), operations=fixture_graph(3)
    )
    (exported,) = _exported(report)

    assert "trace" in exported
    assert "SENTINEL" not in json.dumps(exported["trace"])
    assert "SENTINEL" in json.dumps(exported)  # the operations still hold the member text


# --- XT#10-13: the field sets, the goldens and one builder --------------------------------------


def test_exported_entries_keep_the_report_trace_v1_field_sets() -> None:
    reports = (combine_report(), vote_median_report(), _report(_abstained_case(1)))
    traces = [item["trace"] for report in reports for item in _exported(report) if "trace" in item]

    assert len(traces) == 4  # combine Case 3, vote Case 1, median Case 1, the abstained Case
    for entries in traces:
        for entry in entries:
            assert list(entry) == ["kind", *TRACE_FIELDS[entry["kind"]]]


def test_export_minus_trace_is_case_to_dict_for_every_golden_case() -> None:
    for report, flags in (
        (combine_report(), [False, False, True]),
        (vote_median_report(), [True, True]),
    ):
        value: Any = report.to_dict()
        assert value["schema"] == "screamingface.report.v1"
        cases = [case for result in report.candidates for case in result.cases]
        exported = _exported(report)
        assert ["trace" in item for item in exported] == flags
        for item, case in zip(exported, cases, strict=True):
            assert {key: v for key, v in item.items() if key != "trace"} == case.to_dict()
            if "trace" in item:
                assert list(item)[-1] == "trace"


def test_report_v1_goldens_hold_the_trace() -> None:
    combine: Any = json.loads(COMBINE_GOLDEN.read_text(encoding="utf-8"))
    (opus,) = combine["candidates"]
    assert ["trace" in item for item in opus["cases"]] == [False, False, True]
    trace = opus["cases"][2]["trace"]
    assert _kinds(trace) == ["model_call", "extract", "extract", "extract", "reduce"]
    assert (trace[-1]["operation_id"], trace[-1]["chosen"]) == ("op_opus_aggregate", ["member_1"])

    vote_median: Any = json.loads(VOTE_MEDIAN_GOLDEN.read_text(encoding="utf-8"))
    vote, median = vote_median["candidates"]
    vote_trace = vote["cases"][0]["trace"]
    assert _kinds(vote_trace) == ["model_call"] * 3 + ["extract"] * 3 + ["reduce"]
    assert [e["model"] for e in vote_trace[:3]] == ["provider/a", "provider/b", "provider/c"]
    assert (vote_trace[-1]["op"], vote_trace[-1]["chosen"]) == ("vote", ["member_1"])
    median_trace = median["cases"][0]["trace"]
    assert _kinds(median_trace) == ["model_call"] * 4 + ["extract"] * 4 + ["reduce"]
    assert (median_trace[-1]["op"], median_trace[-1]["chosen"]) == ("median", ["member_2"])
    assert median_trace[-1]["result"]["value"] == "20"


def test_exported_trace_equals_trace_dict_entries() -> None:
    report = vote_median_report()
    traced: Any = report.trace_dict()
    exported: Any = report.to_dict()

    for result, traced_result in zip(exported["candidates"], traced["candidates"], strict=True):
        for item, traced_case in zip(result["cases"], traced_result["cases"], strict=True):
            assert item["case_id"] == traced_case["case_id"]
            assert "trace" in item
            assert item["trace"] == traced_case["entries"]
    assert [len(r["cases"][0]["trace"]) for r in exported["candidates"]] == [7, 9]
