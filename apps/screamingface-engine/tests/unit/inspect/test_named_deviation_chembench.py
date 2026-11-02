# pyright: reportMissingImports=false
# WHY file-level: the scorer imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""ChemBench multiple choice graded by the set of letters: inspect_evals PR #2591, adopted.

What these tests pin, and why:

- a right multi-letter answer counts however the prompt allows it to be written (commas or
  spaces, any order, any case); a missing or extra letter is wrong;
- the TRIPWIRE: v0.20.0's scorer still marks "A, C", "A C" and "C,A" wrong; when a pin bump
  makes that assert fail, inspect_evals has the fix and the Named Deviation can go
  (https://github.com/UKGovernmentBEIS/inspect_evals/pull/2591);
- single-letter and numeric Cases grade exactly as v0.20.0 grades them, except a repeated
  letter ("B,B" against "B"), which is right as a set, as the ChemBench authors mark it;
- the row grades with this scorer, the PR's own `chembench_scorer` copied verbatim (the
  imported `chembench_scorer` below is v0.20.0's, the tripwire's baseline).

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ModelOutput  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.chembench.chembench import chembench_scorer  # noqa: E402

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.named_deviations.chembench import (  # noqa: E402
    chembench as deviation,
)


async def _scored(scorer: Scorer, reply: str, key: str, task_type: str = "mcq") -> Score:
    """The Score one scorer gives one reply against one key, on a Case of `task_type`."""

    metadata: dict[str, object] = {"task_type": task_type, "subset_name": "organic_chemistry"}
    # The eval's own record_to_sample gives every numeric Case a 1% relative tolerance; without
    # it both scorers would demand an exact number and the numeric rows below would test nothing.
    if task_type == "mae":
        metadata.update(tolerance=0.01, relative=True)
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
    """TRIPWIRE (inspect_evals PR #2591): the first assert is v0.20.0's verdict."""

    reply: str = f"Both rings are aromatic.\n[ANSWER]{letters}[/ANSWER]"

    assert (await _scored(chembench_scorer(), reply, "A,C")).value == INCORRECT
    assert (await _scored(deviation.chembench_scorer(), reply, "A,C")).value == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize("letters", ["B,B", "B B"])
async def test_a_repeated_letter_on_a_one_letter_key_is_right_under_ours_only(letters: str) -> None:
    """The one place a one-letter Case grades differently: as sets "B,B" is {B}, as the
    ChemBench authors mark it; v0.20.0's string compare marked it wrong."""

    reply: str = f"[ANSWER]{letters}[/ANSWER]"

    assert (await _scored(chembench_scorer(), reply, "B")).value == INCORRECT
    assert (await _scored(deviation.chembench_scorer(), reply, "B")).value == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize("letters", ["A", "A,C,E", "A,B"])
async def test_a_missing_or_extra_letter_is_wrong(letters: str) -> None:
    score: Score = await _scored(deviation.chembench_scorer(), f"[ANSWER]{letters}[/ANSWER]", "A,C")

    assert score.value == INCORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "key", "task_type", "expected"),
    [
        ("[ANSWER]B[/ANSWER]", "B", "mcq", CORRECT),
        ("[ANSWER]b.[/ANSWER]", "B", "mcq", CORRECT),
        ("[ANSWER]D[/ANSWER]", "B", "mcq", INCORRECT),
        ("[ANSWER]A,C[/ANSWER]", "A,C", "mcq", CORRECT),
        ("The answer is B.", "B", "mcq", INCORRECT),
        # 1.505 is within 1% of 1.5, 1.6 is not: one right and one wrong numeric reply, so a
        # numeric path that always says wrong (or always right) fails here.
        ("[ANSWER]1.505[/ANSWER]", "1.5", "mae", CORRECT),
        ("[ANSWER]1.6[/ANSWER]", "1.5", "mae", INCORRECT),
    ],
)
async def test_every_other_reply_grades_as_inspect_evals_grades_it(
    reply: str, key: str, task_type: str, expected: str
) -> None:
    """The deviation is the letter compare and nothing else: single letters, a missing tag
    (a format failure) and numbers within 1% grade as v0.20.0 grades them, and the verdict is
    the one written here, so the two scorers cannot agree on a wrong mark."""

    inspect_evals_score: Score = await _scored(chembench_scorer(), reply, key, task_type)
    ours: Score = await _scored(deviation.chembench_scorer(), reply, key, task_type)

    assert (ours.value, ours.reason) == (inspect_evals_score.value, inspect_evals_score.reason)
    assert ours.value == expected


def test_the_row_grades_with_the_copied_scorer_not_inspect_evals_own() -> None:
    row = next(spec for spec in BENCHMARKS if spec.key == "chembench")

    assert (
        row.scorer
        == "screamingface_engine_inspect.named_deviations.chembench.chembench:chembench_scorer"
    )
