# pyright: reportMissingImports=false
# WHY file-level: this module imports inspect_ai, absent in the default (extra-less) install
# the typecheck gate runs against; it is loaded only at grading time.
"""An answer inside a wrapper, such as `ANSWER: $B`, `ANSWER: **B**` or `ANSWER: (B)`, graded
against its key.

Think of a marker who reads past the pen strokes around a circled letter: inspect reads the
reply first, and only when it finds no answer do we rub out one layer of decoration from a
COPY of the reply and let inspect read it again.

NAMED DEVIATION — our own fix for inspect_ai issue 5055 (open, no maintainer reply;
https://github.com/UKGovernmentBEIS/inspect_ai/issues/5055). inspect_ai v0.3.263 reads only a
bare answer after `ANSWER:`: `parse_answers` (`solver/_multiple_choice.py:98-110`) takes
letters, digits, spaces and commas, and `AnswerPattern` needs a letter right after the colon
(LETTER) or captures the decoration with the answer (WORD, LINE). So `ANSWER: $B` scores 0 on a
Case whose key is B. The one fix attempt, PR 5058, was closed by its author after it broke 5
tests (https://github.com/UKGovernmentBEIS/inspect_ai/pull/5058); this rule never changes a
reply inspect already reads, which is what broke there.

Reading, in execution order:

    1. inspect's own reader on the reply as written. An answer → done, unchanged.
    2. no answer → peel ONE layer from a copy: a wrapper right after each `ANSWER:` (see
       ``_WRAPPERS``) and a bold or underlined label (`**ANSWER:** B`). Read the copy again.
    3. still none → peel the next layer, at most ``MAX_LAYERS`` in all, then give up with
       inspect's own "no answer".

Worked example, key B: `ANSWER: $\\boxed{B}$` → inspect reads nothing (its lax pattern matches
only the space before `$`) → layer 1 gives `ANSWER: \\boxed{B}`, still nothing → layer 2 gives
`ANSWER: B` → B, graded 1. `ANSWER: B because it is red` has no wrapper, so the copy never
changes and it stays no answer, as inspect reads it.

INVARIANT: this file's source is hashed into the revision of every row it grades (the option
marking pin in ``benchmarks.py``, and ``scorer_source_pins`` for mathvista).
"""

from __future__ import annotations

import copy
import re

from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, Score, Scorer, Target
from inspect_ai.solver import TaskState
from inspect_ai.solver._multiple_choice import parse_answers

#: WHY 3: the deepest wrapping seen in real replies is two layers (`$\\boxed{B}$`); one more is
#: headroom. A cap keeps a reply of nested brackets from being peeled down to a stray letter.
MAX_LAYERS: int = 3

#: Where an answer starts: the label and the spaces after it.
_ANSWER_SITE: re.Pattern[str] = re.compile(r"(?i)ANSWER\s*:\s*")

#: A bold or underlined label, `**ANSWER:** B` or `**ANSWER**: B` → `ANSWER: B`.
_WRAPPED_LABEL: re.Pattern[str] = re.compile(r"(?i)(\*\*|__)(ANSWER)\s*(:)?\s*\1\s*(:)?")

#: The wrappers peeled right after `ANSWER:`, tried in this order; group 1 is what stays.
#: WHY this order: `$$…$$` before `$…$`, and a closed `$…$` before a lone leading `$`.
_WRAPPERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\\boxed\{([^{}\n]+)\}"),
    re.compile(r"\$\$([^$\n]+)\$\$"),
    re.compile(r"\$([^$\n]+)\$"),
    re.compile(r"\$()(?=[A-Za-z])"),
    re.compile(r"\*\*([^*\n]+)\*\*"),
    re.compile(r"__([^_\n]+)__"),
    re.compile(r"`([^`\n]+)`"),
    re.compile(r"\(([^()\n]+)\)"),
    re.compile(r"\[([^\[\]\n]+)\]"),
)


def _label(match: re.Match[str]) -> str:
    """`**ANSWER:**` → `ANSWER:`, keeping the colon wherever the reply put it."""

    return f"{match.group(2)}:" if match.group(3) or match.group(4) else match.group(0)


def peel_one_layer(reply: str) -> str:
    """The reply with one wrapper removed after each `ANSWER:`, and its label unwrapped."""

    text: str = _WRAPPED_LABEL.sub(_label, reply)
    pieces: list[str] = []
    kept_up_to: int = 0
    for site in _ANSWER_SITE.finditer(text):
        start: int = site.end()
        # WHY skip: a wrapper peeled at an earlier site already consumed this one.
        if start < kept_up_to:
            continue
        for wrapper in _WRAPPERS:
            hit: re.Match[str] | None = wrapper.match(text, start)
            if hit is not None:
                pieces += [text[kept_up_to:start], hit.group(1)]
                kept_up_to = hit.end()
                break
    pieces.append(text[kept_up_to:])
    return "".join(pieces)


def peeled_copies(reply: str) -> list[str]:
    """Each successive copy of the reply with one more layer peeled, at most ``MAX_LAYERS``."""

    copies: list[str] = []
    current: str = reply
    for _ in range(MAX_LAYERS):
        peeled: str = peel_one_layer(current)
        if peeled == current:
            break
        copies.append(peeled)
        current = peeled
    return copies


def _with_reply(state: TaskState, reply: str) -> TaskState:
    """A shallow copy of the state carrying another reply; the original is never touched."""

    probe: TaskState = copy.copy(state)
    probe.output = ModelOutput.from_content(model=state.output.model, content=reply)
    return probe


def parse_wrapped_answers(state: TaskState, multiple_correct: bool) -> set[str]:
    """inspect's ``parse_answers``, retried on peeled copies only when it finds no answer."""

    # Stage 1 — inspect's reading of the reply as written.
    answers: set[str] = parse_answers(state, multiple_correct)
    if answers:
        return answers
    # Stages 2-3 — one more layer peeled per try.
    for reply in peeled_copies(state.output.completion):
        answers = parse_answers(_with_reply(state, reply), multiple_correct)
        if answers:
            return answers
    return answers


async def peeled_score(scorer: Scorer, state: TaskState, target: Target) -> Score | None:
    """A pattern scorer's mark, retried on peeled copies only when it is not right.

    WHY retry on "not right" and not on "no match": `AnswerPattern.WORD` and `LINE` match
    `**Yes**` and capture the stars too, so the mark is wrong with a match. A copy only ever
    loses decoration, so a reply with no wrapper keeps its mark: `ANSWER: C` against key B has
    no layer to peel and stays wrong.
    """

    result: Score | None = await scorer(state, target)
    if result is None or result.value == CORRECT:
        return result
    for reply in peeled_copies(state.output.completion):
        retry: Score | None = await scorer(_with_reply(state, reply), target)
        if retry is not None and retry.value == CORRECT:
            # WHY the original reply as the explanation: the audit shows what the model wrote.
            return Score(
                value=retry.value,
                answer=retry.answer,
                explanation=state.output.completion,
                metadata=retry.metadata,
            )
    return result
