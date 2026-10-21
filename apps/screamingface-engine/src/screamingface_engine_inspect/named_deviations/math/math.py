# pyright: reportMissingImports=false
# WHY file-level: this module imports inspect_ai and inspect_evals, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only at grading time.
"""MATH's two exact-match scorers, reading the ANSWER: line the way the prompt's readers do.

Think of the marker as two steps: first copy the answer off the reply's last `ANSWER:` line,
then compare it with the key. The compare step is the eval's own, untouched (the paper's
normalised exact match, and Minerva's sympy equivalence). Only the copy step changes: v0.20.0
copies the line's text verbatim, so wrapping that every reader would see through makes a right
answer wrong.

Copying, in execution order (`extract_answer`):

    1. the text after the LAST `ANSWER:` that ends the reply, as v0.20.0 reads it, with the
       spaces around it trimmed (both compare steps ignore them).
    2. markdown bold around it is dropped: `**ANSWER: 42**` copies `42**` in v0.20.0, which no
       compare step can match to 42. (Ours; no inspect_evals PR or issue yet.)
    3. a paired outer `\\(...\\)` or `\\[...\\]` is dropped: `ANSWER: \\[\\frac{1}{2}\\]` scored 0
       under both scorers. (inspect_evals PR #2340, issue #2220.)
    4. a `\\boxed{...}` on that line is unwrapped: `ANSWER: \\boxed{42}` scored 0 under exact
       match. (inspect_evals PR #2199.) Only the ANSWER: line is read, never a box elsewhere.

Worked example, key 42: "6 times 7.\\nANSWER: \\boxed{42}" copies `42` and is right;
"**ANSWER: \\(41\\)**" copies `41` and is wrong; "The box says \\boxed{42}." has no ANSWER: line,
copies nothing, and is wrong, as in v0.20.0.

NAMED DEVIATION — steps 2 to 4 (links above:
https://github.com/UKGovernmentBEIS/inspect_evals/pull/2199,
https://github.com/UKGovernmentBEIS/inspect_evals/pull/2340, both open). The compare helpers
are imported from inspect_evals v0.20.0, so only the copying is ours.

INVARIANT: this file's source is hashed into the math revision; the scorer names stay the eval's,
because the row's Named Scores are the scorers' registry names.
"""

from __future__ import annotations

import re

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    AnswerPattern,
    Score,
    Scorer,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState
from inspect_evals.math.utils import (
    is_equiv,
    is_equiv_sympy,
    last_boxed_only_string,
    normalize_final_answer,
    remove_boxed,
)

#: Markdown bold, the one wrapping step 2 drops.
_BOLD: str = "**"
#: The paired outer delimiters step 3 drops: LaTeX inline and display math.
_DELIMITERS: tuple[tuple[str, str], ...] = ((r"\(", r"\)"), (r"\[", r"\]"))


def extract_answer(completion: str) -> str:
    """The answer copied off the reply's last ANSWER: line, wrapping dropped; "" when none."""

    # Stage 1: v0.20.0's own read.
    matches: list[re.Match[str]] = list(re.finditer(AnswerPattern.LINE, completion))
    return _unwrapped(matches[-1].group(1)) if matches else ""


def _unwrapped(line: str) -> str:
    """Stages 2 to 4: the ANSWER: line's text with its bold, delimiters and box dropped."""

    # Stage 2: bold on either side (`**ANSWER:** 42` copies `** 42`).
    answer: str = line.strip().removeprefix(_BOLD).removesuffix(_BOLD).strip()
    # Stage 3: one paired outer delimiter.
    for opening, closing in _DELIMITERS:
        if answer.startswith(opening) and answer.endswith(closing):
            answer = answer[len(opening) : -len(closing)].strip()
            break
    # Stage 4: a box on the line, unwrapped with the eval's own helpers.
    boxed: str | None = last_boxed_only_string(answer)
    if boxed is None:
        return answer
    # WHY catch: remove_boxed asserts a `\boxed{` prefix, so an `\fbox{}` keeps the line as is.
    try:
        return remove_boxed(boxed)
    except (AssertionError, IndexError):
        return answer


async def _graded(state: TaskState, target: Target, *, use_sympy: bool) -> Score:
    """The eval's `score_helper` exact-match branches, fed our copied answer."""

    answer: str = extract_answer(state.output.completion)
    if not answer:
        return Score(
            value=INCORRECT,
            explanation=f"Answer not found in model output: {state.output.completion}",
        )
    correct: bool
    if use_sympy:
        norm_answer: str = await normalize_final_answer(answer)
        norm_target: str = await normalize_final_answer(target.text)
        correct = await is_equiv_sympy(norm_answer, norm_target)
    else:
        correct = await is_equiv(answer, target.text)
    return Score(
        value=CORRECT if correct else INCORRECT,
        explanation=state.output.completion,
        metadata={"extracted_answer": answer},
    )


@scorer(metrics=[accuracy(), stderr()])
def expression_exact_match() -> Scorer:
    """The paper's normalised exact match on the copied answer (the Headline Score)."""

    async def score(state: TaskState, target: Target) -> Score:
        return await _graded(state, target, use_sympy=False)

    return score


@scorer(metrics=[accuracy(), stderr()])
def expression_exact_match_sympy() -> Scorer:
    """Minerva's sympy equivalence on the copied answer (a Named Score beside the headline)."""

    async def score(state: TaskState, target: Target) -> Score:
        return await _graded(state, target, use_sympy=True)

    return score
