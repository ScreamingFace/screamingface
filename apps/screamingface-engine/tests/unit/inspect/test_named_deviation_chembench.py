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
- single-letter and numeric Cases grade exactly as v0.20.0 grades them;
- the row grades with this scorer.

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
from screamingface_engine_inspect.named_deviations.chembench.chembench import (  # noqa: E402
    chembench_letter_set,
)


async def _scored(scorer: Scorer, reply: str, key: str, task_type: str = "mcq") -> Score:
    """The Score one scorer gives one reply against one key, on a Case of `task_type`."""

    state = TaskState(
        model="none/none",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[],
        output=ModelOutput.from_content(model="none/none", content=reply),
        metadata={"task_type": task_type, "subset_name": "organic_chemistry"},
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
    assert (await _scored(chembench_letter_set(), reply, "A,C")).value == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize("letters", ["A", "A,C,E", "A,B"])
async def test_a_missing_or_extra_letter_is_wrong(letters: str) -> None:
    score: Score = await _scored(chembench_letter_set(), f"[ANSWER]{letters}[/ANSWER]", "A,C")

    assert score.value == INCORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "key", "task_type"),
    [
        ("[ANSWER]B[/ANSWER]", "B", "mcq"),
        ("[ANSWER]b.[/ANSWER]", "B", "mcq"),
        ("[ANSWER]D[/ANSWER]", "B", "mcq"),
        ("[ANSWER]A,C[/ANSWER]", "A,C", "mcq"),
        ("The answer is B.", "B", "mcq"),
        ("[ANSWER]1.505[/ANSWER]", "1.5", "mae"),
        ("[ANSWER]1.6[/ANSWER]", "1.5", "mae"),
    ],
)
async def test_every_other_reply_grades_as_inspect_evals_grades_it(
    reply: str, key: str, task_type: str
) -> None:
    """The deviation is the letter compare and nothing else: single letters, a missing tag
    (a format failure) and numbers within 1% grade as v0.20.0 grades them."""

    inspect_evals_score: Score = await _scored(chembench_scorer(), reply, key, task_type)
    ours: Score = await _scored(chembench_letter_set(), reply, key, task_type)

    assert (ours.value, ours.reason) == (inspect_evals_score.value, inspect_evals_score.reason)


def test_the_row_grades_with_the_letter_set_scorer() -> None:
    row = next(spec for spec in BENCHMARKS if spec.key == "chembench")

    assert row.scorer.endswith("named_deviations.chembench.chembench:chembench_letter_set")
