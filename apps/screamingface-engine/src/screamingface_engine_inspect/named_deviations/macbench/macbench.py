# pyright: reportMissingImports=false
# WHY file-level: this module imports inspect_ai and inspect_evals, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only at grading time.
"""MaCBench marked by the SET of letters, as the MaCBench authors mark it.

Think of a multi-answer question as a checklist: "which of these liquids are alcohols?" is
answered by ticking A and C, and it does not matter whether the reply writes "A,C", "A, C",
"A C" or "C,A". The eval's prompt says so itself: it asks for "comma- or space-separated list
of the correct letters" inside [ANSWER]...[/ANSWER].

NAMED DEVIATION — chembench's fix, applied to its sibling eval. v0.20.0's `macbench_scorer`
grades multiple choice with inspect's `pattern(MCQ_REGEX_TEMPLATE)`: the regex finds the
letters, and the scorer compares them to the key ("A,C") as a STRING, so "A, C", "A C" and
"C,A" all score 0. 19 of the 779 multiple-choice Cases have more than one correct letter (the
other 374 Cases are numeric). That is the bug inspect_evals issue #2586 names for chembench
(https://github.com/UKGovernmentBEIS/inspect_evals/issues/2586), whose open fix is PR #2591
(https://github.com/UKGovernmentBEIS/inspect_evals/pull/2591); macbench reuses chembench's
regex and its string compare, and has no fix of its own. Reported for macbench on that
issue on 2026-11-09 (https://github.com/UKGovernmentBEIS/inspect_evals/issues/2586#issuecomment-6734254126),
offering to extend PR #2591; when the pin reaches a fix, this module goes and the tripwire
test says so. We checked on 2026-11-09 with the
pinned scorer: `[ANSWER]C, A[/ANSWER]` against the key "A,C" scores 0. On the one-letter
Cases the two rules agree on every reply except one that repeats the letter: "B,B" or "B B"
against the key "B" was wrong and is now right, because as sets {B} is {B}. The MaCBench
authors' own ChemBench engine compares sets (`set(found) == set(...)` in their `metrics.py`),
so they mark it right too.

COPIED VERBATIM: `multiple_choice_letters` below is PR #2591's own function, name and body
unchanged, at its head commit 3bfc894a:
https://github.com/UKGovernmentBEIS/inspect_evals/blob/3bfc894aabb0ebde7593c4e36e781b591c619c0b/src/inspect_evals/chembench/chembench.py#L223-L248
`macbench_scorer` below is v0.20.0's own, with that function in place of `pattern(...)`; the
regexes and `pattern_mae` are imported from the pinned v0.20.0. Ours is only where they live:
v0.20.0's Task cannot be edited, so the row names this module's `macbench_scorer` instead of
inspect_evals'.

Marking, in execution order:

    1. a numeric Case (`task_type == "mae"`) goes to the eval's own `pattern_mae`, unchanged:
       the Case's own `tolerance` (the dataset's precomputed window, read as absolute, or the
       1% relative fallback) decides.
    2. a multiple-choice Case: the eval's own regex finds the text inside the answer tags; no
       tags is a format failure, as before (`invalid_response_format`).
    3. the letters found are compared, as a set, to the key split on its commas.

Worked example: key "A,C". "[ANSWER]C, a[/ANSWER]" finds {A, C}: right. "[ANSWER]A[/ANSWER]"
finds {A}: wrong. "[ANSWER]A,B,C[/ANSWER]" finds {A, B, C}: wrong.

INVARIANT: this file's source is hashed into the macbench revision.
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
def macbench_scorer() -> Scorer:
    """v0.20.0's macbench_scorer, its multiple-choice branch grading the set of letters."""

    multiple_choice_scorer = multiple_choice_letters()
    mae_scorer = pattern_mae(pattern=FLOATQ_REGEX_TEMPLATE)

    async def custom_score(state: TaskState, target: Target) -> Score | None:
        if state.metadata["task_type"] == "mae":
            return await mae_scorer(state, target)

        return await multiple_choice_scorer(state, target)

    return custom_score
