# pyright: reportMissingImports=false
# WHY file-level: this module imports inspect_ai and inspect_evals, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only at grading time.
"""AIME marked wrong when the reply was cut off before it gave an answer.

Think of a student whose exam is taken away mid-sentence: whatever number they were last
writing is not their answer. AIME's prompt asks the model to end on an "ANSWER: n" line; a
reply the token limit cut off, with no such line at its end, never answered.

NAMED DEVIATION — adopted from inspect_evals issue #2701 (open, the fix proposed there;
https://github.com/UKGovernmentBEIS/inspect_evals/issues/2701). v0.20.0's ``aime_scorer`` reads
the reply's last substantive line as the answer whether or not the model finished, so a
reply cut off at "... so the remainder is 1" is right on a Case whose answer is 1. AIME answers
are integers from 0 to 999 and small ones turn up in working all the time; with 30 Cases a row,
one such credit is +3.3 points.

Marking, in execution order:

    1. an empty reply goes to the eval's own scorer, unchanged (wrong, "empty completion").
    2. a reply that stopped at the token limit (stop reason ``max_tokens``, carried by the
       scorer adapter from the Candidate's ``finish_reason: length``) whose last substantive
       line has no ``ANSWER:`` is wrong, with no answer read.
    3. every other reply goes to the eval's own scorer, unchanged: a finished reply,
       ``\\boxed{}`` handling included, and a cut-off one whose last line is its answer.

Worked example, key 1: "Try n = 3: then 3^2 + 7 = 16, so the remainder is 1" cut off → wrong
(v0.20.0: right). The same text finished → right, as v0.20.0. "...\\nANSWER: 1" cut off →
right, as v0.20.0.

LIMITATION, faithful to #2701: a reply cut off INSIDE its ANSWER: line keeps the credit that
line's digits earn. A model writing "ANSWER: 104" that the limit stops after "ANSWER: 1" is
right on a Case whose answer is 1, because the line carries the mark; the stop reason says the
reply was cut, not where, so the guard cannot tell a finished answer line from a truncated one.

INVARIANT: this file's source is hashed into the aime24, aime25 and aime26 revisions.
"""

from __future__ import annotations

from inspect_ai.scorer import INCORRECT, Score, Scorer, Target, accuracy, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_evals.utils.aime_common import _find_last_substantive_line, aime_scorer

#: The line the prompt asks the reply to end on; its presence means the model answered.
ANSWER_LINE_MARK: str = "ANSWER:"


@scorer(metrics=[accuracy(), stderr()])
def aime_cut_off_scorer() -> Scorer:
    """The eval's AIME scorer, with a reply cut off before its answer line marked wrong."""

    inspect_evals_scorer: Scorer = aime_scorer()

    async def score(state: TaskState, target: Target) -> Score | None:
        raw: str = state.output.completion
        # Stage 1: an empty reply is the eval's own case.
        if raw.strip().splitlines():
            last_line: str = _find_last_substantive_line(raw)
            # Stage 2: cut off before the answer line, so no answer was ever given. A cut
            # INSIDE the answer line ("ANSWER: 1" of 104) passes, as in #2701 (docstring).
            if state.output.stop_reason == "max_tokens" and ANSWER_LINE_MARK not in last_line:
                return Score(
                    value=INCORRECT,
                    answer=None,
                    explanation="Generation hit max_tokens before an ANSWER: line",
                    metadata={"unprocessed_answer": raw, "cleaned_answer": None},
                )
        # Stage 3: everything else is marked as the eval marks it.
        return await inspect_evals_scorer(state, target)

    return score
