"""Grading-time letter extraction and the exact-match grade. No judge, no tokens.

INVARIANT: this reads ARBITRARY text and takes the LAST match, because prose states its
conclusion at the end ("B is tempting, but the answer is D").

AIDEV-NOTE: this is NOT `answering.extract_choice_letter`, and merging them is the failure this
board is most exposed to. That one parses a trigger completion at answer time, where the
commitment comes FIRST; this one is the net for whatever text reaches grading. The prior
implementation applied the first-match parser to letter-last essays and measured 35.5% against a
true 70.2%. `test_medxpert_grading.py::test_the_two_parsers_disagree_on_a_letter_last_essay`
exists to make that collapse impossible to ship quietly.
"""

from __future__ import annotations

import re

# The whole answer is one letter, allowing punctuation or markdown: "D", "(B)", "**C**", "d,".
_WHOLE_LETTER_RE = re.compile(r"^[*_`\"'(\[]*([A-Ja-j])[)\]*_`\"'.:,;!?]*$")
# An explicit conclusion marker: "the answer is B", "final answer: D", "correct option is (E)".
_MARKER_RE = re.compile(
    r"(?:final\s+answer|correct\s+(?:answer|choice|option)|answer|option|choice)"
    r"\s*(?:is)?[\s:\-*_]*\(?([A-Ja-j])\)?(?![A-Za-z])",
    re.IGNORECASE,
)
# A letter decorated as a choice reference: "(E)" or "E)". Deliberately excludes "E." and "E:" —
# medical prose is full of "E. coli", and reading that as choice E would score microbiology
# questions against a letter the model never picked.
_DECORATED_RE = re.compile(r"\(([A-J])\)|\b([A-J])\)")
# Bare standalone uppercase letter. Uppercase-only so the article "a" never reads as choice A;
# the lookahead skips "E. coli"-style abbreviations.
_STANDALONE_RE = re.compile(r"\b([A-J])\b(?!\.\s*[a-z])")
# Standalone "A" and "I" are ordinary English words far more often than choices, so they are
# trusted only when nothing else is available.
_PRONOUN_LETTERS = frozenset({"A", "I"})


def extract_letter(text: str) -> str | None:
    """The intended choice letter — most-explicit strategy first, LAST occurrence within each.

    WHY a strategy ladder rather than one regex: the strategies disagree on purpose. A bare "D"
    means something different from "D)" mid-prose, which means something different again from a
    standalone D in a sentence — and the confidence we can place in each differs. Trying them in
    order of explicitness is what keeps "E. coli" and the article "a" from becoming answers.
    """

    if not text:
        return None
    for strategy in (_whole_letter, _marked_letter, _decorated_letter, _standalone_letter):
        found = strategy(text)
        if found is not None:
            return found
    return None


def _whole_letter(text: str) -> str | None:
    match = _WHOLE_LETTER_RE.match(text.strip())
    return match.group(1).upper() if match else None


def _marked_letter(text: str) -> str | None:
    markers = [
        match.group(1)
        for match in _MARKER_RE.finditer(text)
        # "the answer is a beta-blocker" is the article, not choice A. Keep a bare "a" only when
        # it terminates the clause ("Answer: a") or is wrapped ("answer is (a)").
        if not (
            match.group(1) == "a"
            and "(" not in match.group(0)
            and re.match(r"\s+[A-Za-z]", text[match.end() :])
        )
    ]
    return markers[-1].upper() if markers else None


def _decorated_letter(text: str) -> str | None:
    decorated = [first or second for first, second in _DECORATED_RE.findall(text)]
    return decorated[-1].upper() if decorated else None


def _standalone_letter(text: str) -> str | None:
    standalone = _STANDALONE_RE.findall(text)
    if not standalone:
        return None
    non_pronoun = [letter for letter in standalone if letter not in _PRONOUN_LETTERS]
    return (non_pronoun or standalone)[-1]


def grade(*, expected_answer: str, model_answer: str) -> dict[str, object]:
    """Compare a committed letter against the private key. Deterministic; spends no tokens.

    INVARIANT: an answer with no extractable letter is WRONG, not an error and not a skip. The
    official harness scores an empty prediction incorrect, and treating it as anything else would
    let a model improve its accuracy by declining to answer.
    """

    expected = extract_letter((expected_answer or "").strip())
    answered = extract_letter((model_answer or "").strip())
    correct = bool(expected and answered and expected == answered)
    return {
        "is_correct": correct,
        "answered": answered is not None,
        "expected": expected,
        "extracted": answered,
        "grading_method": "mcq_exact",
    }


__all__ = ["extract_letter", "grade"]
