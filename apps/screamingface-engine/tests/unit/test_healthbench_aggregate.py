"""HealthBench retains every Case and scores only complete normal rubric grades."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.healthbench.aggregate import (
    AggregateError,
    aggregate,
    grade_case,
    load_rubric_points,
    score_cases,
    selected_cases,
)
from screamingface_engine.benchmarks.healthbench.case_evaluation import (
    CASE_EVALUATION_SCHEMA,
    RUBRIC_EVALUATION_SCHEMA,
)
from screamingface_engine.benchmarks.healthbench.records import CASE_SCHEMA, RUBRIC_SCHEMA
from screamingface_engine.benchmarks.healthbench.scoring import clipped_mean, unclipped_mean
from screamingface_engine.benchmarks.healthbench.verdict import SCHEMA as VERDICT_SCHEMA


def _write_rubric(root: Path, case_id: int, points: list[int]) -> None:
    _write_case(root, case_id)
    rubric_dir = root / "rubrics"
    rubric_dir.mkdir(parents=True, exist_ok=True)
    (rubric_dir / f"{case_id}.json").write_text(
        json.dumps(
            {
                "hf_id": f"hf-{case_id}",
                "items": [
                    {"rubric_id": index, "criterion": f"c{index}", "points": value}
                    for index, value in enumerate(points, start=1)
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_case(root: Path, case_id: int) -> None:
    cases_path = root / "cases.json"
    cases = json.loads(cases_path.read_text()) if cases_path.exists() else []
    if not any(row["id"] == case_id for row in cases):
        cases.append({"id": case_id, "input": f"input-{case_id}"})
        cases_path.write_text(json.dumps(cases), encoding="utf-8")


def _evidence(case_id: int, rubric_id: int, met: bool) -> dict[str, object]:
    return {
        "schema": VERDICT_SCHEMA,
        "case_id": case_id,
        "rubric_id": rubric_id,
        "producer_type": "model",
        "producer_id": "judge",
        "valid": True,
        "criteria_met": met,
        "explanation": "…",
        "raw_output": "{}",
    }


def _case_row(
    case_id: int,
    verdicts: dict[int, bool],
    *,
    refusal: str | None = None,
    execution: dict[str, object] | None = None,
) -> dict[str, object]:
    output = None if refusal is not None else f"output-{case_id}"
    answer = refusal if refusal is not None else output
    grading = {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": case_id,
        "case": {
            "schema": CASE_SCHEMA,
            "case_id": case_id,
            "input": f"input-{case_id}",
            "status": "refused" if refusal is not None else "completed",
            "answer": answer,
            "output": output,
            "finish_reason": "content_filter" if refusal is not None else "stop",
            "refusal": refusal,
            "execution": execution,
            "metadata": {},
        },
        "rubric_evaluations": [
            {
                "schema": RUBRIC_EVALUATION_SCHEMA,
                "case_id": case_id,
                "rubric_id": rubric_id,
                "rubric": {
                    "schema": RUBRIC_SCHEMA,
                    "case_id": case_id,
                    "rubric_id": rubric_id,
                    "rubric_item": f"[1] c{rubric_id}",
                },
                "evidence": _evidence(case_id, rubric_id, met),
            }
            for rubric_id, met in verdicts.items()
        ],
    }
    assert isinstance(answer, str)
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(
            output or "",
            "content_filter" if refusal is not None else "stop",
            refusal,
        ),
        [grading],
    )


def _grading(row: dict[str, object]) -> dict[str, Any]:
    outcomes = row["grading"]
    assert isinstance(outcomes, list) and isinstance(outcomes[0], dict)
    return outcomes[0]


def _failure_codes(result: dict[str, Any]) -> dict[int, str | None]:
    """case_id → the Case's single failure code (None when scored clean)."""

    return {
        case["case_id"]: (case["failures"][0]["code"] if case["failures"] else None)
        for case in result["cases"]
    }


