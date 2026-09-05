"""Answer-time letter extraction — the verbatim-official parser.

INVARIANT under test: this parser reads a TRIGGER COMPLETION, where the model finishes the
sentence "…the answer is ___". The committed letter therefore comes FIRST, and first-match is
correct. It is deliberately NOT the grading-time parser, which reads prose and takes the LAST
match — see `test_medxpert_grading.py` and the crossover test that pins the difference.

FEATURE: MedXpertQA, graded against the published leaderboard, which requires this exchange.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.medxpert.answering import (
    extract_choice_letter,
    format_trigger,
)


def test_the_first_letter_in_range_wins() -> None:
    # WHY first: the text completes "…the answer is", so the commitment leads.
    assert extract_choice_letter("D. Because the glenoid is retroverted.", 10) == "D"


def test_an_echoed_trigger_is_cut_before_matching() -> None:
    # The official cleanser drops everything up to the trigger the model repeated back.
    trigger = "Therefore, among A through J, the answer is"
    assert extract_choice_letter(f"{trigger} F.", 10, trigger=trigger) == "F"


def test_the_trigger_echo_phrase_cannot_be_read_as_a_letter() -> None:
    # INVARIANT: "A through J" contains A and J. Without the phrase strip the parser would
    # return A on every echoed completion — the whole board would score as if it answered A.
    assert extract_choice_letter("A through J, the answer is C", 10) == "C"


def test_a_letter_beyond_this_rows_range_is_not_returned() -> None:
    # A four-option row must never yield "G"; the range is per-row, not fixed at J.
    assert extract_choice_letter("G", 4) is None


def test_no_letter_yields_none() -> None:
    # Callers turn this into "" so the grader scores the row wrong — the official
    # empty-prediction verdict. None is not "unknown", it is "no commitment".
    assert extract_choice_letter("no determination was possible", 10) is None
    assert extract_choice_letter("", 10) is None


def test_the_pronoun_i_is_read_as_choice_i_at_ten_options() -> None:
    """A faithful-port hazard, pinned so it is a known property and not a surprise.

    The official `answer_cleansing()` matches any in-range letter as a word, and on a 10-option
    row "I" is in range. So a model writing "I could not determine the answer" is scored as
    having chosen I. We reproduce this deliberately: D3 makes this parser verbatim-official, and
    silently diverging would make our numbers incomparable to the published leaderboard in a way
    no reader could see.

    AIDEV-NOTE: it is only reachable at >= 9 options, and only when the model writes a bare "I"
    in the committed span. Do not "fix" it without changing PROTOCOL_REVISION — that is a
    different exam.
    """

    assert extract_choice_letter("I could not determine the answer.", 10) == "I"
    assert extract_choice_letter("I could not determine the answer.", 4) is None


def test_format_trigger_spans_this_rows_option_count() -> None:
    assert format_trigger(10) == "Therefore, among A through J, the answer is"
    assert format_trigger(4) == "Therefore, among A through D, the answer is"


@pytest.mark.parametrize("count", [0, -1, 99])
def test_option_counts_are_clamped_into_the_alphabet(count: int) -> None:
    # WHY clamp rather than raise: prepare validates option shape, so a bad count here would be
    # an internal defect. Clamping keeps the parser total; the build is where rows are refused.
    assert format_trigger(count).startswith("Therefore, among A through ")
