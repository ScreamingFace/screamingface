"""The shared rubric ``grade_case`` — marking one script against a graded checklist.

Imagine you're a TA grading 100 essay answers. You can't just eyeball them — you have a
rubric: a checklist where each item has points.

+5  "mentions the correct drug"
+3  "explains the mechanism"
-3  "invents a dosage"        ← negative = a good answer NEVER does this

The judging already happened before code in this module runs.
An LLM judge already read the answer and, for each checklist item, said "hit" or "miss."
Those decisions (verdicts) are sitting inside the data row. This function's job is
to take the verdicts, check they're complete, and turn them into a number.
This factory builds the ``grade_case`` hook both rubric boards share; the board supplies
only its official per-Case scoring formula and its judge's producer id.

The 4 stages (one answer being graded)
1. Read the verdicts off the row. One per rubric item. Count any garbage replies (judge
    answered nonsense).
2. Copy out the audit trail. Keep the judge's exact wording per check — so a human can
    later ask "why did Case 7 lose points?"
3. Completeness gate. Did the judge rule on every item, with zero invalid replies? If
    not — stop, don't score.
4. Score, or fail loudly. Complete → apply the board's formula. Incomplete → the
    Case fails as incomplete_verdicts. Complete but the rubric has no positive points to
    earn → no_positive_points (the asset itself is broken).

INVARIANT: a missing or invalid verdict is never defaulted. A rubric penalty (say -3,
"invents a dosage") only subtracts when the judge says "hit"; defaulting a failed judge
call to "not hit" would erase the penalty and inflate the Case.

INVARIANT: one check per rubric_id, last entry wins — the same dict-assignment dedup
for verdicts and checks, so a duplicate judge entry (retry noise) never becomes a
second check and met can never exceed judged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from screamingface_engine.benchmarks.spine.scored import (
    CaseGradeOutcome,
    GradeCase,
    GradeRequest,
)

#: The board's official per-Case scoring formula: ``(points, verdicts) -> score``,
#: ``None`` for a fully judged Case with nothing worth points.
type CaseScore = Callable[[Sequence[int], Mapping[int, bool]], float | None]


def rubric_grade_case(*, case_score: CaseScore, judge_producer_id: str) -> GradeCase:
    """Build one board's rubric hook from its formula and its judge's identity.

    Args:
        case_score: the board's per-Case scoring math — deliberately NOT shared
            (each board's formula answers to its own reference; see the boards'
            ``scoring`` modules).
        judge_producer_id: the producer stamped on evidence whose judge reply had
            no usable producer ("gdpval/judge", "healthbench/judge") — even a
            malformed reply has a known Benchmark-owned producer.
    """

    async def grade(request: GradeRequest) -> CaseGradeOutcome:
        material = request.material
        assert isinstance(material, Sequence) and not isinstance(material, (str, bytes))
        points: list[int] = [int(value) for value in material]
        evaluations: object = request.row.get("rubric_evaluations")
        # Stage 1-2 — the judge's work, read and projected.
        verdicts, invalid = _verdicts(evaluations)
        checks: list[dict[str, Any]] = _checks(evaluations, points, judge_producer_id)
        metrics: dict[str, int] = {
            "judged": len(verdicts),
            "expected": len(points),
            "invalid_replies": invalid,
        }
        # Stage 3-4 — the completeness gate, then the board's formula.
        complete: bool = len(verdicts) == len(points) and not invalid
        score: float | None = case_score(points, verdicts) if complete else None
        if score is None:
            # WHY the split: a complete-but-unscorable Case means the baked asset
            # lost its guaranteed positive-points item — a baked-asset defect, not
            # judge loss; the two must stay distinguishable in the report.
            code: str = "no_positive_points" if complete else "incomplete_verdicts"
            return CaseGradeOutcome(score=None, metrics=metrics, checks=checks, failure_code=code)
        return CaseGradeOutcome(score=score, metrics=metrics, checks=checks)

    return grade


def _verdicts(evaluations: object) -> tuple[dict[int, bool], int]:
    """Stage 1 — verdicts by rubric position, plus how many judge replies were unusable."""

    verdicts: dict[int, bool] = {}
    invalid = 0
    if not isinstance(evaluations, list):
        return verdicts, invalid
    for evaluation in evaluations:
        if not isinstance(evaluation, Mapping):
            invalid += 1
            continue
        evidence: object = evaluation.get("evidence")
        if not isinstance(evidence, Mapping) or evidence.get("valid") is not True:
            invalid += 1
            continue
        rubric_id: object = evidence.get("rubric_id")
        criteria_met: object = evidence.get("criteria_met")
        if (
            isinstance(rubric_id, int)
            and not isinstance(rubric_id, bool)
            and (criteria_met is True or criteria_met is False)
        ):
            verdicts[rubric_id] = criteria_met
        else:
            invalid += 1
    return verdicts, invalid


def _checks(evaluations: object, points: list[int], judge_producer_id: str) -> list[dict[str, Any]]:
    """Stage 2 — project the judge's evaluations into the SDK's check/evidence rows."""

    if not isinstance(evaluations, list):
        return []
    checks: dict[int, dict[str, Any]] = {}
    for evaluation in evaluations:
        if not isinstance(evaluation, Mapping):
            continue
        rubric: object = evaluation.get("rubric")
        evidence: object = evaluation.get("evidence")
        rubric_id: object = evaluation.get("rubric_id")
        if (
            not isinstance(rubric, Mapping)
            or not isinstance(evidence, Mapping)
            or isinstance(rubric_id, bool)
            or not isinstance(rubric_id, int)
        ):
            continue
        check: dict[str, Any] = {
            "type": "rubric_item",
            "id": str(rubric_id),
            "label": str(rubric.get("rubric_item", "")),
            "evidence": [_evidence(evidence, judge_producer_id)],
        }
        # Check-level verdict in the report schema's vocabulary — the judge decides
        # it. Without a top-level outcome the SDK renders the check as unjudged
        # (ifeval precedent), so it is emitted whenever the judge reply was valid;
        # an invalid reply leaves the check outcome-less on purpose.
        if evidence.get("valid") is True:
            check["outcome"] = "MET" if evidence.get("criteria_met") is True else "UNMET"
        checks[rubric_id] = {
            **check,
            "metadata": (
                {"points": points[rubric_id - 1]} if 1 <= rubric_id <= len(points) else {}
            ),
        }
    return list(checks.values())


def _evidence(record: Mapping[str, Any], judge_producer_id: str) -> dict[str, Any]:
    """Turn one raw judge reply into the audit-trail record a human reads later — its
    verdict and explanation if the reply was valid, the rejection reason if it wasn't.
    """

    valid: bool = record.get("valid") is True
    value: dict[str, Any] = {
        # One judge pass per rubric item (the reference grades each item once),
        # so the sequence is always 1.
        "sequence": 1,
        "producer": {
            "type": str(record.get("producer_type", "model")),
            # Even a malformed Judge reply has a known Benchmark-owned producer.
            "id": str(record.get("producer_id") or judge_producer_id),
        },
        "valid": valid,
        "raw_output": str(record.get("raw_output", "")),
        "metadata": {},
        "accounting": record.get("accounting"),
    }
    if valid:
        value["outcome"] = "MET" if record.get("criteria_met") is True else "UNMET"
        value["explanation"] = str(record.get("explanation", ""))
    else:
        value["metadata"] = {"rejection_reason": str(record.get("reason", "invalid"))}
    return value


__all__ = ["CaseScore", "rubric_grade_case"]
