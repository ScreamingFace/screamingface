"""What each grader reads as an answer, said once per scorer and shown on every Benchmark page.

FEATURE: answer format on the Benchmark page (OME-1906, follow-up of OME-1886). A submitter
whose model wrote `ANSWER: $C` paid for a full MMLU-Pro run in which inspect's parser read 68
of 200 replies as no answer. The grader stays as inspect wrote it; the page says what it reads,
so a cheap smoke run can be checked first.

Think of it as the instructions printed at the top of an exam paper: they belong to the marking
scheme, not to one question, so they are written once per scorer (95 catalogue rows share 38
scorers) and the Engine appends them to every row graded by that scorer. A row's own prose
stays hand-written in its catalogue entry; this sentence follows it.

Stages, in execution order (:func:`with_answer_format`):

    Stage 1 — find the row's answer format: by its catalogue key first, then by its scorer
              reference.
              WHY the key first: a few scorers are configured per row (inspect's `match` reads
              a number for gsm8k), so one sentence per scorer would be wrong for some rows.
    Stage 2 — append the answer format's sentence to the row's prose, one space between.

Worked example — the MMLU-Pro row has no answer format of its own, so Stage 1 finds the one for
`inspect_ai.scorer:choice`; on a Case whose key is B, its quoted replies grade `ANSWER: B` and
`ANSWER: B.` → 1, and `ANSWER: $B`, `ANSWER: (B)`, `ANSWER: **B**`, `ANSWER: \\boxed{B}` → 0.

One file per family of graders, grouped by how they read a reply: `_choice.py` (inspect's
multiple-choice scorer), `_letters.py` (other letter scorers), `_exact.py` (exact, number,
pattern and overlap scorers), `_judged.py` (a judge model reads the reply).

INVARIANT: every quoted reply of a non-judge answer format grades the way its sentence says,
through each row's real grader (`tests/unit/inspect/test_answer_formats.py`), so the page never
promises a format the grader refuses. Every catalogue row has one.

INVARIANT: the description is not part of a Benchmark's revision, so editing a sentence moves
no fingerprint and no published revision; the scoreboard's seed job copies the new text to the
leaderboard on the next deploy.

AIDEV-NOTE: plain data only. Benchmark assembly reads this package, and assembly never imports
inspect (it is an optional extra).
"""

from __future__ import annotations

from collections.abc import Mapping

from screamingface_engine_inspect.answer_formats._choice import CHOICE
from screamingface_engine_inspect.answer_formats._exact import EXACT
from screamingface_engine_inspect.answer_formats._format import AnswerFormat
from screamingface_engine_inspect.answer_formats._judged import JUDGED
from screamingface_engine_inspect.answer_formats._letters import LETTERS


def _merged(*families: Mapping[str, AnswerFormat]) -> dict[str, AnswerFormat]:
    """One lookup table from the family files, refusing a key defined in two of them."""

    merged: dict[str, AnswerFormat] = {}
    for family in families:
        clash: set[str] = merged.keys() & family.keys()
        if clash:
            raise ValueError(f"answer format defined twice: {sorted(clash)}")
        merged.update(family)
    return merged


#: Row key or scorer reference (as a catalogue row names it) → its answer format.
ANSWER_FORMATS: Mapping[str, AnswerFormat] = _merged(CHOICE, LETTERS, EXACT, JUDGED)


def answer_format_for(key: str, scorer: str) -> AnswerFormat | None:
    """The row's own answer format when it has one, else its scorer's (Stage 1)."""

    return ANSWER_FORMATS.get(key) or ANSWER_FORMATS.get(scorer)


def with_answer_format(description: str, key: str, scorer: str) -> str:
    """The row's own prose, followed by its answer-format sentence when there is one."""

    answer_format: AnswerFormat | None = answer_format_for(key, scorer)
    # Stage 2 — prose, one space, sentence.
    return description if answer_format is None else f"{description} {answer_format.sentence}"


__all__ = ["ANSWER_FORMATS", "AnswerFormat", "answer_format_for", "with_answer_format"]
