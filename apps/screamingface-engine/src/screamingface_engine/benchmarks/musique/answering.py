"""Reading a MuSiQue-Ans reply — the two lines the Candidate commits to (spec D6, D7).

INVARIANT: this reads a model that may reason aloud before it commits, so the LAST label wins.
That is the opposite of MedXpert's trigger-completion parser (`medxpert/answering.py`), which
takes the FIRST letter because there the commitment leads; the two must never be merged.

INVARIANT: never a crash, never a guess. A missing line is reported (`answer_line` /
`support_line` False) and the grader decides what that scores, so a reply in the wrong format
is visible in the Report instead of silently scoring zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The two labels the prompt asks for (`prompts.CASE_TEMPLATE`), matched in any case.
#: WHY plain substrings and not line anchors: models wrap labels in markdown (`**Answer:**`)
#: or prefix them (`Final answer:`), and both are still the commitment.
_ANSWER_LABEL = re.compile(re.escape("Answer:"), re.IGNORECASE)
_SUPPORT_LABEL = re.compile(re.escape("Supporting paragraphs:"), re.IGNORECASE)

#: A paragraph number on the support line. ASCII digits only: `int()` would also accept other
#: scripts' digits, which no paragraph number in the prompt is written in.
_NUMBER = re.compile(r"[0-9]+")


@dataclass(frozen=True, slots=True)
class ExtractedReply:
    """What one reply committed to, and whether it committed in the asked-for format."""

    answer: str
    answer_line: bool
    support: frozenset[int]
    support_line: bool


def extract_reply(completion: str) -> ExtractedReply:
    """Read the committed answer and supporting paragraphs off the end of a reply.

    Mental model: the reply is an exam script whose last two lines are the boxed answer. We read
    the boxes, not the working, and when a box is missing we mark the whole script instead of
    guessing which sentence was meant.

    Stages, in execution order:

    1. **Answer.** Find the LAST `Answer:` (any case). Its value is the rest of that line; if the
       rest is blank, the next non-empty line (models that put the label alone on a line). If the
       value runs into a `Supporting paragraphs:` label on the same line, it stops there, so the
       two labels never swallow each other. No `Answer:` anywhere: the whole reply, stripped, is
       the answer and `answer_line` is False (spec D7).
    2. **Support.** The same rule for the LAST `Supporting paragraphs:`, stopping at an
       `Answer:` label; every run of digits on that value is one paragraph number, collected as a
       set (the official metric takes a set too). No label: the empty set and `support_line`
       False — the official SupportMetric then scores 0, which is the paper's behaviour.

    Only whitespace is stripped. Markdown is left for the official `normalize_answer`, which
    drops punctuation itself; cleaning it here too would be our rule, not the paper's.

    Worked example — the reply ends::

        Paragraph 10 is Steve Hillage's album; maybe the answer: Hillage? No, the spouse.
        Supporting paragraphs: 10, 5, 5
        **Answer:** Miquette Giraudy

    Stage 1: two `answer:` hits; the last is in `**Answer:**`, so the answer is
    `** Miquette Giraudy` (normalised later to `miquette giraudy`, F1 1.0 against the gold).
    Stage 2: one support label; digits `10`, `5`, `5` give the set {5, 10}.

    Args:
        completion: the Candidate's full reply text, exactly as returned.

    Returns:
        The committed answer (possibly empty, when the label had no value), the set of cited
        paragraph numbers (possibly empty), and one flag per line saying whether its label was
        found at all.
    """

    # Stage 1 — the answer: the last `Answer:` value, or the whole reply when there is none.
    answer: str | None = _committed_value(completion, _ANSWER_LABEL, stop=_SUPPORT_LABEL)
    # Stage 2 — the support set: the digits on the last `Supporting paragraphs:` value.
    support: str | None = _committed_value(completion, _SUPPORT_LABEL, stop=_ANSWER_LABEL)
    return ExtractedReply(
        answer=completion.strip() if answer is None else answer,
        answer_line=answer is not None,
        support=frozenset() if support is None else _paragraph_numbers(support),
        support_line=support is not None,
    )


def _committed_value(text: str, label: re.Pattern[str], *, stop: re.Pattern[str]) -> str | None:
    """The value after the last ``label``, or ``None`` when the reply never wrote it.

    The value is the rest of the label's line, or the next non-empty line when that rest is
    blank, cut at the first ``stop`` label, then stripped.
    """

    hits: list[re.Match[str]] = list(label.finditer(text))
    if not hits:
        return None
    first, *following = text[hits[-1].end() :].split("\n")
    value: str = first
    if not value.strip():
        # WHY only when blank: a label with a value on its own line is already the commitment,
        # and reaching past it would read the next line of a reply that kept going.
        value = next((line for line in following if line.strip()), "")
    return stop.split(value, maxsplit=1)[0].strip()


def _paragraph_numbers(value: str) -> frozenset[int]:
    """Every paragraph number cited on the support line, as a set."""

    return frozenset(int(number) for number in _NUMBER.findall(value))


__all__ = ["ExtractedReply", "extract_reply"]
