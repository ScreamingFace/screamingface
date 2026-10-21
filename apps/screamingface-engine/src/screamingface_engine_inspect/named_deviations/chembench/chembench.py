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
"A, C", "A C" and "C,A" all score 0. 394 of the 2,785 Cases have more than one correct letter;
on every other Case the two rules agree. The ChemBench authors compare sets
(`set(found) == set(...)` in their `metrics.py`), and so does the fix.

Marking, in execution order:

    1. a numeric Case (`task_type == "mae"`) goes to the eval's own `pattern_mae`, unchanged.
    2. a multiple-choice Case: the eval's own regex finds the text inside the answer tags; no
       tags is a format failure, as before (`invalid_response_format`).
    3. the letters found are compared to the key's letters as sets, ignoring case.

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

#: What inspect's pattern scorer calls a reply with no answer tags (the eval's behaviour kept).
INVALID_RESPONSE_FORMAT: str = "invalid_response_format"


def letters(text: str) -> frozenset[str]:
    """The option letters named in a piece of text, upper-cased: "c, a" → {A, C}."""

    return frozenset(re.findall(r"[A-Z]", text.upper()))


async def letter_set_score(state: TaskState, target: Target) -> Score:
    """Right when the letters inside the answer tags are exactly the key's letters."""

    completion: str = state.output.completion
    # Stage 2: the eval's own regex, with the IGNORECASE its pattern scorer applies.
    found: re.Match[str] | None = re.search(MCQ_REGEX_TEMPLATE, completion, re.IGNORECASE)
    if found is None:
        return Score(
            value=INCORRECT,
            reason=INVALID_RESPONSE_FORMAT,
            explanation=f"Scoring pattern not matched in output: {completion}",
        )
    # Stage 3: sets, not strings.
    answer: str = found.group(1)
    right: bool = letters(answer) == letters(target.text)
    return Score(value=CORRECT if right else INCORRECT, answer=answer, explanation=completion)


@scorer(metrics=[grouped(accuracy(), "subset_name"), stderr()])
def chembench_letter_set() -> Scorer:
    """The eval's scorer with multiple choice marked by the set of letters."""

    mae_scorer: Scorer = pattern_mae(pattern=FLOATQ_REGEX_TEMPLATE)

    async def score(state: TaskState, target: Target) -> Score | None:
        # Stage 1: numeric Cases are the eval's own.
        if state.metadata["task_type"] == "mae":
            return await mae_scorer(state, target)
        return await letter_set_score(state, target)

    return score
