"""The MuSiQue-Ans grade and its reduction — three Named Scores per Case, column means per run.

Every test runs on the two real dev Cases prepared by the real Case Preparation:

    Case 1  2hop__460946_294723         gold `Miquette Giraudy`, no aliases, support {5, 10}
    Case 2  3hop1__454441_55349_651302  gold `Denver`, alias `Denver, Colorado`, support {0, 7, 9}

and on the spec's reply table ("How a reply becomes three numbers"), so a number asserted here
is a number a reader can check by hand against the spec.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.graded_answer import graded_answer_payload
from screamingface_engine.benchmarks.musique.aggregate import (
    NAMED_SCORES,
    AggregateError,
    aggregate,
    load_answer,
    selected_cases,
)
from screamingface_engine.benchmarks.musique.case_grade import CHECK_SCHEMA, build_case_grade
from screamingface_engine.benchmarks.musique.definition import BENCHMARK_ID, REVISION
from screamingface_engine.benchmarks.musique.prepare import case_records, emit, parse_rows

_FIXTURE: Path = Path(__file__).parents[1] / "fixtures/musique/dev_two_rows.jsonl"
_FIXTURE_CASES = 2


def _root(tmp_path: Path) -> Path:
    """Prepare the two fixture Cases into ``tmp_path`` with the real Case Preparation."""

    cases, answers = case_records(parse_rows(_FIXTURE.read_bytes(), expected_count=_FIXTURE_CASES))
    emit(tmp_path, cases, answers)
    return tmp_path


def _record(
    case_id: int,
    answer: str,
    support: list[int],
    *,
    answer_line: bool = True,
    support_line: bool = True,
) -> dict[str, object]:
    """One check record, as `runtime._check` writes it for a reply that committed these."""

    return {
        "schema": CHECK_SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "answer": answer,
        "support": support,
        "answer_line": answer_line,
        "support_line": support_line,
        "status": "completed",
        "refusal": None,
        "finish_reason": "stop",
        "output": "reply",
        "execution": None,
    }


def _rows(*records: dict[str, Any]) -> str:
    """The collected Case execution rows the aggregate route receives."""

    return json.dumps(
        [
            graded_answer_payload(
                record["case_id"],
                encode_candidate_invocation("reply", "stop", None),
                [build_case_grade(record["case_id"], [record])],
            )
            for record in records
        ]
    )


def _aggregate(root: Path, raw: str, case_ids: tuple[int, ...]) -> dict[str, Any]:
    """Run the Benchmark's own reducer over ``raw``."""

    return aggregate(
        raw, root, benchmark_id=BENCHMARK_ID, benchmark_revision=REVISION, case_ids=case_ids
    )


