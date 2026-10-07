"""MuSiQue-Ans's grading hooks — the per-Case grade and the run's three column means.

The shared grading code owns the marking room (``shared_grading/benchmark_aggregation.py``); this
module is the Benchmark's contribution: its ``grade_case`` (the paper's scorer applied to what
the reply committed), its scorer (a plain mean per Named Score), and its own failure wording.

INVARIANT — three Named Scores per Case, the paper's two plus exact match (spec D9):

    f1          answer token F1, best over `[answer] + answer_aliases`   (the paper's An; headline)
    exact       answer exact match, 0 or 1                              (SQuAD's EM)
    support_f1  set F1 of the cited paragraph numbers vs the gold ones  (the paper's Sp)

The headline column IS the Case score, and every run-level column is a mean over the SAME graded
Cases, so all three share Coverage's denominator.

INVARIANT — a failure to COMMIT and a failure to RUN are different facts. A reply without the
two lines has been measured (it is graded, and flagged in the grade's metrics). A Case whose
Candidate call errored has NOT been measured (score ``None``, a visible failed Case, outside
every mean).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import CandidateScore, SelectedCase
from screamingface_engine.benchmarks.contract import CaseGrade, CaseResult
from screamingface_engine.benchmarks.musique.case_grade import decode_case_grade
from screamingface_engine.benchmarks.musique.grading import (
    AnswerScore,
    score_answer,
    score_support,
)
from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    BenchmarkAggregation,
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.case_grades import (
    CaseGradeReader,
    read_selected_cases,
)
from screamingface_engine.benchmarks.shared_grading.incremental import Scoring

#: The Named Scores, headline first (spec D9). `f1`/`exact` match SQuAD's names.
NAMED_SCORES: tuple[str, ...] = ("f1", "exact", "support_f1")
_HEADLINE: str = NAMED_SCORES[0]

#: The grade's two format flags (spec D7), published per Case and as rates per run.
_FLAGS: tuple[str, ...] = ("answer_line_found", "support_line_found")

#: The Case result metadata copied from the private answer record (spec D12). Never the whole
#: record: `answer`, `answer_aliases` and `supporting_idx` are the answer key.
_METADATA_FIELDS: tuple[str, ...] = ("musique_id", "hop_type")

#: Every Report number is rounded to this many places, as the shared grade does.
_PLACES = 4

#: A check is MET only at full marks: the reply matched exactly / cited exactly the gold set.
_FULL_MARKS = 1.0

# INVARIANT: failure wording is this Benchmark's published voice — no rubric-flavored code
# ("missing_rubric_asset") may leak into a result whose Grading Material is an answer key.
_FAILURE_MESSAGES = {
    "missing_answer_asset": "the prepared answer record for this Case is missing or invalid",
    "missing_case_row": "no evaluation row for this Case reached the aggregate",
    "case_error": "the Case pipeline collected an error instead of an evaluation",
}


class AggregateError(ValueError):
    """The reducer's input is unusable — raised before any scoring."""


