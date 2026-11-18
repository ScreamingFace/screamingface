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
    2. no answer → peel ONE layer from a copy, at the LAST `ANSWER:` only: a bold or
       underlined label (`**ANSWER:** B`) and the wrapper right after it (see ``_WRAPPERS``).
       When the answer is a list, every later answer on that line is unwrapped too, so
       `ANSWER: (A) (B) (C) (D)` becomes `ANSWER: A B C D`, the hedge inspect refuses, and is
       never read as its first letter. Read the copy again.
       WHY the last only: inspect's strict pass prefers an `ANSWER:` that starts a line over a
       later one mid-line, so peeling a retracted draft (`ANSWER: (A)` ... `Final ANSWER: $C$`)
       would make the draft win. The final answer is the last one, as inspect's prompt asks.
    3. still none → peel the next layer, at most ``MAX_LAYERS`` in all, then give up with
       inspect's own "no answer".
    4. a peeled reading that leaves out an option letter the reply names after its last
       `ANSWER:` is a hedge: `ANSWER: (A)/(B)` peels to `ANSWER: A/B`, which inspect's fallback
       reads as A, so it is read as no answer instead. INVARIANT: grading never rewards a
       hedge. inspect's own reading of a reply (stage 1) is never second-guessed.

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

from inspect_ai._util.answer import answer_character
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, Score, Scorer, Target
from inspect_ai.solver import TaskState
from inspect_ai.solver._multiple_choice import parse_answers

#: WHY 3: the deepest wrapping seen in real replies is two layers (`$\\boxed{B}$`); one more is
#: headroom. A cap keeps a reply of nested brackets from being peeled down to a stray letter.
MAX_LAYERS: int = 3

#: Where an answer starts: the label and the spaces after it.
_ANSWER_SITE: re.Pattern[str] = re.compile(r"(?i)ANSWER\s*:\s*")

#: An answer label, bare or wrapped (`ANSWER:`, `**ANSWER:**`, `__ANSWER__:`); the last one is
#: the only site the peel touches.
_LABEL: re.Pattern[str] = re.compile(r"(?i)(?:\*\*|__)?ANSWER(?:\*\*|__)?\s*:")

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

#: A single letter, number or word: what a later answer in a wrapped list holds (`[B]`).
_ONE_WORD: re.Pattern[str] = re.compile(r"[A-Za-z\d]+")

#: A capital letter standing alone, as a reply names an option: the B in `(B)`, `$B$`, `A/B`.
_LONE_LETTER: re.Pattern[str] = re.compile(r"(?<![A-Za-z\d])[A-Z](?![A-Za-z\d])")


def _label(match: re.Match[str]) -> str:
    """`**ANSWER:**` → `ANSWER:`, keeping the colon wherever the reply put it."""

    return f"{match.group(2)}:" if match.group(3) or match.group(4) else match.group(0)


def peel_one_layer(reply: str) -> str:
    """The reply with one layer peeled at its last `ANSWER:`: the label unwrapped, then one
    wrapper removed from the answer and from each later answer listed on its line. Every
    earlier part of the reply is kept as written."""

    labels: list[re.Match[str]] = list(_LABEL.finditer(reply))
    if not labels:
        return reply
    head: str = reply[: labels[-1].start()]
    tail: str = _WRAPPED_LABEL.sub(_label, reply[labels[-1].start() :], count=1)
    site: re.Match[str] | None = _ANSWER_SITE.match(tail)
    hit: re.Match[str] | None = None
    if site is not None:
        # The first wrapper in ``_WRAPPERS`` order that opens right after the label.
        hit = next(
            (found for wrapper in _WRAPPERS if (found := wrapper.match(tail, site.end()))), None
        )
    if hit is not None:
        line_end: int = tail.find("\n", hit.end())
        line_end = len(tail) if line_end < 0 else line_end
        rest: str = _peel_listed_answers(tail[hit.end() : line_end], hit.re)
        tail = tail[: hit.start()] + hit.group(1) + rest + tail[line_end:]
    return head + tail


def _peel_listed_answers(rest: str, kind: re.Pattern[str]) -> str:
    """The rest of the answer line with each later answer unwrapped once, so a wrapped list
    reads as its bare form: `(A) (B) (C)` → `A B C`, which inspect refuses as a hedge.

    Peeled: every wrapper of the first answer's ``kind`` (`**A**, **B**`), and any wrapper
    around a single letter or word (the `[B]` in `(A), [B]`). WHY not every wrapper: prose
    after the answer keeps its brackets, so `$B$ (the second option)` still reads B, as its
    bare form does. One pass over the line as written, so a nested wrapper loses one layer per
    try and ``MAX_LAYERS`` still caps the depth.
    """

    found: list[re.Match[str]] = sorted(
        (
            match
            for wrapper in _WRAPPERS
            for match in wrapper.finditer(rest)
            if wrapper is kind or _ONE_WORD.fullmatch(match.group(1))
        ),
        key=lambda match: (match.start(), -match.end()),
    )
    pieces: list[str] = []
    cursor: int = 0
    for match in found:
        if match.start() < cursor:  # inside, or overlapping, a wrapper already peeled
            continue
        pieces.append(rest[cursor : match.start()] + match.group(1))
        cursor = match.end()
    pieces.append(rest[cursor:])
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
            # Stage 4 — a hedge check on the peeled reading only (inspect's own is kept above).
            return set() if _named_letters(state) - answers else answers
    return answers


def _named_letters(state: TaskState) -> set[str]:
    """Every option letter the reply names, standing alone, after its last `ANSWER:`.

    WHY: inspect's fallback pattern stops at the first character that is not a letter, digit,
    space or comma, so the peeled hedge `ANSWER: A/B` (from `ANSWER: (A)/(B)`) reads as A, and
    so do `ANSWER: (A) - no wait, (B)` and letters on separate lines. A peeled reading that
    leaves out an option letter the reply names is a hedge, read as no answer, as on main.
    Only capitals count, so the article "a" never does. The check runs only on a peeled
    reading, a reply main scored 0, so a wrong refusal can never cost a grade main gave.
    """

    labels: list[re.Match[str]] = list(_LABEL.finditer(state.output.completion))
    if not labels:
        return set()
    options: set[str] = {answer_character(index) for index in range(len(state.choices))}
    named: set[str] = {
        found.group(0) for found in _LONE_LETTER.finditer(state.output.completion, labels[-1].end())
    }
    return named & options


async def peeled_score(scorer: Scorer, state: TaskState, target: Target) -> Score | None:
    """A pattern scorer's mark, retried on peeled copies only when it is not right.

    INVARIANT: only for a scorer whose pattern reads the LAST `ANSWER:`. inspect_ai v0.3.263's
    `AnswerPattern.LETTER` and `WORD` end in `(?!.*ANSWER\\s*:)` and `LINE` anchors on the end
    of the reply, so a retracted draft earlier in the reply can never be read. A scorer using a
    plain first-match `re.search` would read the first site instead: do not pass one here.

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
