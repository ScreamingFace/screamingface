# pyright: reportMissingImports=false, reportPossiblyUnboundVariable=false
# WHY file-level: this module imports inspect_ai and inspect_evals, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only at grading time.
# reportPossiblyUnboundVariable: `score_helper` is v0.20.0's, copied verbatim, and its grader-model
# branch reads `result` under the same `not exact_match` condition that sets it; silenced
# here rather than by editing the copied lines.
"""MATH's two exact-match scorers, reading the ANSWER: line the way the prompt's readers do.

Think of the marker as two steps: first copy the answer off the reply's last `ANSWER:` line,
then compare it with the key. The compare step is the eval's own, untouched (the paper's
normalised exact match, and Minerva's sympy equivalence). Only the copy step changes: v0.20.0
copies the line's text verbatim, so wrapping that every reader would see through makes a right
answer wrong.

WHAT IS COPIED, AND FROM WHERE. Every inspect_evals line below is copied verbatim, names and
bodies unchanged:

    - `expression_exact_match_sympy` and `expression_exact_match`: v0.20.0's scorers,
      https://github.com/UKGovernmentBEIS/inspect_evals/blob/v0.20.0/src/inspect_evals/math/math.py#L129-L158
    - `score_helper`: v0.20.0's,
      https://github.com/UKGovernmentBEIS/inspect_evals/blob/v0.20.0/src/inspect_evals/math/utils.py#L75-L121
      Both are copied only because v0.20.0 binds `extract_answer` inside its own module, so its
      scorers cannot be pointed at ours (forced by the pin).
    - `extract_answer`: v0.20.0's, with two open inspect_evals PRs applied, each block verbatim:
      PR #2199 (head 3bca67e5, unwraps a `\\boxed{...}` on the ANSWER: line),
      https://github.com/UKGovernmentBEIS/inspect_evals/blob/3bca67e5e57af3862552258cf33ea918c313fe90/src/inspect_evals/math/utils.py#L124-L152
      and PR #2340 (head 89171c5e, drops a paired outer `\\(...\\)` or `\\[...\\]`; issue #2220),
      https://github.com/UKGovernmentBEIS/inspect_evals/blob/89171c5e3d2213c86926dc23af402dcb7f085259/src/inspect_evals/math/utils.py#L124-L140
      Both PRs rewrite the same lines, so no single copy holds both. They are joined the way a
      merge would: #2199's early return on no match and its box block run first, and #2340's
      delimiter block takes the place of #2199's final `return answer` (its own final
      `return answer` serves both). Its docstring is #2199's, with #2340 credited.

WHAT IS OURS (each marked `OURS` where it runs):

    1. before the PR blocks, `drop_whitespace_and_bold` trims the line and drops markdown bold.
       A trailing carriage return or tab is not ignored by the compare steps: on a Windows line
       ending (`ANSWER: 42\\r\\n`) v0.20.0 copies `42\\r`, which its exact match marks wrong and
       sympy marks right; ours copies `42` for both. `**ANSWER: 42**` copies `42**` in v0.20.0,
       which no compare step can match to 42. (No inspect_evals PR or issue yet.)
    2. after `score_helper` builds its Score, `explain_empty_answer_line` names a reply whose
       ANSWER: line was there but held only wrapping (`ANSWER: \\boxed{}`, `ANSWER: ****`), which
       v0.20.0 reports as "Answer not found". The verdict is unchanged: wrong either way.

Worked example, key 42: "6 times 7.\\nANSWER: \\boxed{42}" copies `42` and is right;
"**ANSWER: \\(41\\)**" copies `41` and is wrong; "The box says \\boxed{42}." has no ANSWER: line,
copies nothing, and is wrong, as in v0.20.0; "ANSWER: \\boxed{}" copies an empty answer and is
wrong, explained as an empty ANSWER: line rather than a missing one.

LIMITATION, kept on purpose: with two boxes on the ANSWER: line the LAST one is copied, so
"ANSWER: \\boxed{41} or \\boxed{42}" is right for 42 (v0.20.0 copies the whole line and marks
it wrong). PR #2199 and the MATH paper's own grader (`last_boxed_only_string`) read the last box
the same way, so we keep their rule rather than invent a stricter one.

NAMED DEVIATION — PRs #2199 and #2340 (both open:
https://github.com/UKGovernmentBEIS/inspect_evals/pull/2199,
https://github.com/UKGovernmentBEIS/inspect_evals/pull/2340) and our two steps above. The
compare helpers are imported from inspect_evals v0.20.0, so only the copying is ours.

INVARIANT: this file's source is hashed into the math revision; the scorer names stay the eval's,
because the row's Named Scores are the scorers' registry names.
"""

from __future__ import annotations

import re

from inspect_ai.model import Model, get_model
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
    EQUIVALANCE_TEMPLATE,
    is_equiv,
    is_equiv_sympy,
    last_boxed_only_string,
    normalize_final_answer,
    remove_boxed,
)

#: Why a reply whose ANSWER: line holds only wrapping is wrong (the line exists, the answer not).
EMPTY_ANSWER_LINE: str = "Empty answer on the ANSWER: line once its wrapping is dropped"
#: Markdown bold, the one wrapping `drop_whitespace_and_bold` drops.
_BOLD: str = "**"