def test_fully_judged_cases_score_and_mean_unclipped(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7, 8, -6])
    _write_rubric(tmp_path, 2, [5])
    rows = json.dumps(
        [
            _case_row(1, {1: False, 2: False, 3: True}),  # (0-6)/15 = -0.4
            _case_row(2, {1: True}),  # 1.0
        ]
    )
    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=unclipped_mean,
    )
    assert result["score"] == pytest.approx((1.0 - 0.4) / 2)
    assert result["coverage"] == 1.0
    assert result["metrics"].get("scored_cases") == 2
    assert result["metrics"].get("verdict_coverage") == 1.0
    assert _failure_codes(result) == {1: None, 2: None}
    # The check-level verdict the SDK renders from (ifeval precedent): the judge's
    # decision surfaces as a top-level outcome, not only inside evidence.
    checks = result["cases"][0]["grade"]["checks"]
    assert [check["outcome"] for check in checks] == ["UNMET", "UNMET", "MET"]
    assert [check["label"] for check in checks] == ["[1] c1", "[1] c2", "[1] c3"]
    assert [check["metadata"] for check in checks] == [
        {"points": 7},
        {"points": 8},
        {"points": -6},
    ]
    # SDK Case Result contract (seen live in the smoke run): every Case carries
    # the full key set, a scored Case carries a rubric grade, and evidence rows
    # sit under grade.checks — not in any home-grown envelope.
    first = result["cases"][0]
    assert set(first) == {
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
    }
    assert first["output"] == "output-1"
    grade = first["grade"]
    assert grade is not None
    assert grade["method"] == "rubric"
    assert grade["score"] == pytest.approx(-0.4)
    assert [check["id"] for check in grade["checks"]] == ["1", "2", "3"]
    assert grade["checks"][2]["evidence"][0]["outcome"] == "MET"
    # The SDK's candidate-result contract requires a top-level failures list even
    # when empty — omitting the key breaks report decoding (seen live in the smoke
    # run); healthbench routes every failure to a Case, so it is always [].
    assert result["failures"] == []
    # Same decoder rejects non-numeric metric values (also seen live) — the
    # scoring label must never reappear inside metrics.
    assert all(isinstance(value, (int, float)) for value in result["metrics"].values())


def test_live_projection_and_final_aggregation_share_case_grading_and_scorer(
    tmp_path: Path,
) -> None:
    _write_rubric(tmp_path, 1, [5, -2])
    row = _case_row(1, {1: True, 2: False})
    selected = selected_cases(tmp_path, (1,))[0]

    projected = grade_case(row, selected, [5, -2])
    final = aggregate(
        json.dumps([row]),
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=unclipped_mean,
    )

    assert projected.model_dump() == final["cases"][0]
    assert score_cases(unclipped_mean, [projected]).score == final["score"]


def test_canonical_contract_metrics_map_healthbench_semantics(tmp_path: Path) -> None:
    """The MAPPING is under test — presence/range is the CandidateResult model's job.

    pass_rate is the UNWEIGHTED criterion hit rate (met / judged), deliberately
    different from `score`, the point-weighted unclipped mean. Top-level coverage
    counts gradeable Cases, while verdict_coverage describes rubric completeness
    within those grades.
    """

    _write_rubric(tmp_path, 1, [7, 8, -6])
    _write_rubric(tmp_path, 2, [5])
    rows = json.dumps(
        [
            _case_row(1, {1: False, 2: False, 3: True}),
            _case_row(2, {1: True}),
        ]
    )
    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=unclipped_mean,
    )
    # 2 of 4 judged criteria met (case 1: only the penalty item; case 2: its one item).
    assert result["metrics"]["pass_rate"] == pytest.approx(0.5)
    assert result["coverage"] == result["metrics"]["verdict_coverage"] == 1.0
    # The weighted/unweighted distinction is real: same run, different numbers.
    assert result["score"] != result["metrics"]["pass_rate"]


def test_a_negative_unclipped_mean_survives_the_contract(tmp_path: Path) -> None:
    """INVARIANT: the challenge metric is UNCLIPPED — a penalty-dominated run scores
    negative and must pass the CandidateResult contract (its score has no lower
    bound); clamping or rejecting it would corrupt worst-30 ranking."""

    _write_rubric(tmp_path, 1, [2, -8])
    rows = json.dumps([_case_row(1, {1: True, 2: True})])  # (2-8)/2 = -3.0
    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=unclipped_mean,
    )
    assert result["score"] == pytest.approx(-3.0)
    assert result["metrics"]["pass_rate"] == 1.0  # every criterion judged MET — yet negative


