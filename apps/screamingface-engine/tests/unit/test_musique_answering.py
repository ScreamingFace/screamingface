"""Reading a MuSiQue reply — the two lines the Candidate commits to at the end (spec D6, D7).

INVARIANT under test: the parser reads a model that may reason aloud first, so the LAST
`Answer:` and the LAST `Supporting paragraphs:` are the commitments. It never crashes and never
guesses: a missing line is reported as missing, and the grader decides what that scores.

FEATURE: MuSiQue-Ans grading. These values feed the copied official scorer, so a parser that
reads the wrong span moves every score.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.musique.answering import ExtractedReply, extract_reply


def test_a_clean_reply_yields_both_commitments() -> None:
    reply: ExtractedReply = extract_reply(
        "Paragraph 10 names Steve Hillage; paragraph 5 names his partner.\n"
        "Supporting paragraphs: 10, 5\n"
        "Answer: Miquette Giraudy"
    )

    assert reply == ExtractedReply(
        answer="Miquette Giraudy",
        answer_line=True,
        support=frozenset({5, 10}),
        support_line=True,
    )


def test_the_last_answer_label_wins_over_a_mention_while_reasoning() -> None:
    """WHY last (spec D6): a model thinking aloud writes "the answer: maybe X" before it
    commits. Taking the first label would score its discarded guess."""

    reply: ExtractedReply = extract_reply(
        "My first thought for the answer: Steve Hillage.\n"
        "But the question asks for the spouse.\n"
        "Supporting paragraphs: 10, 5\n"
        "Answer: Miquette Giraudy"
    )

    assert reply.answer == "Miquette Giraudy"


def test_the_last_support_label_wins_over_an_earlier_draft() -> None:
    reply: ExtractedReply = extract_reply(
        "Supporting paragraphs: 1, 2\nOn reflection those were decoys.\n"
        "Supporting paragraphs: 10, 5\nAnswer: Miquette Giraudy"
    )

    assert reply.support == frozenset({5, 10})


def test_labels_match_in_any_case() -> None:
    reply: ExtractedReply = extract_reply("SUPPORTING PARAGRAPHS: 3\nanswer: Denver")

    assert reply.answer == "Denver"
    assert reply.support == frozenset({3})
    assert reply.answer_line and reply.support_line


def test_markdown_around_the_label_is_left_for_the_official_normaliser() -> None:
    """`**Answer:** X` leaves `** X`. We do not pre-clean beyond whitespace: the official
    `normalize_answer` strips the `*` itself, and cleaning twice would be our rule, not theirs."""

    reply: ExtractedReply = extract_reply("**Supporting paragraphs:** 10, 5\n**Answer:** Giraudy")

    assert reply.answer == "** Giraudy"
    assert reply.support == frozenset({5, 10})


def test_an_empty_answer_label_line_takes_the_next_non_empty_line() -> None:
    """Some models put the label alone on a line and the value under it (spec D6)."""

    reply: ExtractedReply = extract_reply(
        "Supporting paragraphs:\n\n10, 5\nAnswer:\n\n  Miquette Giraudy  \n"
    )

    assert reply.answer == "Miquette Giraudy"
    assert reply.answer_line is True
    assert reply.support == frozenset({5, 10})


def test_an_answer_label_with_nothing_after_it_commits_to_an_empty_answer() -> None:
    """The label was written, so the line is NOT missing; the empty answer then scores 0."""

    reply: ExtractedReply = extract_reply("Supporting paragraphs: 10\nAnswer:")

    assert reply.answer == ""
    assert reply.answer_line is True


def test_a_reply_with_no_answer_label_is_scored_whole_and_flagged() -> None:
    """Spec D7: never a crash and never silent — the whole reply is the answer, and the flag
    says why its F1 is low."""

    reply: ExtractedReply = extract_reply(
        "  The performer is Steve Hillage, whose partner is Miquette Giraudy.  "
    )

    assert reply.answer == "The performer is Steve Hillage, whose partner is Miquette Giraudy."
    assert reply.answer_line is False


def test_a_reply_with_no_support_label_has_an_empty_set_and_is_flagged() -> None:
    reply: ExtractedReply = extract_reply("Answer: Miquette Giraudy")

    assert reply.support == frozenset()
    assert reply.support_line is False


def test_an_empty_reply_is_two_missing_lines_not_an_error() -> None:
    reply: ExtractedReply = extract_reply("")

    assert reply == ExtractedReply(
        answer="", answer_line=False, support=frozenset(), support_line=False
    )


def test_repeated_and_out_of_range_numbers_are_kept_as_a_set() -> None:
    """A repeat is one citation (the official metric takes a set); an out-of-range number is
    kept so the official metric counts it as a false positive rather than us forgiving it."""

    reply: ExtractedReply = extract_reply("Supporting paragraphs: 5, 5, 10, 99\nAnswer: X")

    assert reply.support == frozenset({5, 10, 99})


def test_words_on_the_support_line_contribute_no_numbers() -> None:
    reply: ExtractedReply = extract_reply(
        "Supporting paragraphs: paragraph [10] and ten, then #5\nAnswer: X"
    )

    assert reply.support == frozenset({5, 10})


def test_a_support_line_with_no_numbers_is_present_but_empty() -> None:
    """The line exists, so it is not flagged missing; it simply cites nothing (spec F5)."""

    reply: ExtractedReply = extract_reply("Supporting paragraphs: none\nAnswer: X")

    assert reply.support == frozenset()
    assert reply.support_line is True


def test_the_support_label_is_not_read_as_an_answer_on_the_same_line() -> None:
    """INVARIANT: the two labels never swallow each other. A model that writes both on one line
    must not have its paragraph numbers scored as part of its answer, or the reverse."""

    reply: ExtractedReply = extract_reply("Supporting paragraphs: 10, 5 Answer: Miquette Giraudy")

    assert reply.answer == "Miquette Giraudy"
    assert reply.support == frozenset({5, 10})


def test_an_answer_line_never_absorbs_a_support_label_written_after_it() -> None:
    reply: ExtractedReply = extract_reply("Answer: Miquette Giraudy Supporting paragraphs: 10, 5")

    assert reply.answer == "Miquette Giraudy"
    assert reply.support == frozenset({5, 10})


def test_a_support_label_on_the_line_after_an_empty_answer_label_is_not_the_answer() -> None:
    """The next-non-empty-line rule must not hand the support line to the answer."""

    reply: ExtractedReply = extract_reply("Answer:\nSupporting paragraphs: 10, 5")

    assert reply.answer == ""
    assert reply.support == frozenset({5, 10})


def test_windows_line_endings_read_the_same() -> None:
    reply: ExtractedReply = extract_reply(
        "Supporting paragraphs: 10, 5\r\nAnswer: Miquette Giraudy\r\n"
    )

    assert reply.answer == "Miquette Giraudy"
    assert reply.support == frozenset({5, 10})
