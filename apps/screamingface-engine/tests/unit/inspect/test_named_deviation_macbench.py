# pyright: reportMissingImports=false
# WHY file-level: the scorer imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""MaCBench multiple choice graded by the set of letters: chembench's fix (inspect_evals PR
#2591), applied to the sibling eval that shares its regex and its bug.

What these tests pin, and why:

- a right multi-letter answer counts however the prompt allows it to be written (commas or
  spaces, any order, any case); a missing or extra letter is wrong;
- the TRIPWIRE: v0.20.0's `macbench_scorer` still marks "A, C", "A C" and "C,A" wrong against
  "A,C"; when a pin bump makes that assert fail, inspect_evals grades the set and the Named
  Deviation can go (https://github.com/UKGovernmentBEIS/inspect_evals/issues/2586);
- single-letter and numeric Cases grade exactly as v0.20.0 grades them, the dataset's own
  absolute tolerance window and the 1% relative fallback included, except a repeated letter
  ("B,B" against "B"), which is right as a set;
- the row grades with this scorer, not inspect_evals' own.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.macbench.macbench import macbench_scorer  # noqa: E402

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.named_deviations.macbench import (  # noqa: E402
    macbench as deviation,
)


async def _scored(
    scorer: Scorer,
    reply: str,
    key: str,
    task_type: str = "mcq",
    tolerance: float = 0.0,
    relative: bool | None = None,
) -> Score:
    """The Score one scorer gives one reply against one key, on a Case of `task_type`.

    The metadata is the shape the eval's own record_to_sample_MM writes: a multiple-choice
    Case carries tolerance 0.0 and relative None; a numeric Case carries the dataset's
    precomputed absolute window (relative False) or, when the dataset has none, 1% relative.
    """

    metadata: dict[str, object] = {
        "task_type": task_type,
        "subset_name": "afm-image",
        "preferred_score": "single_target_question",
        "tolerance": tolerance,
        "relative": relative,
    }
    state = TaskState(
        model="none/none",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[],
        output=ModelOutput.from_content(model="none/none", content=reply),
        metadata=metadata,
    )
    score: Score | None = await scorer(state, Target(key))
    assert score is not None
    return score


@pytest.mark.asyncio
@pytest.mark.parametrize("letters", ["A, C", "A C", "C,A", "c, a"])
async def test_tripwire_a_right_multi_letter_answer_inspect_evals_fails_is_right_under_ours(
    letters: str,
) -> None:
    """TRIPWIRE (inspect_evals issue #2586, chembench's fix PR #2591 not yet applied to
    macbench): the first assert is v0.20.0's verdict."""

    reply: str = f"Both liquids are alcohols.\n[ANSWER]{letters}[/ANSWER]"

    assert (await _scored(macbench_scorer(), reply, "A,C")).value == INCORRECT
    assert (await _scored(deviation.macbench_scorer(), reply, "A,C")).value == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize("letters", ["B,B", "B B"])
async def test_a_repeated_letter_on_a_one_letter_key_is_right_under_ours_only(letters: str) -> None:
    """The one place a one-letter Case grades differently: as sets "B,B" is {B}; v0.20.0's
    string compare marked it wrong."""

    reply: str = f"[ANSWER]{letters}[/ANSWER]"

    assert (await _scored(macbench_scorer(), reply, "B")).value == INCORRECT
    assert (await _scored(deviation.macbench_scorer(), reply, "B")).value == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize("letters", ["A", "A,C,E", "A,B"])
async def test_a_missing_or_extra_letter_is_wrong(letters: str) -> None:
    score: Score = await _scored(deviation.macbench_scorer(), f"[ANSWER]{letters}[/ANSWER]", "A,C")

    assert score.value == INCORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "key", "task_type", "tolerance", "relative", "expected"),
    [
        ("[ANSWER]B[/ANSWER]", "B", "mcq", 0.0, None, CORRECT),
        ("[ANSWER]b.[/ANSWER]", "B", "mcq", 0.0, None, CORRECT),
        ("[ANSWER]D[/ANSWER]", "B", "mcq", 0.0, None, INCORRECT),
        ("[ANSWER]A,C[/ANSWER]", "A,C", "mcq", 0.0, None, CORRECT),
        ("The answer is B.", "B", "mcq", 0.0, None, INCORRECT),
        # The eval's 1% relative fallback: 1.505 is within 1% of 1.5, 1.6 is not.
        ("[ANSWER]1.505[/ANSWER]", "1.5", "mae", 0.01, True, CORRECT),
        ("[ANSWER]1.6[/ANSWER]", "1.5", "mae", 0.01, True, INCORRECT),
        # The dataset's own precomputed window, read as an absolute tolerance (the eval's
        # README): 7.95 ± 0.3975, so 8.3 is inside and 8.4 is outside.
        ("[ANSWER]8.3[/ANSWER]", "7.95", "mae", 0.3975, False, CORRECT),
        ("[ANSWER]8.4[/ANSWER]", "7.95", "mae", 0.3975, False, INCORRECT),
    ],
)
async def test_every_other_reply_grades_as_inspect_evals_grades_it(
    reply: str,
    key: str,
    task_type: str,
    tolerance: float,
    relative: bool | None,
    expected: str,
) -> None:
    """The deviation is the letter compare and nothing else: single letters, a missing tag
    (a format failure) and numbers inside or outside their window grade as v0.20.0 grades
    them, and the verdict is the one written here, so the two scorers cannot agree on a
    wrong mark."""

    inspect_evals_score: Score = await _scored(
        macbench_scorer(), reply, key, task_type, tolerance, relative
    )
    ours: Score = await _scored(
        deviation.macbench_scorer(), reply, key, task_type, tolerance, relative
    )

    assert (ours.value, ours.reason) == (inspect_evals_score.value, inspect_evals_score.reason)
    assert ours.value == expected


def test_the_row_grades_with_the_copied_scorer_not_inspect_evals_own() -> None:
    row = next(spec for spec in BENCHMARKS if spec.key == "macbench")

    assert (
        row.scorer
        == "screamingface_engine_inspect.named_deviations.macbench.macbench:macbench_scorer"
    )