def test_duplicate_rubric_entries_abort_as_protocol_corruption(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [5, 3])
    row = _case_row(1, {1: True, 2: True})
    evaluations = _grading(row)["rubric_evaluations"]
    assert isinstance(evaluations, list)
    evaluations.append(json.loads(json.dumps(evaluations[0])))
    with pytest.raises(AggregateError, match="duplicate HealthBench rubric_id"):
        aggregate(
            json.dumps([row]),
            tmp_path,
            benchmark_id="hb",
            benchmark_revision="rev",
            case_ids=(1,),
            mean=unclipped_mean,
        )


def test_a_missing_rubric_asset_lowers_coverage_without_erasing_valid_scores(
    tmp_path: Path,
) -> None:
    _write_rubric(tmp_path, 1, [7])
    _write_case(tmp_path, 2)
    rows = json.dumps([_case_row(1, {1: True}), _case_row(2, {1: True})])
    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=unclipped_mean,
    )
    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert _failure_codes(result) == {1: None, 2: "missing_rubric_asset"}
    assert result["metrics"]["scored_cases"] == 1


def test_an_error_collected_row_fails_its_case(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7])
    _write_rubric(tmp_path, 2, [3])
    rows = json.dumps(
        [
            _case_row(1, {1: True}),
            {
                "schema": CASE_EVALUATION_SCHEMA,
                "case_id": 2,
                "error": {
                    "kind": "ResolutionError",
                    "code": "provider_error",
                    "message": "the provider was unavailable",
                    "permanent": True,
                },
            },
        ]
    )
    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=unclipped_mean,
    )
    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert _failure_codes(result)[2] == "case_error"
    failed = next(case for case in result["cases"] if case["case_id"] == 2)
    assert failed["grade"]["score"] is None
    assert failed["failures"][0]["message"] == "the provider was unavailable"
    assert failed["failures"][0]["metadata"]["source_error"] == {
        "kind": "ResolutionError",
        "code": "provider_error",
        "message": "the provider was unavailable",
        "retryable": False,
    }


def test_partial_verdicts_never_score(tmp_path: Path) -> None:
    # INVARIANT: a judge failure on a penalty item would erase the penalty — a Case
    # missing any verdict must fail, never score from the items that did parse.
    _write_rubric(tmp_path, 1, [7, -6])
    rows = json.dumps([_case_row(1, {1: True})])  # the -6 item was never judged
    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=unclipped_mean,
    )
    assert result["score"] is None
    assert _failure_codes(result) == {1: "incomplete_verdicts"}
    # The judged item's evidence is still auditable via grade.checks even though
    # the Case failed — grade.score stays None (the contract's "no score" form).
    grade = result["cases"][0]["grade"]
    assert grade is not None
    assert grade["score"] is None
    assert len(grade["checks"]) == 1
    assert result["metrics"] == {}  # unscored → empty (SDK report rule)


def test_a_malformed_case_envelope_aborts_as_protocol_corruption(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7])
    _write_rubric(tmp_path, 2, [3])
    malformed = _case_row(2, {1: True})
    del _grading(malformed)["case"]  # complete verdicts, but the Candidate record is gone
    with pytest.raises(AggregateError, match="invalid HealthBench Case Evaluation"):
        aggregate(
            json.dumps([_case_row(1, {1: True}), malformed]),
            tmp_path,
            benchmark_id="hb",
            benchmark_revision="rev",
            case_ids=(1, 2),
            mean=unclipped_mean,
        )


def test_invalid_judge_evidence_counts_and_fails_the_case(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7])
    row = _case_row(1, {1: True})
    evaluations = _grading(row)["rubric_evaluations"]
    assert isinstance(evaluations, list)
    evaluations[0]["evidence"] = {
        "schema": VERDICT_SCHEMA,
        "case_id": 1,
        "rubric_id": 1,
        "valid": False,
        "reason": "invalid_json",
        "raw_output": "not json",
    }
    result = aggregate(
        json.dumps([row]),
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=unclipped_mean,
    )
    assert result["score"] is None
    assert result["metrics"] == {}  # unscored → empty (SDK report rule)
    assert _failure_codes(result) == {1: "incomplete_verdicts"}


