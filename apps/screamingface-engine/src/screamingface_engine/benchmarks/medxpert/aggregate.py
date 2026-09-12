"""MedXpertQA's grading hooks — everything this board still writes to be graded.

The spine owns the marking room (``spine/scored.py``); this module is the board's
contribution: its exact-match ``grade_case`` (committed letter vs the private key),
its plain-accuracy scorer, its slice tags, and its own failure wording. The engine
ships mechanisms; a benchmark ships semantics (folded in OME-1149 — this board was
the "second non-rubric data point" its pre-fold docstring asked for).

INVARIANT — an unparseable answer scores 0.0; it is NOT excluded. This is the official
harness's empty-prediction verdict, and it is what keeps two systems comparable: the prior
experimental run scored a model answering 77% of rows over that smaller, easier denominator,
so its accuracy was not the same measurement as a model that answered all of them.

AIDEV-NOTE: that is deliberately NOT the board's `failure_policy`. That axis governs a Case
which never got a valid grade — an infrastructure failure — and those go through the spine's
failure ladder into the shared `finalize_candidate_result`, which scores the gradeable subset
and publishes coverage. Hence the board declares `coverage_declare`. An empty answer DOES get
a grade here, of 0.0.

INVARIANT — a failure to COMMIT and a failure to RUN are different facts. A model that replies
without a valid letter has answered badly (score 0.0, `answered: false`). A Case whose invocation
errored has not been measured at all (score `None`, a visible failed Case). Collapsing the two
would let an outage look like weakness, or weakness look like an outage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import CandidateScore, SelectedCase
from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.medxpert.case_evaluation import decode_case_evaluation
from screamingface_engine.benchmarks.medxpert.prepare import METADATA_COLUMNS
from screamingface_engine.benchmarks.spine.rows import RowReader, read_selected_cases
from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeRequest,
    ScoredPath,
)

# INVARIANT: failure wording is this board's published voice — no rubric-flavored
# codes ("missing_rubric_asset") may leak into an MCQ result.
_FAILURE_MESSAGES = {
    "missing_answer_asset": "the baked answer record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


def load_answer(root: Path, case_id: int) -> dict[str, Any] | None:
    """Read one Case's private answer record; ``None`` when the asset is unusable."""

    try:
        decoded = json.loads((root / "answers" / f"{case_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, Mapping):
        return None
    label = decoded.get("label")
    return dict(decoded) if isinstance(label, str) and label else None


def selected_cases(root: Path, case_ids: tuple[int, ...]) -> list[SelectedCase]:
    """The roll call from the baked ``cases.json``, in selected order."""

    return read_selected_cases(
        root, case_ids, benchmark_label="MedXpertQA", error_type=AggregateError
    )


def aggregate(
    raw_rows: str,
    root: Path,
    *,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Score every selected Case on the shared scored path, then plain accuracy."""

    # WHY one read per Case: the answer record is both the grading material (its
    # label) and the source of the public slice tags — load once, use twice.
    answers: dict[int, dict[str, Any] | None] = {
        case_id: load_answer(root, case_id) for case_id in case_ids
    }
    return _PATH.aggregate(
        raw_rows,
        benchmark_id=benchmark_id,
        benchmark_revision=benchmark_revision,
        selected_cases=selected_cases(root, case_ids),
        grading_material=lambda case_id: answers.get(case_id),
        scorer=_accuracy,
        case_metadata=lambda case_id: _slice_metadata(answers.get(case_id)),
    )


def _decode(grading: object, expected_case_id: int) -> dict[str, Any]:
    """Validate the envelope, then hoist attempt 1 into the spine's candidate shape.

    The committed letter, reasoning, and refusal all live on the first (only)
    attempt; the spine reads the candidate's half of the row under ``case``.
    """

    envelope = decode_case_evaluation(grading, expected_case_id)
    attempt: Mapping[str, Any] = envelope["attempts"][0]
    metadata: object = attempt.get("metadata")
    fields: dict[str, Any] = dict(metadata) if isinstance(metadata, Mapping) else {}
    # D8: turn 1's essay rides the check envelope into the report — a letter with no
    # reasoning is unauditable, and the audit matters most on the cases that went wrong.
    reasoning: object = attempt.get("reasoning")
    if isinstance(reasoning, str) and reasoning:
        fields["reasoning"] = reasoning
    return {
        "case": {
            "status": attempt.get("status"),
            "output": attempt.get("commit_output"),
            "finish_reason": attempt.get("finish_reason"),
            "refusal": attempt.get("refusal"),
            "execution": attempt.get("execution"),
            "operations": attempt.get("operations"),
            "metadata": fields,
        },
        "attempt": dict(attempt),
    }


async def _grade_case(request: GradeRequest) -> CaseGradeOutcome:
    """Exact-match one committed letter against the private key — the whole exam rule.

    INVARIANT: an unanswered Case scores 0.0, not None — the official empty-prediction
    verdict. It counts toward the denominator like any other answered Case.
    """

    attempt: Mapping[str, Any] = request.row["attempt"]
    material = request.material
    assert isinstance(material, Mapping)  # the ladder already rejected unusable assets
    label: str = str(material["label"])
    committed: str = str(attempt.get("answer") or "")
    answered: bool = bool(committed)
    correct: bool = answered and committed == label
    return CaseGradeOutcome(
        score=1.0 if correct else 0.0,
        metrics={"answered": answered},
        checks=[
            {
                "type": "choice",
                "id": "1",
                "label": "committed choice matches the published key",
                "outcome": "MET" if correct else "UNMET",
                "evidence": [_match_evidence(committed, label, correct)],
                "metadata": {"committed": committed, "expected": label},
            }
        ],
    )


def _slice_metadata(answer: Mapping[str, Any] | None) -> dict[str, Any]:
    """The three PUBLIC slice tags for this Case's report row, and nothing else.

    WHY explicit columns (spec D6): the official leaderboard cuts sub-scores by these axes,
    and a report a researcher cannot group offline forces a re-join against the raw dataset.
    WHY never the whole record: `label` — the answer key — lives in the same file; copying
    the record wholesale would publish the key on every case.
    """

    metadata = answer.get("metadata") if isinstance(answer, Mapping) else None
    if not isinstance(metadata, Mapping):
        return {}
    return {
        column: metadata[column]
        for column in METADATA_COLUMNS
        if isinstance(metadata.get(column), str)
    }


def _match_evidence(committed: str, label: str, correct: bool) -> dict[str, Any]:
    """The exact-match verdict, as the report schema's Evidence record.

    WHY it exists at all for a one-check MCQ Board: `Check.evidence` is required, and a
    reader must be able to see WHAT was compared without re-deriving it from the score.
    `raw_output` carries the committed letter — "" when the reply named no choice.
    """

    return {
        "sequence": 1,
        "producer": {"type": "deterministic", "id": "medxpert/exact-match"},
        "valid": True,
        "outcome": "PASS" if correct else "FAIL",
        "raw_output": committed,
        "metadata": {"expected": label, "answered": bool(committed)},
        "accounting": None,
    }


def _accuracy(cases: Sequence[CaseResult]) -> CandidateScore:
    """Plain accuracy, with the answered fraction reported beside it.

    WHY report `answered` even though the empty-prediction verdict already counts
    unanswered Cases as wrong: 40% built from 40% correct reads very differently from
    40% built from 90% correct and half the rows unanswered, and only the second is a
    formatting failure rather than a knowledge failure.
    """

    grades = [case.grade for case in cases if case.grade is not None]
    scored = [grade for grade in grades if grade.score is not None]
    if not scored:  # pragma: no cover - a Benchmark always selects one Case
        raise AssertionError("MedXpertQA scorer requires at least one scored Case")
    values = [float(grade.score) for grade in scored if grade.score is not None]
    answered = sum(1 for grade in scored if grade.metrics.get("answered"))
    return CandidateScore(
        score=round(sum(values) / len(values), 4),
        metrics={
            "correct": sum(1 for value in values if value >= 1.0),
            "scored_cases": len(values),
            "answered": answered,
            "answered_rate": round(answered / len(values), 4),
        },
    )


# WHY bound at module bottom: the scored path lives in the spine; the hooks and the
# failure-message wording stay board-owned so per-case output is byte-identical to the
# pre-fold copy (the medxpert unit suite pins every rung — no golden exists yet).
_PATH = ScoredPath(
    reader=RowReader(
        benchmark_label="MedXpertQA",
        error_type=AggregateError,
        decode_case_evaluation=_decode,
    ),
    grade_case=_grade_case,
    failure_messages=_FAILURE_MESSAGES,
    method="exact_match",
    grading_failure_code="medxpert_grading_failed",
    grading_failure_message="the MedXpertQA checker could not grade this Case",
    missing_material_code="missing_answer_asset",
)

__all__ = ["AggregateError", "aggregate", "load_answer", "selected_cases"]
