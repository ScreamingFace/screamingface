"""The scoring view of one Case: the facts a Benchmark scorer reads, and nothing else.

FEATURE memory fix 3 (OME-1835), unit 2. Moved from activity/progress.py, so the result builder
(benchmarks/result_builder.py) and the live progress share one projection per Case. Two changes:
- a non-None ``attempts`` becomes ``[]``. Scorers only test ``attempts is not None``
  (single_shot._check_scores_agree), so the Attempts' text, grades and operations are not kept.
- a projection is returned unchanged (the same object).
INVARIANT (score identity): for every Benchmark scorer, scorer(cases) == scorer(projections);
tests/unit/test_scoring_projection_parity.py pins it.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.contract import CaseGrade, CaseResult, Check, Evidence

NOT_RETAINED = "[not retained]"


def scoring_projection(result: CaseResult) -> CaseResult:
    """Retain scorer facts; discard prompt/answer, diagnostic text and accounting.

    Native scorers inspect grade metrics, check outcomes and (IFEval) evidence
    mode/outcome. Those facts remain intact; this copy never becomes a Report case.
    """

    if _is_projection(result):
        return result
    return result.model_copy(
        update={
            "input": NOT_RETAINED,
            "output": None,
            "refusal": None,
            "operations": None,
            "metadata": {},
            "attempts": None if result.attempts is None else [],
            "grade": None if result.grade is None else _projected_grade(result.grade),
            "failures": [
                failure.model_copy(update={"message": "", "metadata": {}})
                for failure in result.failures
            ],
        }
    )


def _projected_grade(grade: CaseGrade) -> CaseGrade:
    return grade.model_copy(update={"checks": [_projected_check(c) for c in grade.checks]})


def _projected_check(check: Check) -> Check:
    return check.model_copy(
        update={
            "label": "",
            "metadata": {},
            "evidence": [_projected_evidence(evidence) for evidence in check.evidence],
        }
    )


def _projected_evidence(evidence: Evidence) -> Evidence:
    return evidence.model_copy(
        update={
            "raw_output": None,
            "explanation": None,
            "accounting": None,
            "metadata": {k: v for k, v in evidence.metadata.items() if k == "mode"},
        }
    )


def _is_projection(result: CaseResult) -> bool:
    """True when projecting result would change nothing.

    It is already a scoring view (a fixed point), so returning it is value-correct.
    """

    return (
        result.input == NOT_RETAINED
        and result.output is None
        and result.refusal is None
        and result.operations is None
        and not result.metadata
        and not result.attempts
        and all(not failure.message and not failure.metadata for failure in result.failures)
        and (result.grade is None or all(_is_projected_check(c) for c in result.grade.checks))
    )


def _is_projected_check(check: Check) -> bool:
    return (
        not check.label
        and not check.metadata
        and all(
            evidence.raw_output is None
            and evidence.explanation is None
            and evidence.accounting is None
            and set(evidence.metadata) <= {"mode"}
            for evidence in check.evidence
        )
    )


__all__ = ["NOT_RETAINED", "scoring_projection"]