# ── COPIED VERBATIM: v0.20.0's two exact-match scorers ──────────────────────────────────


# Exact match using sympy based on: https://arxiv.org/pdf/2206.14858
@scorer(metrics=[accuracy(), stderr()])
def expression_exact_match_sympy() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return await score_helper(
            state=state,
            target=target,
            exact_match=True,
            use_sympy=True,
        )

    return score


# Exact match based on:
# https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/hendrycks_math/utils.py#L36
@scorer(metrics=[accuracy(), stderr()])
def expression_exact_match() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return await score_helper(
            state=state,
            target=target,
            exact_match=True,
            use_sympy=False,
        )

    return score


# ── COPIED VERBATIM: v0.20.0's score_helper, plus one marked line of ours before its return ──


async def score_helper(
    state: TaskState,
    target: Target,
    exact_match: bool,
    use_sympy: bool = False,
    model: str | Model | None = None,
) -> Score:
    answer = extract_answer(state.output.completion)
    if answer:
        if exact_match:
            if use_sympy:
                # Use sympy library for exact match based on https://arxiv.org/pdf/2206.14858
                norm_answer = await normalize_final_answer(answer)
                norm_target = await normalize_final_answer(target.text)
                correct = await is_equiv_sympy(norm_answer, norm_target)
            else:
                correct = await is_equiv(answer, target.text)

        # Ask grader model to judge equivalence
        else:
            prompt = EQUIVALANCE_TEMPLATE % ({"expression1": target.text, "expression2": answer})
            result = await get_model(model).generate(prompt)

            # Return the score
            matches = re.findall(r"\b(yes|no)\b", result.completion.lower())
            correct = matches[-1] == "yes" if matches else False

        score = Score(
            value=CORRECT if correct else INCORRECT,
            explanation=state.output.completion,
            metadata={
                "extracted_answer": answer,
            },
        )

        if not exact_match and score.metadata is not None:
            score.metadata.update({"grader_model_usage": result.usage})
    else:
        score = Score(
            value=INCORRECT,
            explanation="Answer not found in model output: " + f"{state.output.completion}",
        )

    # OURS, not inspect_evals' (see the module docstring): name an empty ANSWER: line.
    score = explain_empty_answer_line(score, state.output.completion)
    return score


# ── extract_answer: v0.20.0's, with PR #2199's and PR #2340's blocks, each verbatim ─────


def extract_answer(completion: str) -> str:  # noqa: PLR0911 — the PRs' own returns, kept
    r"""
    Find the last occurrence of ANSWER: pattern

    Handles cases like "**Final answer:**\nANSWER: 42" where we want to extract "42".

    Also unwraps a \boxed{...}/\fbox{...} expression when it appears within that
    same ANSWER: line (e.g. "ANSWER: \boxed{42}"), since many reasoning models
    box their final answer even though the prompt says they don't need to.

    This is deliberately narrow: AnswerPattern.LINE still requires the literal
    "ANSWER:" marker anchored to the end of the completion (i.e. the last line,
    per the prompt), so a bare \boxed{...} elsewhere in the completion (e.g. in
    intermediate reasoning) is never picked up as the answer.
    """
    # PR #2199:
    matches = list(re.finditer(AnswerPattern.LINE, completion))
    if not matches:
        return ""

    answer = matches[-1].group(1)
    # OURS (see the module docstring, step 1):
    answer = drop_whitespace_and_bold(answer)

    # PR #2199:
    boxed = last_boxed_only_string(answer)
    if boxed is not None:
        try:
            return remove_boxed(boxed)
        except (AssertionError, IndexError):
            return answer

    # PR #2340:
    stripped_answer = answer.strip()
    for opening, closing in ((r"\(", r"\)"), (r"\[", r"\]")):
        if stripped_answer.startswith(opening) and stripped_answer.endswith(closing):
            return stripped_answer[len(opening) : -len(closing)]
    return answer


# ── OURS: the two steps no inspect_evals PR covers (module docstring, "WHAT IS OURS") ────


def drop_whitespace_and_bold(answer: str) -> str:
    """Step 1: the ANSWER: line's text trimmed of all whitespace, with markdown bold dropped.

    `42\r` (a CRLF line) copies `42`; `** 42` (from `**ANSWER:** 42`) copies `42`.
    """

    return answer.strip().removeprefix(_BOLD).removesuffix(_BOLD).strip()


def explain_empty_answer_line(score: Score, completion: str) -> Score:
    """Step 2: a reply whose ANSWER: line was there but empty is explained as such.

    `score_helper` reports any empty extraction as "Answer not found"; when the reply does end
    in an ANSWER: line, that misreports it. Only the explanation changes, never the verdict.
    """

    found_line: bool = any(re.finditer(AnswerPattern.LINE, completion))
    if score.value == INCORRECT and found_line and not extract_answer(completion):
        return score.model_copy(update={"explanation": f"{EMPTY_ANSWER_LINE}: {completion}"})
    return score
