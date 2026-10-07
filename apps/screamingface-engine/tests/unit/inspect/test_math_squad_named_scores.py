# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""MATH and SQuAD, the first Benchmarks with Named Scores (OME-1268, PR 5 of 5).

FEATURE: SQuAD reports the paper's EM / F1 pair from one run (F1 the Headline Score);
MATH reports the paper's normalised exact match (headline) beside Minerva's symbolic
equivalence, with the self-grading `expression_equivalance` dropped by name.

INVARIANT (spec §8.2, conservation): for each row, every declared scorer's per-Case value
equals inspect's OWN scorer's value on the same answer and target. Three hand-written
Cases per row; no network, no model. The rows' Revisions are frozen in
test_published_revisions.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ChatMessageUser, ModelOutput  # noqa: E402
from inspect_ai.scorer import Score, Target, exact, f1  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.math.math import (  # noqa: E402
    expression_exact_match,
    expression_exact_match_sympy,
)

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    CaseGradeOutcome,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402

# (question, answer, target) — the stand-in Candidate's answers are hand-written to hit
# three outcomes per row: both scorers agree it is right, they disagree, both say wrong.
_SQUAD_CASES: list[tuple[str, str, list[str] | str]] = [
    ("Context: …\nQuestion: When was it built?", "1889", ["1889", "in 1889"]),
    ("Context: …\nQuestion: Who designed it?", "Gustave Eiffel's company did", ["Gustave Eiffel"]),
    ("Context: …\nQuestion: Is it in Rome?", "Rome", "unanswerable"),
]
_MATH_CASES: list[tuple[str, str, str]] = [
    ("What is 6 times 7?", "Six sevens.\nANSWER: 42", "42"),
    ("Simplify 2/4.", "Half.\nANSWER: 2/4", "\\frac{1}{2}"),
    ("What is 6 times 7?", "ANSWER: 41", "42"),
]


def _request(case_id: int, question: str, answer: str, target: Any) -> GradeRequest:
    return GradeRequest(
        case_id=case_id,
        input=TextPayload(text=question),
        answer=TextPayload(text=answer),
        row={"case": {"status": "answered"}},
        material={"target": target},
    )


async def _inspects_own(scorer: Any, question: str, answer: str, target: Any) -> float:
    """The value inspect's own scorer gives the same answer — the conservation oracle."""

    state = TaskState(
        model="screamingface/candidate",  # type: ignore[arg-type]
        sample_id=1,
        epoch=1,
        input=question,
        messages=[ChatMessageUser(content=question)],
        output=ModelOutput.from_content(model="screamingface/candidate", content=answer),
    )
    score: Score = await scorer(state, Target(target))
    value: Any = score.value
    letters: dict[str, float] = {"C": 1.0, "I": 0.0}
    return letters[value] if isinstance(value, str) else float(value)


@pytest.mark.asyncio
async def test_squad_named_scores_match_inspect_on_three_cases() -> None:
    hook = imported_benchmark("squad").aggregation().grade_case
    for case_id, (question, answer, target) in enumerate(_SQUAD_CASES, start=1):
        outcome: CaseGradeOutcome = await hook(_request(case_id, question, answer, target))
        assert outcome.failure_code is None, outcome.checks
        expected_f1 = await _inspects_own(f1(), question, answer, target)
        expected_exact = await _inspects_own(exact(), question, answer, target)
        assert outcome.scores == {"f1": expected_f1, "exact": expected_exact}
        assert outcome.score == expected_f1
    # The three Cases really hit three outcomes (the oracle is not trivially all-zero).
    firsts = [await _inspects_own(f1(), q, a, t) for q, a, t in _SQUAD_CASES]
    assert firsts[0] == 1.0 and 0.0 < firsts[1] < 1.0 and firsts[2] == 0.0


@pytest.mark.asyncio
async def test_math_named_scores_match_inspect_on_three_cases() -> None:
    hook = imported_benchmark("math").aggregation().grade_case
    for case_id, (question, answer, target) in enumerate(_MATH_CASES, start=1):
        outcome: CaseGradeOutcome = await hook(_request(case_id, question, answer, target))
        assert outcome.failure_code is None, outcome.checks
        expected_exact = await _inspects_own(expression_exact_match(), question, answer, target)
        expected_sympy = await _inspects_own(
            expression_exact_match_sympy(), question, answer, target
        )
        assert outcome.scores == {
            "expression_exact_match": expected_exact,
            "expression_exact_match_sympy": expected_sympy,
        }
        assert outcome.score == expected_exact
    # 2/4 against \frac{1}{2}: sympy sees the equivalence, exact match does not.
    assert await _inspects_own(expression_exact_match_sympy(), *_MATH_CASES[1]) == 1.0
    assert await _inspects_own(expression_exact_match(), *_MATH_CASES[1]) == 0.0


def test_math_drops_expression_equivalance_by_name() -> None:
    row = next(spec for spec in BENCHMARKS if spec.key == "math")

    assert row.dropped_scorers == ("expression_equivalance",)
    assert row.named_scores == ("expression_exact_match", "expression_exact_match_sympy")
    assert "expression_equivalance" in row.description
    assert "temperature" in row.description


def test_squad_declares_f1_as_the_headline_with_exact_beside_it() -> None:
    row = next(spec for spec in BENCHMARKS if spec.key == "squad")

    assert row.scorer == "inspect_ai.scorer:f1"
    assert row.extra_scorers == ("inspect_ai.scorer:exact",)
    assert row.named_scores == ("f1", "exact")
    assert row.dropped_scorers == ()


def test_the_rows_assemble_with_their_declared_named_scores() -> None:
    assert imported_benchmark("squad").named_scores == ("f1", "exact")
    assert imported_benchmark("math").named_scores == (
        "expression_exact_match",
        "expression_exact_match_sympy",
    )
    assert imported_benchmark("squad").benchmark.case_count == 11873
    assert imported_benchmark("math").benchmark.case_count == 5000
