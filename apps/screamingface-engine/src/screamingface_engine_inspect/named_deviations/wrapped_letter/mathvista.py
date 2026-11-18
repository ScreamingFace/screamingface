# pyright: reportMissingImports=false
# WHY file-level: this module imports inspect_ai and inspect_evals, absent in the default
# (extra-less) install the typecheck gate runs against; it is loaded only at grading time.
"""MathVista's own pattern scorer, with an answer inside a wrapper graded against its key.

NAMED DEVIATION — inspect_ai issue 5055's first site (see ``wrapped_letter.py``). inspect_evals
v0.20.0's ``mathvista_scorer`` reads a multiple-choice answer with `AnswerPattern.LETTER` and a
free-form one with `AnswerPattern.LINE`: `ANSWER: (B)` finds no letter, and `ANSWER: **42**`
captures the stars, so both score 0 on a right answer. Worked example: key B, `ANSWER: $B$` →
v0.20.0 wrong, here right; `ANSWER: 1.50` against 1.5 stays wrong, as v0.20.0 (no wrapper).

INVARIANT: this package's source is hashed into the mathvista revision (``scorer_source_pins``).
"""

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_evals.mathvista.mathvista import mathvista_scorer

from screamingface_engine_inspect.named_deviations.wrapped_letter.wrapped_letter import (
    peeled_score,
)


@scorer(metrics=[accuracy(), stderr()])
def mathvista_wrapped_scorer() -> Scorer:
    """The eval's MathVista scorer, retried on a peeled copy when its mark is not right."""

    inspect_evals_scorer: Scorer = mathvista_scorer()

    async def score(state: TaskState, target: Target) -> Score | None:
        return await peeled_score(inspect_evals_scorer, state, target)

    return score
