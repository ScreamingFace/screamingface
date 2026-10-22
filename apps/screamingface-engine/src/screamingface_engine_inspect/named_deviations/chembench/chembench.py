# pyright: reportMissingImports=false
# WHY file-level: this module imports inspect_ai and inspect_evals, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only at grading time.
"""ChemBench marked by the SET of letters, as the ChemBench authors mark it.

Think of a multi-answer question as a checklist: "which of these are aromatic?" is answered by
ticking A and C, and it does not matter whether the reply writes "A,C", "A, C", "A C" or "C,A".
The eval's prompt says so itself: it asks for "a comma- or space-separated list of the correct
letters" inside [ANSWER]...[/ANSWER].

NAMED DEVIATION — adopted from inspect_evals PR #2591 (open; issue #2586;
https://github.com/UKGovernmentBEIS/inspect_evals/pull/2591). v0.20.0's `chembench_scorer`
finds the letters with its own regex, then compares them to the key ("A,C") as a STRING, so
"A, C", "A C" and "C,A" all score 0. 394 of the 2,785 Cases have more than one correct letter.
On the one-letter Cases the two rules agree on every reply except one that repeats the letter:
"B,B" or "B B" against the key "B" was wrong and is now right, because as sets {B} is {B}. The
ChemBench authors compare sets (`set(found) == set(...)` in their `metrics.py`), so they mark it
right too, and so does the fix.

COPIED VERBATIM: `multiple_choice_letters` and `chembench_scorer` below are the PR's own two
functions, names and bodies unchanged, at its head commit 3bfc894a:
https://github.com/UKGovernmentBEIS/inspect_evals/blob/3bfc894aabb0ebde7593c4e36e781b591c619c0b/src/inspect_evals/chembench/chembench.py#L223-L262
That file is v0.20.0's plus exactly this change, so the regexes and `pattern_mae` are imported
from the pinned v0.20.0. Ours is only where they live: v0.20.0's Task cannot be edited, so the
row names this module's `chembench_scorer` instead of inspect_evals'.

Marking, in execution order:

    1. a numeric Case (`task_type == "mae"`) goes to the eval's own `pattern_mae`, unchanged.
    2. a multiple-choice Case: the eval's own regex finds the text inside the answer tags; no
       tags is a format failure, as before (`invalid_response_format`).
    3. the letters found are compared, as a set, to the key split on its commas.

Worked example: key "A,C". "[ANSWER]C, a[/ANSWER]" finds {A, C}: right. "[ANSWER]A[/ANSWER]"
finds {A}: wrong. "[ANSWER]A,B,C[/ANSWER]" finds {A, B, C}: wrong.

INVARIANT: this file's source is hashed into the chembench revision.
"""

from __future__ import annotations

import re

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    grouped,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState
from inspect_evals.chembench.chembench import FLOATQ_REGEX_TEMPLATE, MCQ_REGEX_TEMPLATE
from inspect_evals.chembench.mae_scorer import pattern_mae


def multiple_choice_letters() -> Scorer:
    """Compare the set of answer letters, as upstream ChemBench does.

    The prompt allows comma- or space-separated letters in any order, so "A, C",
    "A C" and "C,A" all answer a target of "A,C".
    """

    async def score(state: TaskState, target: Target) -> Score:
        match = re.search(MCQ_REGEX_TEMPLATE, state.output.completion, re.IGNORECASE)
        if match is None:
            return Score(
                value=INCORRECT,
                reason="invalid_response_format",
                explanation="Scoring pattern not matched in output: "
                + f"{state.output.completion}",
            )
        answer = match.group(1)
        answer_letters = set(re.findall(r"[A-Z]", answer.upper()))
        target_letters = set(target.text.upper().split(","))
        return Score(
            value=CORRECT if answer_letters == target_letters else INCORRECT,
            answer=answer,
            explanation=state.output.completion,
        )

    return score


@scorer(metrics=[grouped(accuracy(), "subset_name"), stderr()])
def chembench_scorer() -> Scorer:
    multiple_choice_scorer = multiple_choice_letters()
    mae_scorer = pattern_mae(pattern=FLOATQ_REGEX_TEMPLATE)

    async def custom_score(state: TaskState, target: Target) -> Score | None:
        if state.metadata["task_type"] == "mae":
            return await mae_scorer(state, target)

        return await multiple_choice_scorer(state, target)

    return custom_score
