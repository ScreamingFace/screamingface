# pyright: reportMissingImports=false
# WHY file-level: the scorers import inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""MATH's ANSWER: line read through its wrapping: inspect_evals PRs #2199 and #2340, plus bold.

What these tests pin, and why:

- a right answer boxed, wrapped in \\( \\) or \\[ \\], or in markdown bold on the ANSWER: line is
  right under both of our scorers;
- the TRIPWIRES: v0.20.0's exact match still marks each of those wrong; when a pin bump makes
  one of those asserts fail, inspect_evals has that fix and its step of the Named Deviation
  can go (https://github.com/UKGovernmentBEIS/inspect_evals/pull/2199,
  https://github.com/UKGovernmentBEIS/inspect_evals/pull/2340);
- a wrong answer stays wrong through the same wrapping, and a box off the ANSWER: line is
  still not read;
- the row grades with these scorers, keeps its Named Score names, and pins antlr4 beside sympy.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

from importlib.metadata import version

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.math.math import expression_exact_match as inspect_evals_exact  # noqa: E402

from screamingface_engine_inspect.benchmarks import (  # noqa: E402
    BENCHMARKS,
    _scorer_dependency_pins,
    imported_benchmark,
)
from screamingface_engine_inspect.named_deviations.math.math import (  # noqa: E402
    expression_exact_match,
    expression_exact_match_sympy,
    extract_answer,
)

#: (reply, key): a right answer in each wrapping v0.20.0's exact match scores 0.
_WRAPPED_RIGHT: list[tuple[str, str]] = [
    # inspect_evals PR #2199: a box on the ANSWER: line.
    ("6 times 7.\nANSWER: \\boxed{42}", "42"),
    ("Half.\nANSWER: $\\boxed{\\frac{1}{2}}$", "\\frac{1}{2}"),
    # inspect_evals PR #2340 (issue #2220): paired outer LaTeX delimiters.
    ("Half.\nANSWER: \\(\\frac{1}{2}\\)", "\\frac{1}{2}"),
    ("Half.\nANSWER: \\[\\frac{1}{2}\\]", "\\frac{1}{2}"),
    ("So x is five.\nANSWER: \\[x = 5\\]", "5"),
    # Ours: markdown bold, which v0.20.0 copies as `42**`.
    ("6 times 7.\n**ANSWER: 42**", "42"),
    ("6 times 7.\n**ANSWER:** 42", "42"),
]


async def _graded(scorer: Scorer, reply: str, key: str) -> object:
    """The grade one scorer gives one reply against one key."""

    state = TaskState(
        model="none/none",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[],
        output=ModelOutput.from_content(model="none/none", content=reply),
    )
    score: Score | None = await scorer(state, Target(key))
    assert score is not None
    return score.value


@pytest.mark.asyncio
@pytest.mark.parametrize(("reply", "key"), _WRAPPED_RIGHT)
async def test_tripwire_a_wrapped_right_answer_inspect_evals_fails_is_right_under_ours(
    reply: str, key: str
) -> None:
    """TRIPWIRE: the first assert is v0.20.0's exact-match verdict."""

    assert await _graded(inspect_evals_exact(), reply, key) == INCORRECT
    assert await _graded(expression_exact_match(), reply, key) == CORRECT
    assert await _graded(expression_exact_match_sympy(), reply, key) == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        "ANSWER: \\boxed{41}",
        "**ANSWER: \\(41\\)**",
        # No ANSWER: line: a box elsewhere is never read, as in v0.20.0.
        "The product is \\boxed{42}.",
    ],
)
async def test_a_wrong_or_unmarked_answer_stays_wrong(reply: str) -> None:
    assert await _graded(expression_exact_match(), reply, "42") == INCORRECT
    assert await _graded(expression_exact_match_sympy(), reply, "42") == INCORRECT


@pytest.mark.parametrize(
    ("reply", "copied"),
    [
        ("ANSWER: 42", "42"),
        ("ANSWER: 1\nANSWER: \\[\\boxed{2}\\]", "2"),
        ("ANSWER: \\fbox{3}", "\\fbox{3}"),
        ("no answer line", ""),
    ],
)
def test_the_answer_is_copied_off_the_last_answer_line(reply: str, copied: str) -> None:
    """Delimiters come off before the box is unwrapped; an `\\fbox{}` (which the eval's
    `remove_boxed` cannot unwrap) keeps the line as written."""

    assert extract_answer(reply) == copied


def test_the_row_grades_with_these_scorers_under_the_evals_names() -> None:
    """INVARIANT: the Named Scores are the scorers' registry names, so ours keep the eval's."""

    row = next(spec for spec in BENCHMARKS if spec.key == "math")

    assert row.scorer.endswith("named_deviations.math.math:expression_exact_match")
    assert row.extra_scorers == (
        "screamingface_engine_inspect.named_deviations.math.math:expression_exact_match_sympy",
    )
    assert imported_benchmark("math").named_scores == (
        "expression_exact_match",
        "expression_exact_match_sympy",
    )


def test_the_latex_parser_sympy_grades_with_is_pinned_beside_it() -> None:
    """parse_latex runs on antlr4: a bump of either changes symbolic verdicts, so both are
    Benchmark identity."""

    row = next(spec for spec in BENCHMARKS if spec.key == "math")

    assert _scorer_dependency_pins(row) == (
        f"sympy=={version('sympy')}",
        f"antlr4-python3-runtime=={version('antlr4-python3-runtime')}",
    )