def load_answer(root: Path, case_id: int) -> dict[str, Any] | None:
    """Read one Case's private answer record; ``None`` when the scorer could not use it."""

    try:
        decoded: object = json.loads(
            (root / "answers" / f"{case_id}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, Mapping) or not _usable_answer(decoded):
        return None
    return dict(decoded)


def _usable_answer(record: Mapping[str, Any]) -> bool:
    """True when the record holds the gold the official scorer needs, typed as it needs it."""

    if not isinstance(record.get("answer"), str):
        return False
    aliases: object = record.get("answer_aliases")
    supporting: object = record.get("supporting_idx")
    return (
        isinstance(aliases, list)
        and all(isinstance(alias, str) for alias in aliases)
        and isinstance(supporting, list)
        # WHY `type(n) is int`: a JSON `true` is an int to Python, and would be paragraph 1.
        and all(type(number) is int for number in supporting)
    )


def selected_cases(root: Path, case_ids: tuple[int, ...]) -> list[SelectedCase]:
    """The roll call from the prepared ``cases.json``, in selected order."""

    return read_selected_cases(
        root, case_ids, benchmark_label="MuSiQue-Ans", error_type=AggregateError
    )


def aggregate(
    raw_case_grades: str,
    root: Path,
    *,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Grade every selected Case and score the run — the aggregate route's reducer."""

    return scoring(
        root, benchmark_id=benchmark_id, benchmark_revision=benchmark_revision, case_ids=case_ids
    ).aggregate(raw_case_grades)


def scoring(
    root: Path,
    *,
    benchmark_id: str,
    benchmark_revision: str,
    case_ids: tuple[int, ...],
) -> Scoring:
    """Score every selected Case on the shared scored path, then the three column means."""

    # WHY one read per Case: the answer record is both the Grading Material and the source of
    # the public Case metadata — load once, use twice (MedXpert's pattern).
    answers: dict[int, dict[str, Any] | None] = {
        case_id: load_answer(root, case_id) for case_id in case_ids
    }
    return Scoring(
        path=_PATH,
        benchmark_id=benchmark_id,
        revision=benchmark_revision,
        selected=selected_cases(root, case_ids),
        material=lambda case_id: answers.get(case_id),
        scorer=_column_means,
        metadata=lambda case_id: _case_metadata(answers.get(case_id)),
    )


def _case_metadata(answer: Mapping[str, Any] | None) -> dict[str, Any]:
    """The dataset's own id and hop type for this Case's Report row, and nothing else."""

    if answer is None:
        return {}
    return {
        field: answer[field] for field in _METADATA_FIELDS if isinstance(answer.get(field), str)
    }


def _decode(grading: object, expected_case_id: int) -> dict[str, Any]:
    """Validate the envelope, then hoist attempt 1 into the shared candidate shape."""

    envelope: dict[str, Any] = decode_case_grade(grading, expected_case_id)
    attempt: Mapping[str, Any] = envelope["attempts"][0]
    return {
        "case": {
            "status": attempt.get("status"),
            "output": attempt.get("output"),
            "finish_reason": attempt.get("finish_reason"),
            "refusal": attempt.get("refusal"),
            "execution": attempt.get("execution"),
            "operations": attempt.get("operations"),
            # WHY empty: this Benchmark's Case metadata comes from the private answer record
            # (`Scoring(metadata=...)`), never from the reply.
            "metadata": {},
        },
        "attempt": dict(attempt),
    }


async def _grade_case(request: GradeRequest) -> CaseGradeOutcome:
    """Grade one reply's two committed lines against the answer key, with the paper's scorer.

    Mental model: the marker reads the two boxed lines off the script (already read at check
    time) and holds them against the answer key — the answer box against the gold answer and its
    accepted spellings, the paragraph box against the gold paragraph numbers. The scoring itself
    is the paper's copied code; this hook only feeds it and labels the three numbers.

    Stages, in execution order:

    1. **Read.** The committed answer, the cited numbers and the two flags from the check record;
       the gold answer, aliases and supporting numbers from the private answer record.
    2. **Answer.** ``score_answer`` → token F1 and exact match, best over answer + aliases.
    3. **Support.** ``score_support`` → set F1 of cited vs gold numbers (empty vs non-empty: 0).
    4. **Label.** ``f1`` is the Case score and the headline; ``exact`` and ``support_f1`` ride
       beside it; the two flags go to metrics; one check per committed line.

    Worked example — Case ``2hop__460946_294723``, gold ``Miquette Giraudy`` and {5, 10}; the
    reply ended ``Supporting paragraphs: 10`` / ``**Answer:** Giraudy`` (spec reply table, row 2):

    - Stage 1: answer ``** Giraudy``, support {10}, both flags True;
    - Stage 2: normalised ``giraudy`` vs ``miquette giraudy`` — precision 1/1, recall 1/2,
      f1 = 2·1·0.5 / 1.5 = 0.667; exact 0;
    - Stage 3: cited {10} vs gold {5, 10} — precision 1/1, recall 1/2, support_f1 0.667;
    - Stage 4: score 0.667; scores ``{f1: 0.667, exact: 0.0, support_f1: 0.667}``.

    Args:
        request: the shared grading request; ``row["attempt"]`` is the decoded check record and
            ``material`` the Case's answer record (``load_answer``; the ladder has already
            refused an unusable one).

    Returns:
        A graded outcome: score = answer F1, the three Named Scores headline first, the two
        format flags as metrics, and two checks (answer line, support line).
    """

    # Stage 1 — read the committed lines and the answer key.
    attempt: Mapping[str, Any] = request.row["attempt"]
    material: object = request.material
    assert isinstance(material, Mapping)  # the ladder already rejected unusable material
    committed_answer: str = str(attempt["answer"])
    cited: list[int] = list(attempt["support"])
    gold_support: list[int] = list(material["supporting_idx"])
    # Stage 2 — the answer: token F1 and exact match, best over the answer and its aliases.
    answer: AnswerScore = score_answer(
        committed_answer, str(material["answer"]), list(material["answer_aliases"])
    )
    # Stage 3 — the support: set F1 of the cited numbers against the gold ones.
    support_f1: float = score_support(cited, gold_support)
    # Stage 4 — label the three numbers, headline first; flags to metrics.
    scores: dict[str, float | None] = {
        "f1": answer.f1,
        "exact": float(answer.exact),
        "support_f1": support_f1,
    }
    return CaseGradeOutcome(
        score=answer.f1,
        scores=scores,
        metrics={
            "answer_line_found": bool(attempt["answer_line"]),
            "support_line_found": bool(attempt["support_line"]),
        },
        checks=[
            _check(
                "answer",
                "the committed answer matches the gold answer or an accepted alias (token F1)",
                answer.f1,
                met=answer.exact == 1,
                metadata={
                    "committed": committed_answer,
                    "line_found": bool(attempt["answer_line"]),
                    "exact": answer.exact,
                    "gold_answer_count": 1 + len(material["answer_aliases"]),
                },
            ),
            _check(
                "support",
                "the cited paragraphs are the gold supporting paragraphs (set F1)",
                support_f1,
                met=support_f1 >= _FULL_MARKS,
                metadata={
                    "cited": sorted(cited),
                    "line_found": bool(attempt["support_line"]),
                    "gold_support_count": len(gold_support),
                },
            ),
        ],
    )


def _check(
    check_id: str, label: str, value: float, *, met: bool, metadata: dict[str, Any]
) -> dict[str, Any]:
    """One committed line's verdict as the report schema's Check, with its Evidence record.

    WHY counts and not the gold itself in ``metadata``: the Report is published, and the
    answer key's place is the private Grading Material.
    """

    return {
        "type": "musique_official_scorer",
        "id": check_id,
        "label": label,
        "outcome": "MET" if met else "UNMET",
        "score": round(value, _PLACES),
        "evidence": [
            {
                "sequence": 1,
                "producer": {"type": "deterministic", "id": f"musique/{check_id}"},
                "valid": True,
                "outcome": "PASS" if met else "FAIL",
                # WHY the number: this producer is the official scorer, so its OUTPUT is the
                # value it computed. The reply is already on the Case as `output`.
                "raw_output": value,
                "metadata": metadata,
                "accounting": None,
            }
        ],
        "metadata": {},
    }


def _column_means(cases: Sequence[CaseResult]) -> CandidateScore:
    """Each Named Score's mean over the graded Cases, headline first — the run's three numbers.

    Mental model: the gradebook's three columns, each averaged down. Only Cases that were
    graded count, and every column averages over exactly those Cases, so f1, exact and
    support_f1 share one denominator with Coverage (the inspect `_column_means` precedent).
    The official script averages the same per-Case values; it rounds to 3 places for display,
    and the Report rounds to 4.

    Worked example, 2 graded Cases — Case 1 (f1 1.0, exact 1, support_f1 1.0) and Case 2
    replying `Denver, CO` and citing {0, 7} against gold `Denver` and {0, 7, 9} (f1 0.6667,
    exact 0, support_f1 0.8): scores f1 0.8333 · exact 0.5 · support_f1 0.9; score 0.8333.

    INVARIANT: reads only `grade.score`, `grade.scores` and `grade.metrics`, which the live-score
    projection keeps (``activity/progress.py``), so an early score equals the final one. The
    run score is the mean of the Case scores, which ARE the f1 column, so the two agree.

    Args:
        cases: the finalizer's gradeable Cases (each has a grade with a numeric score).

    Returns:
        The run score (the f1 mean), the three column means, the count of graded Cases and the
        share of them that committed each line.
    """

    graded: list[CaseGrade] = [
        case.grade for case in cases if case.grade is not None and case.grade.score is not None
    ]
    score: float | None = _mean([float(grade.score or 0.0) for grade in graded])
    assert score is not None  # the finalizer never calls a scorer with no graded Case
    means: dict[str, float | None] = {
        name: _column_mean([grade.scores.get(name) for grade in graded]) for name in NAMED_SCORES
    }
    rates: dict[str, float | None] = {
        f"{flag}_rate": _mean([float(bool(grade.metrics.get(flag))) for grade in graded])
        for flag in _FLAGS
    }
    return CandidateScore(
        score=score,
        metrics={"scored_cases": len(graded), **rates},
        scores=means,
    )


def _column_mean(column: Sequence[float | None]) -> float | None:
    """One Named Score's mean, or ``None`` when any graded Case left it unknown.

    INVARIANT: every column shares the headline's denominator. A column one graded Case could
    not fill has no honest mean over those Cases, so it is published as unknown — never as a
    mean over fewer Cases, never as 0.0.
    """

    filled: list[float] = [float(value) for value in column if value is not None]
    return _mean(filled) if len(filled) == len(column) else None


def _mean(values: Sequence[float]) -> float | None:
    """The rounded mean of ``values``; ``None`` for no values."""

    return round(sum(values) / len(values), _PLACES) if values else None


# WHY bound at module bottom: the scored path lives in the shared grading code; the hooks and the
# failure wording stay Benchmark-owned, so per-Case output keeps this Benchmark's voice.
_PATH = BenchmarkAggregation(
    reader=CaseGradeReader(
        benchmark_label="MuSiQue-Ans",
        error_type=AggregateError,
        decode_case_grade=_decode,
    ),
    grade_case=_grade_case,
    failure_messages=_FAILURE_MESSAGES,
    method="deterministic",
    grading_failure_code="musique_grading_failed",
    grading_failure_message="the MuSiQue-Ans grader could not grade this Case",
    missing_material_code="missing_answer_asset",
    named_scores=NAMED_SCORES,
)

__all__ = [
    "NAMED_SCORES",
    "AggregateError",
    "aggregate",
    "load_answer",
    "scoring",
    "selected_cases",
]
