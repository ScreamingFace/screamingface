"""The MedXpertQA cross-row reducer — check records in, `CandidateResult` out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.medxpert.aggregate import (
    AggregateError,
    aggregate,
    load_answer,
    selected_cases,
)
from screamingface_engine.benchmarks.medxpert.case_evaluation import (
    CHECK_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine.benchmarks.medxpert.definition import BENCHMARK_ID, REVISION

_KEYS = {1: "C", 2: "A"}


def _root(tmp_path: Path, case_ids: tuple[int, ...] = (1, 2)) -> Path:
    (tmp_path / "answers").mkdir()
    (tmp_path / "cases.json").write_text(
        json.dumps([{"id": i, "input": f"Question {i}?"} for i in case_ids]),
        encoding="utf-8",
    )
    for case_id in case_ids:
        (tmp_path / "answers" / f"{case_id}.json").write_text(
            json.dumps(
                {
                    "source_id": f"src-{case_id}",
                    "label": _KEYS[case_id],
                    "options_count": 5,
                    "metadata": {},
                }
            ),
            encoding="utf-8",
        )
    return tmp_path


def _record(case_id: int, letter: str) -> dict[str, object]:
    return {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": letter,
        "answered": bool(letter),
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "commit_output": f"the answer is {letter}" if letter else "I am not sure.",
        "reasoning": "step by step",
        "execution": None,
    }


def _case_execution(case_id: int, grading: object) -> dict[str, object]:
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(f"the answer is {case_id}", "stop", None),
        [grading],
    )


def _rows(*letters_by_case: tuple[int, str]) -> str:
    return json.dumps(
        [
            _case_execution(case_id, bind_case_evaluation(case_id, [_record(case_id, letter)]))
            for case_id, letter in letters_by_case
        ]
    )


def _aggregate(root: Path, raw_rows: str, case_ids: tuple[int, ...] = (1, 2)) -> dict:
    return aggregate(
        raw_rows,
        root,
        benchmark_id=BENCHMARK_ID,
        benchmark_revision=REVISION,
        case_ids=case_ids,
    )


def test_scores_plain_accuracy_over_the_selected_cases(tmp_path: Path) -> None:
    result = _aggregate(_root(tmp_path), _rows((1, "C"), (2, "B")))

    assert result["score"] == 0.5
    assert result["metrics"]["correct"] == 1
    assert result["metrics"]["scored_cases"] == 2
    assert result["metrics"]["answered_rate"] == 1.0


def test_an_unanswered_case_scores_zero_and_stays_in_the_denominator(tmp_path: Path) -> None:
    """INVARIANT: the official empty-prediction verdict — 0.0, never excluded."""

    result = _aggregate(_root(tmp_path), _rows((1, "C"), (2, "")))

    assert result["score"] == 0.5
    assert result["metrics"]["scored_cases"] == 2
    assert result["metrics"]["answered"] == 1
    assert result["metrics"]["answered_rate"] == 0.5


def test_a_wrong_letter_and_a_missing_letter_are_both_scored_not_withheld(tmp_path: Path) -> None:
    result = _aggregate(_root(tmp_path), _rows((1, "B"), (2, "")))

    assert result["score"] == 0.0
    assert [case["grade"]["score"] for case in result["cases"]] == [0.0, 0.0]
    assert [case["grade"]["metrics"]["answered"] for case in result["cases"]] == [True, False]


def test_the_check_row_records_the_committed_and_expected_letters(tmp_path: Path) -> None:
    result = _aggregate(_root(tmp_path), _rows((1, "B"), (2, "A")))

    first = result["cases"][0]["grade"]["checks"][0]
    assert first["outcome"] == "UNMET"
    assert first["metadata"] == {"committed": "B", "expected": "C"}
    assert result["cases"][1]["grade"]["checks"][0]["outcome"] == "MET"


def test_a_case_with_no_row_becomes_a_visible_failure_not_a_zero(tmp_path: Path) -> None:
    """A Case that never ran has NOT been measured — score None, not 0.0."""

    result = _aggregate(_root(tmp_path), _rows((1, "C")))

    second = result["cases"][1]
    assert second["grade"]["score"] is None
    assert second["failures"][0]["code"] == "missing_case_row"
    assert result["score"] == 1.0
    assert result["metrics"]["scored_cases"] == 1


def test_an_identified_error_row_fails_that_case_as_a_case_error(tmp_path: Path) -> None:
    rows = json.dumps(
        [
            _case_execution(1, bind_case_evaluation(1, [_record(1, "C")])),
            {"case_id": 2, "error": {"kind": "ResolutionError", "message": "the call 429'd"}},
        ]
    )

    result = _aggregate(_root(tmp_path), rows)

    failure = result["cases"][1]["failures"][0]
    assert failure["code"] == "case_error"
    assert failure["stage"] == "candidate"
    assert result["cases"][1]["grade"]["score"] is None


def test_an_anonymous_collected_error_keeps_its_cause_on_the_rowless_case(tmp_path: Path) -> None:
    """An on_error=collect row loses its Case identity — the symptom must still name the cause."""

    rows = json.dumps(
        [
            _case_execution(1, bind_case_evaluation(1, [_record(1, "C")])),
            {"error": {"kind": "ResolutionError", "message": "the call 429'd"}},
        ]
    )

    result = _aggregate(_root(tmp_path), rows)

    failure = result["cases"][1]["failures"][0]
    assert failure["code"] == "missing_case_row"
    assert "429" in failure["message"]
    assert failure["metadata"]["source_error"]["kind"] == "ResolutionError"


def test_a_missing_answer_asset_fails_that_case_alone(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "answers" / "2.json").write_text("{}", encoding="utf-8")

    result = _aggregate(root, _rows((1, "C"), (2, "A")))

    assert result["cases"][1]["failures"][0]["code"] == "missing_answer_asset"
    assert result["cases"][0]["grade"]["score"] == 1.0


def test_more_rows_than_selected_cases_aborts_before_scoring(tmp_path: Path) -> None:
    rows = _rows((1, "C"), (2, "A"))

    with pytest.raises(AggregateError, match="rows for 1 selected Cases"):
        _aggregate(_root(tmp_path), rows, case_ids=(1,))


def test_unusable_cases_json_aborts_before_scoring(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "cases.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AggregateError, match="must be a JSON array"):
        _aggregate(root, _rows((1, "C"), (2, "A")))


def test_load_answer_rejects_a_record_without_a_label(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "answers" / "1.json").write_text(json.dumps({"label": ""}), encoding="utf-8")

    assert load_answer(root, 1) is None


def test_selected_cases_preserves_the_requested_order(tmp_path: Path) -> None:
    chosen = selected_cases(_root(tmp_path), (2, 1))

    assert [case.case_id for case in chosen] == [2, 1]
