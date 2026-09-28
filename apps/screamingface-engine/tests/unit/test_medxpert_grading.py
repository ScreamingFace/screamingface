"""Grading-time letter extraction and the exact-match grade — the lenient prose net.

INVARIANT under test: this parser reads ARBITRARY text and takes the LAST match, because prose
states its conclusion at the end ("B is tempting, but the answer is D"). It is deliberately NOT
the answer-time parser — see the crossover test at the bottom, which is the 35-point regression
the prior implementation shipped.

INVARIANT under test: an answer with no letter is WRONG, never rescued.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.medxpert.answering import extract_choice_letter
from screamingface_engine.benchmarks.medxpert.grading import extract_letter, grade


def test_prose_concludes_at_the_end() -> None:
    assert extract_letter("B is tempting, but the answer is D.") == "D"


def test_a_bare_letter_answer_is_read() -> None:
    assert extract_letter("D") == "D"
    assert extract_letter("**C**") == "C"
    assert extract_letter("(B)") == "B"


def test_the_e_coli_guard() -> None:
    # WHY: medical text is full of "E. coli". Reading that as choice E would silently score
    # microbiology questions against a letter the model never chose.
    assert extract_letter("The culture grew E. coli, so the answer is H.") == "H"


def test_the_article_a_guard() -> None:
    # "the answer is a beta-blocker" is the English article, not choice A.
    assert extract_letter("The answer is a beta-blocker, specifically option G.") == "G"


def test_an_empty_answer_grades_wrong() -> None:
    # INVARIANT: the official harness treats an empty prediction as incorrect. It must not be
    # rescued, and it must not be an error either — it is simply wrong.
    row = grade(expected_answer="C", model_answer="")
    assert row["is_correct"] is False
    assert row["grading_method"] == "mcq_exact"


def test_a_matching_letter_is_correct() -> None:
    assert grade(expected_answer="C", model_answer="C")["is_correct"] is True


def test_a_mismatched_letter_is_incorrect() -> None:
    assert grade(expected_answer="C", model_answer="D")["is_correct"] is False


def test_grading_is_deterministic() -> None:
    first = grade(expected_answer="C", model_answer="C")
    assert first == grade(expected_answer="C", model_answer="C")


def test_the_two_parsers_disagree_on_a_letter_last_essay() -> None:
    """The 35-point regression, pinned forever.

    A one-shot prompt with the trigger appended produces an essay that REJECTS options before
    committing at the end. The answer-time parser takes the first in-range letter and returns the
    rejected distractor; the grading-time parser takes the last and returns the real verdict.

    INVARIANT: these two must stay different functions. The prior implementation applied the
    first-match parser to essays like this and measured 35.5% against a true 70.2%. If this test
    ever passes with both parsers agreeing, someone has collapsed them — and the board's scores
    silently halve.
    """

    # AIDEV-NOTE: no "answer is" phrase on purpose. With it, the answer-time parser's official
    # trigger fallback splits there and recovers — which is why the bug needed a real essay to
    # surface. An essay that merely weighs options and concludes is the shape that breaks it.
    essay = "Option B is plausible but the retroversion argues against it. Option D fits best."
    assert extract_choice_letter(essay, 10) == "B"  # first in-range letter: the REJECTED one
    assert extract_letter(essay) == "D"  # the actual commitment
