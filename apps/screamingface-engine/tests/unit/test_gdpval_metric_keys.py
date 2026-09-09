"""OME-1097: pin gdpval's published metric vocabulary byte-identical.

gdpval-text has NO e2e golden yet (OME-1098), so this pin is the only net proving the
shared scored path did not move the board's published surface. The keys are the class
results a leaderboard reader parses; renaming one silently breaks every consumer.

INVARIANT: the metric key set — and the exam-payload keys around it — stay exactly as
the pre-extraction `gdpval/aggregate.py` emitted them.
"""

from __future__ import annotations

import json
from pathlib import Path

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.gdpval.case_evaluation import (
    CASE_EVALUATION_SCHEMA,
    RUBRIC_EVALUATION_SCHEMA,
)
from screamingface_engine.benchmarks.gdpval.grade import aggregate
from screamingface_engine.benchmarks.gdpval.records import CASE_SCHEMA, RUBRIC_SCHEMA
from screamingface_engine.benchmarks.gdpval.scoring import mean
from screamingface_engine.benchmarks.gdpval.verdict import SCHEMA as VERDICT_SCHEMA


def _bake(root: Path, case_id: int, points: list[int]) -> None:
    cases_path = root / "cases.json"
    cases = json.loads(cases_path.read_text()) if cases_path.exists() else []
    cases.append({"id": case_id, "input": f"input-{case_id}"})
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    rubric_dir = root / "rubrics"
    rubric_dir.mkdir(exist_ok=True)
    (rubric_dir / f"{case_id}.json").write_text(
        json.dumps(
            {
                "items": [
                    {"rubric_id": index, "criterion": f"c{index}", "points": value}
                    for index, value in enumerate(points, start=1)
                ]
            }
        ),
        encoding="utf-8",
    )


def _case_row(case_id: int, verdicts: dict[int, bool]) -> dict[str, object]:
    grading = {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": case_id,
        "case": {
            "schema": CASE_SCHEMA,
            "case_id": case_id,
            "input": f"input-{case_id}",
            "status": "completed",
            "answer": f"output-{case_id}",
            "output": f"output-{case_id}",
            "finish_reason": "stop",
            "refusal": None,
            "execution": None,
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
                "evidence": {
                    "schema": VERDICT_SCHEMA,
                    "case_id": case_id,
                    "rubric_id": rubric_id,
                    "producer_type": "model",
                    "producer_id": "judge",
                    "valid": True,
                    "criteria_met": met,
                    "explanation": "…",
                    "raw_output": "{}",
                },
            }
            for rubric_id, met in verdicts.items()
        ],
    }
    return case_execution_payload(
        case_id, encode_candidate_invocation(f"output-{case_id}", "stop", None), [grading]
    )


def test_gdpval_metric_keys_are_byte_identical_to_the_pre_extraction_board(
    tmp_path: Path,
) -> None:
    _bake(tmp_path, 1, [5, 3, -3])
    _bake(tmp_path, 2, [4])
    rows = json.dumps([_case_row(1, {1: True, 2: False, 3: True}), _case_row(2, {1: True})])

    result = aggregate(
        rows,
        tmp_path,
        benchmark_id="gdpval-text",
        benchmark_revision="rev",
        case_ids=(1, 2),
        mean=mean,
    )

    # The pinned vocabulary — exactly these keys, no more, no fewer.
    assert set(result["metrics"]) == {
        "pass_rate",
        "scored_cases",
        "score_sd",
        "verdict_coverage",
        "judge_invalid_replies",
    }
    # And the surrounding exam payload keeps its published shape and math:
    # case 1 = (5-3)/8 = 0.25, case 2 = 4/4 = 1.0, mean = 0.625.
    assert result["score"] == 0.625
    assert result["coverage"] == 1.0
    assert result["metrics"]["pass_rate"] == 0.75  # 3 MET of 4 judged
    assert result["metrics"]["scored_cases"] == 2
    assert result["metrics"]["verdict_coverage"] == 1.0
    assert result["metrics"]["judge_invalid_replies"] == 0
    assert all(isinstance(value, (int, float)) for value in result["metrics"].values())
    assert [case["status"] for case in result["cases"]] == ["scored", "scored"]
