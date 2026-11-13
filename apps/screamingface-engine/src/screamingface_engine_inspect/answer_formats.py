"""What each grader reads as an answer, said once per scorer and shown on every Benchmark page.

FEATURE: answer format on the Benchmark page (OME-1906, follow-up of OME-1886). A submitter
whose model wrote `ANSWER: $C` paid for a full MMLU-Pro run in which inspect's parser read 68
of 200 replies as no answer. The grader stays as inspect wrote it; the page says what it reads, so a
cheap smoke run can be checked first.

Think of it as the instructions printed at the top of an exam paper: they belong to the marking
scheme, not to one question, so they are written once per scorer here (95 catalogue rows share
38 scorers) and the Engine appends them to every row graded by that scorer. A row's own prose
stays hand-written in its catalogue entry; this sentence follows it.

Worked example — the MMLU-Pro row's published description is its prose, one space, then the
`inspect_ai.scorer:choice` sentence below. On a Case whose key is B, the quoted replies grade:
`ANSWER: B` → 1; `ANSWER: $B`, `ANSWER: (B)`, `ANSWER: **B**`, `ANSWER: \\boxed{B}` → 0,
because inspect_ai v0.3.263's parser takes only letters, digits, spaces and commas after
`ANSWER:` (`solver/_multiple_choice.py:98-110`).

INVARIANT: every reply a sentence quotes is graded, through each row's real grader, the way the
sentence says (`tests/unit/inspect/test_answer_formats.py`), so the page never promises a format
the grader refuses. Adding or changing a sentence means adding or changing its examples.

INVARIANT: the description is not part of a Benchmark's revision, so editing a sentence moves
no fingerprint and no published revision; the scoreboard's seed job copies the new text to the
leaderboard on the next deploy.

AIDEV-NOTE: plain data only. Benchmark assembly reads this module, and assembly never imports
inspect (it is an optional extra).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerFormat:
    """One scorer's answer rule, in the words a submitter reads, with replies that prove it.

    Attributes:
        sentence: appended to the description of every row graded by the scorer; quotes each
            example reply in single quotes.
        key: the answer key the example replies are written for (a stand-in Case's key).
        accepted: replies the sentence says are read as an answer; each scores 1 on ``key``.
        rejected: replies the sentence says are read as no answer; each scores 0.
    """

    sentence: str
    key: str
    accepted: tuple[str, ...]
    rejected: tuple[str, ...]


#: Scorer reference (as a catalogue row names it) → its answer rule. PR 1 of 2 covers inspect's
#: own multiple-choice scorer (35 rows); PR 2 of 2 covers the other 37 scorers.
ANSWER_FORMATS: Mapping[str, AnswerFormat] = {
    "inspect_ai.scorer:choice": AnswerFormat(
        sentence=(
            "Answer format: end the reply with a line like 'ANSWER: B', the bare letter of one "
            "option. A letter with anything around it, such as 'ANSWER: $B', 'ANSWER: (B)', "
            "'ANSWER: **B**' or 'ANSWER: \\boxed{B}', is read as no answer and scores 0, even "
            "when the letter is right."
        ),
        key="B",
        accepted=("ANSWER: B",),
        rejected=("ANSWER: $B", "ANSWER: (B)", "ANSWER: **B**", "ANSWER: \\boxed{B}"),
    ),
}


def with_answer_format(description: str, scorer: str) -> str:
    """The row's own prose, followed by its scorer's answer-format sentence when there is one."""

    answer_format: AnswerFormat | None = ANSWER_FORMATS.get(scorer)
    return description if answer_format is None else f"{description} {answer_format.sentence}"
