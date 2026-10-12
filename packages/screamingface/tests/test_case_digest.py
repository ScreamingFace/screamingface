"""The case digest of a run is stable, order-free and sensitive to each case (E14 B5, Q29, §7).

FEATURE: OME-1307 — the SDK digests a run's graded Cases; the board stores the digest at submit and
a replay must match it, so the same headline score over other Cases is not an exact replay.
STORY: as a reader of a board score, I can trust that a replay answered the same Cases the score
was made from, because the digest changes when one Case's id, status or grade changes.
"""

from __future__ import annotations

import hashlib

import screamingface as sf
from screamingface._case_digest import case_digest


def _case(case_id: int | str, score: float | None) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output=f"Answer {case_id}",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=score, metrics={}, checks=()),
        # A Case with no numeric grade is `failed`, and a failed Case carries a failure.
        failures=()
        if score is not None
        else (
            sf.Failure(stage="grading", code="grading_failed", message="fixture", case_id=case_id),
        ),
        metadata={},
    )


def test_case_digest_is_stable_and_order_independent() -> None:
    cases = (_case(1, 1.0), _case(2, None))

    # The entries are `[case_id, status, score]` as compact JSON, sorted, joined by a newline.
    expected = hashlib.sha256(b'[1,"scored",1.0]\n[2,"failed",null]').hexdigest()
    assert case_digest(cases) == expected
    assert case_digest(tuple(reversed(cases))) == expected


def test_case_digest_changes_when_one_grade_or_status_changes() -> None:
    base = case_digest((_case(1, 1.0), _case(2, 0.0)))

    assert case_digest((_case(1, 1.0), _case(2, 1.0))) != base
    assert case_digest((_case(1, 1.0), _case(2, None))) != base


def test_case_digest_int_and_str_ids_differ() -> None:
    assert case_digest((_case(1, 1.0),)) != case_digest((_case("1", 1.0),))
