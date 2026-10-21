# pyright: reportMissingImports=false
# WHY file-level: the scorer imports inspect_ai and inspect_evals, absent in the extra-less
# typecheck install.
"""AIME marks a reply cut off by the token limit wrong: inspect_evals issue #2701, adopted.

What these tests pin, and why:

- the TRIPWIRE: v0.20.0's ``aime_scorer`` still credits #2701's reproduction, a reply cut off
  mid-reasoning whose last line happens to end in the answer; ours marks it wrong. When a pin
  bump makes the first assert fail, inspect_evals has the fix and the Named Deviation can go
  (https://github.com/UKGovernmentBEIS/inspect_evals/issues/2701);
- a reply cut off right after its ``ANSWER:`` line keeps its credit (the model did answer);
- every reply that finished on its own grades exactly as v0.20.0 grades it, ``\\boxed{}``
  included, as does one whose stop reason is unknown;
- the three AIME rows grade with this scorer.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from inspect_ai.model import ModelOutput, StopReason  # noqa: E402
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402
from inspect_evals.utils.aime_common import aime_scorer  # noqa: E402

from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402
from screamingface_engine_inspect.named_deviations.aime.aime import (  # noqa: E402
    aime_cut_off_scorer,
)

#: inspect_evals issue #2701's reproduction, verbatim: the model is still working when the
#: token limit stops it, and its last intermediate value happens to equal the key.
CUT_OFF_MID_REASONING: str = "Try n = 3: then 3^2 + 7 = 16, so the remainder is 1"


async def _scored(scorer: Scorer, reply: str, key: str, stop_reason: StopReason) -> Score:
    """The Score one scorer gives one reply against one key, for a reply that stopped so."""

    state = TaskState(
        model="none/none",  # type: ignore[arg-type]  # ModelName is a str alias at runtime
        sample_id=1,
        epoch=1,
        input="q",
        messages=[],
        output=ModelOutput.from_content(model="none/none", content=reply, stop_reason=stop_reason),
    )
    score: Score | None = await scorer(state, Target(key))
    assert score is not None
    return score


@pytest.mark.asyncio
async def test_tripwire_a_cut_off_reply_inspect_evals_credits_is_wrong_under_ours() -> None:
    """TRIPWIRE (inspect_evals issue #2701): the first assert is v0.20.0's verdict."""

    inspect_evals_score: Score = await _scored(
        aime_scorer(), CUT_OFF_MID_REASONING, "1", "max_tokens"
    )
    ours: Score = await _scored(aime_cut_off_scorer(), CUT_OFF_MID_REASONING, "1", "max_tokens")

    assert inspect_evals_score.value == CORRECT
    assert ours.value == INCORRECT
    # WHY the answer is None: the model never gave one, so nothing was read off the reply.
    assert ours.answer is None


@pytest.mark.asyncio
async def test_a_reply_cut_off_after_its_answer_line_keeps_its_credit() -> None:
    """The guard is "never answered", not "was cut off": an ANSWER: line written before the
    limit is the model's answer, as #2701's table keeps it."""

    reply: str = "3^2 + 7 = 16, the remainder mod 5 is 1.\nANSWER: 16"

    score: Score = await _scored(aime_cut_off_scorer(), reply, "16", "max_tokens")

    assert score.value == CORRECT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "key", "stop_reason"),
    [
        ("work...\nANSWER: 16", "16", "stop"),
        ("work\n$$\n\\boxed{70}\n$$", "70", "stop"),
        ("work...\nANSWER: 15", "16", "stop"),
        # WHY "stop": a reply that finished on its own and ends on a number is inspect_evals' call.
        (CUT_OFF_MID_REASONING, "1", "stop"),
        # WHY "unknown": a Candidate whose finish reason never reached us is not called cut off.
        (CUT_OFF_MID_REASONING, "1", "unknown"),
        ("", "1", "max_tokens"),
    ],
)
async def test_every_other_reply_grades_as_inspect_evals_grades_it(
    reply: str, key: str, stop_reason: StopReason
) -> None:
    """The deviation is the cut-off guard and nothing else (#2701's table, rows 1, 2 and 4)."""

    inspect_evals_score: Score = await _scored(aime_scorer(), reply, key, stop_reason)
    ours: Score = await _scored(aime_cut_off_scorer(), reply, key, stop_reason)

    assert (ours.value, ours.answer) == (inspect_evals_score.value, inspect_evals_score.answer)


@pytest.mark.parametrize("key", ["aime24", "aime25", "aime26"])
def test_the_aime_rows_grade_with_the_cut_off_scorer(key: str) -> None:
    row = next(spec for spec in BENCHMARKS if spec.key == key)

    assert row.scorer.endswith("named_deviations.aime.aime:aime_cut_off_scorer")
    assert row.answer_rule is not None
    assert row.answer_rule.grader.startswith(row.scorer)