def _grade(tmp_path: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Grade one record for Case ``record["case_id"]`` and return its published grade."""

    case_id: int = int(record["case_id"])
    result: dict[str, Any] = _aggregate(_root(tmp_path), _rows(record), (case_id,))
    return result["cases"][0]["grade"]


# --- one Case: the spec's reply table --------------------------------------------------------


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        # `Supporting paragraphs: 10, 5` / `Answer: Miquette Giraudy`
        (_record(1, "Miquette Giraudy", [5, 10]), (1.0, 1.0, 1.0)),
        # `Supporting paragraphs: 10` / `**Answer:** Giraudy`: precision 1/1, recall 1/2
        (_record(1, "** Giraudy", [10]), (0.6667, 0.0, 0.6667)),
        # `Answer:` / `Miquette Giraudy` on the next line, no support line
        (_record(1, "Miquette Giraudy", [], support_line=False), (1.0, 1.0, 0.0)),
        # the whole sentence: 2 of 9 normalised tokens match, F1 = 4/11
        (
            _record(
                1,
                "The performer is Steve Hillage, whose partner is Miquette Giraudy.",
                [],
                answer_line=False,
                support_line=False,
            ),
            (0.3636, 0.0, 0.0),
        ),
    ],
    ids=["committed", "partial", "missing-support", "missing-both"],
)
def test_each_reply_in_the_spec_table_earns_the_spec_s_three_numbers(
    tmp_path: Path, record: dict[str, Any], expected: tuple[float, float, float]
) -> None:
    """The reply table is the contract between the spec and the grade: f1, exact, support_f1."""

    grade: dict[str, Any] = _grade(tmp_path, record)

    assert tuple(grade["scores"].values()) == pytest.approx(expected, abs=1e-4)


def test_a_case_grade_carries_exactly_the_declared_named_scores_headline_first(
    tmp_path: Path,
) -> None:
    """Spec D9: `f1` (the paper's An), then `exact`, then `support_f1` (the paper's Sp)."""

    grade: dict[str, Any] = _grade(tmp_path, _record(1, "** Giraudy", [10]))

    assert NAMED_SCORES == ("f1", "exact", "support_f1")
    assert list(grade["scores"]) == ["f1", "exact", "support_f1"]


def test_the_case_score_is_the_answer_f1(tmp_path: Path) -> None:
    """INVARIANT: the headline column equals the Case score, so the number a leaderboard ranks
    and the first Named Score are one number, never two."""

    grade: dict[str, Any] = _grade(tmp_path, _record(1, "** Giraudy", [10]))

    assert grade["score"] == grade["scores"]["f1"] == pytest.approx(0.6667, abs=1e-4)


def test_an_alias_counts_as_the_gold_answer(tmp_path: Path) -> None:
    """The official scorer takes the best match over `[answer] + answer_aliases`."""

    grade: dict[str, Any] = _grade(tmp_path, _record(2, "Denver, Colorado", [0, 7, 9]))

    assert grade["scores"] == {"f1": 1.0, "exact": 1.0, "support_f1": 1.0}


def test_the_format_flags_ride_on_the_grade_metrics(tmp_path: Path) -> None:
    """Spec D7: a reply that dropped a committed line is graded AND visibly flagged."""

    grade: dict[str, Any] = _grade(
        tmp_path, _record(1, "Miquette Giraudy", [], answer_line=True, support_line=False)
    )

    assert grade["metrics"] == {"answer_line_found": True, "support_line_found": False}


def test_the_checks_name_each_committed_line_without_publishing_the_gold(tmp_path: Path) -> None:
    """One check per committed line. WHY counts and not the gold answer: the Report is
    published, and the answer key's place is the private Grading Material."""

    grade: dict[str, Any] = _grade(tmp_path, _record(1, "** Giraudy", [10]))
    checks: dict[str, dict[str, Any]] = {check["id"]: check for check in grade["checks"]}

    assert set(checks) == {"answer", "support"}
    assert checks["answer"]["score"] == pytest.approx(0.6667, abs=1e-4)
    assert checks["answer"]["outcome"] == "UNMET"
    assert checks["support"]["outcome"] == "UNMET"
    assert "Miquette" not in json.dumps(grade)


def test_the_case_result_carries_the_dataset_id_and_hop_type(tmp_path: Path) -> None:
    """Spec D12: the per-hop view groups by `hop_type`; both come from the private record, so
    the Candidate never saw them."""

    result: dict[str, Any] = _aggregate(
        _root(tmp_path),
        _rows(_record(1, "Miquette Giraudy", [5, 10]), _record(2, "Denver", [0, 7, 9])),
        (1, 2),
    )

    assert [case["metadata"] for case in result["cases"]] == [
        {"musique_id": "2hop__460946_294723", "hop_type": "2hop"},
        {"musique_id": "3hop1__454441_55349_651302", "hop_type": "3hop1"},
    ]


# --- the run: column means ---------------------------------------------------------------------


def test_the_run_scores_are_the_column_means_over_the_graded_cases(tmp_path: Path) -> None:
    """Case 1 (1.0, 1, 1.0) and Case 2 `Denver, CO` citing {0, 7} (0.6667, 0, 0.8):
    f1 0.8333 · exact 0.5 · support_f1 0.9, and the run score is the f1 mean."""

    result: dict[str, Any] = _aggregate(
        _root(tmp_path),
        _rows(_record(1, "Miquette Giraudy", [5, 10]), _record(2, "Denver, CO", [0, 7])),
        (1, 2),
    )

    assert list(result["scores"]) == ["f1", "exact", "support_f1"]
    assert result["scores"] == pytest.approx(
        {"f1": 0.8333, "exact": 0.5, "support_f1": 0.9}, abs=1e-4
    )
    assert result["score"] == result["scores"]["f1"]
    assert result["metrics"]["scored_cases"] == 2


def test_the_run_reports_how_often_each_line_was_found(tmp_path: Path) -> None:
    """The flags' run-level view: the share of graded Cases that committed each line."""

    result: dict[str, Any] = _aggregate(
        _root(tmp_path),
        _rows(
            _record(1, "Miquette Giraudy", [], support_line=False),
            _record(2, "Denver", [0, 7, 9]),
        ),
        (1, 2),
    )

    assert result["metrics"]["answer_line_found_rate"] == 1.0
    assert result["metrics"]["support_line_found_rate"] == 0.5


def test_a_case_that_never_ran_is_a_visible_failure_and_outside_every_mean(
    tmp_path: Path,
) -> None:
    """Spec F6: a Case with no row was not measured — score None, a named failure, and the
    columns average over the one graded Case, all sharing Coverage's denominator."""

    result: dict[str, Any] = _aggregate(
        _root(tmp_path), _rows(_record(1, "** Giraudy", [10])), (1, 2)
    )

    assert result["cases"][1]["grade"]["score"] is None
    assert result["cases"][1]["failures"][0]["code"] == "missing_case_row"
    assert result["scores"] == pytest.approx(
        {"f1": 0.6667, "exact": 0.0, "support_f1": 0.6667}, abs=1e-4
    )
    assert result["metrics"]["scored_cases"] == 1


def test_missing_grading_material_fails_that_case_alone(tmp_path: Path) -> None:
    """Spec F7: an unusable answer record is `missing_answer_asset`, never a 0."""

    root: Path = _root(tmp_path)
    (root / "answers" / "2.json").write_text("{}", encoding="utf-8")

    result: dict[str, Any] = _aggregate(
        root,
        _rows(_record(1, "Miquette Giraudy", [5, 10]), _record(2, "Denver", [0, 7, 9])),
        (1, 2),
    )

    assert result["cases"][1]["failures"][0]["code"] == "missing_answer_asset"
    assert result["cases"][1]["grade"]["score"] is None
    assert result["cases"][0]["grade"]["score"] == 1.0
    assert result["metrics"]["scored_cases"] == 1


def test_a_check_that_crashed_fails_the_case_with_this_benchmark_s_own_code(
    tmp_path: Path,
) -> None:
    """Spec: a grading crash surfaces as `musique_grading_failed`, the code the Engine and the
    SDK both declare."""

    row: dict[str, object] = graded_answer_payload(
        1,
        encode_candidate_invocation("reply", "stop", None),
        [{"error": {"message": "the check could not run"}}],
    )

    result: dict[str, Any] = _aggregate(_root(tmp_path), json.dumps([row]), (1,))

    assert result["cases"][0]["failures"][0]["code"] == "musique_grading_failed"
    assert result["score"] is None


# --- the Grading Material and the roll call --------------------------------------------------


def test_load_answer_reads_the_prepared_record(tmp_path: Path) -> None:
    answer: dict[str, Any] | None = load_answer(_root(tmp_path), 2)

    assert answer is not None
    assert answer["answer_aliases"] == ["Denver, Colorado"]
    assert answer["supporting_idx"] == [0, 7, 9]


@pytest.mark.parametrize(
    "broken",
    [
        {},
        {"answer": "Denver", "answer_aliases": "Denver, Colorado"},
        {"answer": "Denver", "answer_aliases": [], "supporting_idx": [True]},
        {"answer": 7, "answer_aliases": [], "supporting_idx": [0]},
    ],
)
def test_load_answer_refuses_a_record_the_scorer_cannot_use(
    tmp_path: Path, broken: dict[str, object]
) -> None:
    """An ill-typed record would reach the official scorer as wrong gold; it is unusable
    material instead, which the ladder reports as `missing_answer_asset`."""

    root: Path = _root(tmp_path)
    (root / "answers" / "1.json").write_text(json.dumps(broken), encoding="utf-8")

    assert load_answer(root, 1) is None


def test_more_rows_than_selected_cases_aborts_before_scoring(tmp_path: Path) -> None:
    rows: str = _rows(_record(1, "a", [5]), _record(2, "b", [0]))

    with pytest.raises(AggregateError, match="rows for 1 selected Cases"):
        _aggregate(_root(tmp_path), rows, (1,))


def test_selected_cases_preserves_the_requested_order(tmp_path: Path) -> None:
    chosen = selected_cases(_root(tmp_path), (2, 1))

    assert [case.case_id for case in chosen] == [2, 1]