def test_provider_refusals_are_mapped_by_case_and_preserved_exactly(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7])
    _write_rubric(tmp_path, 2, [7])
    first = "I can’t answer the first request."
    second = "I can’t answer the second request."

    result = aggregate(
        json.dumps(
            [_case_row(1, {1: True}, refusal=first), _case_row(2, {1: False}, refusal=second)]
        ),
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=unclipped_mean,
    )

    assert result["score"] == 0.5
    assert result["coverage"] == 1.0
    assert [case["status"] for case in result["cases"]] == ["refused", "refused"]
    assert [case["refusal"] for case in result["cases"]] == [first, second]
    assert [case["finish_reason"] for case in result["cases"]] == [
        "content_filter",
        "content_filter",
    ]
    assert [case["grade"]["score"] for case in result["cases"]] == [1.0, 0.0]
    assert [case["failures"] for case in result["cases"]] == [[], []]


def test_corrective_execution_provenance_reaches_the_case_result(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7])
    execution = {
        "schema": "screamingface.corrective-execution.v1",
        "stop_reason": "passed",
        "rounds_executed": 2,
    }

    result = aggregate(
        json.dumps([_case_row(1, {1: True}, execution=execution)]),
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=unclipped_mean,
    )

    case = result["cases"][0]
    assert case["stop_reason"] == "passed"
    assert case["rounds_executed"] == 2


def test_a_missing_case_row_is_visible(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7])
    _write_rubric(tmp_path, 2, [3])
    result = aggregate(
        json.dumps([_case_row(1, {1: True})]),
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=unclipped_mean,
    )
    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert _failure_codes(result)[2] == "missing_case_row"


def test_unusable_row_payloads_raise_before_scoring(tmp_path: Path) -> None:
    with pytest.raises(AggregateError):
        aggregate(
            "not json",
            tmp_path,
            benchmark_id="hb",
            benchmark_revision="rev",
            case_ids=(1,),
            mean=unclipped_mean,
        )


def test_no_rows_retains_every_selected_case_as_failed(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7])
    result = aggregate(
        "[]",
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=unclipped_mean,
    )

    assert result["score"] is None
    assert result["cases"][0]["failures"][0]["code"] == "missing_case_row"


def test_load_rubric_points_rejects_malformed_assets(tmp_path: Path) -> None:
    assert load_rubric_points(tmp_path, 9) is None  # absent
    rubric_dir = tmp_path / "rubrics"
    rubric_dir.mkdir()
    (rubric_dir / "9.json").write_text("not json", encoding="utf-8")
    assert load_rubric_points(tmp_path, 9) is None
    (rubric_dir / "9.json").write_text(
        json.dumps({"items": [{"rubric_id": 1, "points": 7.5}]}), encoding="utf-8"
    )
    assert load_rubric_points(tmp_path, 9) is None  # float points are corrupt
    (rubric_dir / "9.json").write_text(
        json.dumps({"items": [{"rubric_id": 2, "points": 7}]}), encoding="utf-8"
    )
    assert load_rubric_points(tmp_path, 9) is None  # ids must be consecutive from 1


def test_the_official_board_floors_a_negative_mean_at_zero(tmp_path: Path) -> None:
    """INVARIANT (OME-903): one reduction, two exam-level metrics.

    The SAME graded Cases must produce the challenge number on the worst-30% board and the
    official number on the professional board — the clip is the ONLY difference. A run
    dominated by safety penalties averages -3.0 here; the official HealthBench aggregate
    reports 0.0 for it, which is what makes the number comparable to published figures.
    """

    _write_rubric(tmp_path, 1, [2, -8])
    rows = json.dumps([_case_row(1, {1: True, 2: True})])  # (2-8)/2 = -3.0

    challenge = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=unclipped_mean,
    )
    official = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1,),
        mean=clipped_mean,
    )

    assert challenge["score"] == pytest.approx(-3.0)
    assert official["score"] == 0.0
    # Only the exam-level number moves: the per-Case grade keeps its unclamped truth, so a
    # reader can still see WHY the board says zero.
    assert official["cases"][0]["grade"]["score"] == pytest.approx(-3.0)
    assert official["coverage"] == challenge["coverage"] == 1.0
    assert official["metrics"]["pass_rate"] == challenge["metrics"]["pass_rate"]


def test_the_official_board_leaves_an_ordinary_mean_alone(tmp_path: Path) -> None:
    _write_rubric(tmp_path, 1, [7, 8, -6])
    _write_rubric(tmp_path, 2, [5])
    rows = json.dumps(
        [
            _case_row(1, {1: True, 2: True, 3: False}),  # 15/15 = 1.0
            _case_row(2, {1: False}),  # 0.0
        ]
    )
    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="hb",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=clipped_mean,
    )
    assert result["score"] == pytest.approx(0.5)
