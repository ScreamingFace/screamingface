"""MuSiQue's three numbers per Case — the paper's scorer, reached through our thin wrapper.

Every expected value here is hand-checked against the official definitions (SQuAD-style token
F1 and exact match, max over the gold answer and its aliases; HotpotQA-style support F1 over
paragraph numbers). None of them is our choice: a wrapper that "improves" a number moves our
scores off the paper's (spec D8).

The worked Case throughout is the real dev Case `2hop__460946_294723`: gold answer
`Miquette Giraudy`, no aliases, supporting paragraphs {5, 10}.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.musique.answering import ExtractedReply, extract_reply
from screamingface_engine.benchmarks.musique.grading import (
    AnswerScore,
    score_answer,
    score_support,
)

_GOLD_ANSWER = "Miquette Giraudy"
_GOLD_SUPPORT = frozenset({5, 10})


@pytest.mark.parametrize(
    ("reply", "f1", "exact", "support_f1"),
    [
        pytest.param(
            "Supporting paragraphs: 10, 5\nAnswer: Miquette Giraudy", 1.0, 1, 1.0, id="clean"
        ),
        # `** Giraudy` normalises to `giraudy`: precision 1/1, recall 1/2, F1 = 2/3. Support {10}
        # against {5, 10} is the same arithmetic.
        pytest.param(
            "Supporting paragraphs: 10\n**Answer:** Giraudy", 2 / 3, 0, 2 / 3, id="markdown"
        ),
        # No support line: the official SupportMetric gives an empty prediction F1 0 against a
        # non-empty gold set — the flag, not the score, is what we add.
        pytest.param("Answer:\nMiquette Giraudy", 1.0, 1, 0.0, id="answer-on-next-line"),
        # The whole sentence is scored: 9 normalised tokens (`the` dropped), 2 match, so
        # precision 2/9, recall 1, F1 = 4/11.
        pytest.param(
            "The performer is Steve Hillage, whose partner is Miquette Giraudy.",
            4 / 11,
            0,
            0.0,
            id="no-lines",
        ),
    ],
)
def test_the_specs_reply_table_scores_as_hand_checked(
    reply: str, f1: float, exact: int, support_f1: float
) -> None:
    """INVARIANT: each row of the spec's "How a reply becomes three numbers" table holds end to
    end — parser, then the copied scorer — so the spec and the code cannot drift apart."""

    extracted: ExtractedReply = extract_reply(reply)
    answer: AnswerScore = score_answer(extracted.answer, _GOLD_ANSWER, [])

    assert answer.f1 == pytest.approx(f1)
    assert answer.exact == exact
    assert score_support(extracted.support, _GOLD_SUPPORT) == pytest.approx(support_f1)


def test_the_best_matching_alias_sets_the_answer_score() -> None:
    """PROTOCOL: the official AnswerMetric takes the max over `[answer] + answer_aliases`.

    Real Case `3hop1__454441_55349_651302`: gold `Denver`, alias `Denver, Colorado`. `Denver, CO`
    scores 2/3 against `Denver` (precision 1/2, recall 1) and 1/2 against the alias, so 2/3.
    """

    score: AnswerScore = score_answer("Denver, CO", "Denver", ["Denver, Colorado"])

    assert score.f1 == pytest.approx(2 / 3)
    assert score.exact == 0


def test_an_alias_can_earn_exact_match_after_normalisation() -> None:
    """The comma is punctuation, so `denver colorado` equals the alias once both are
    normalised — the alias, not the shorter gold answer, is the one that matches exactly."""

    score: AnswerScore = score_answer("denver colorado", "Denver", ["Denver, Colorado"])

    assert score.f1 == pytest.approx(1.0)
    assert score.exact == 1


def test_an_empty_prediction_scores_zero_not_an_error() -> None:
    """A Candidate that committed `Answer:` with nothing after it is wrong, not ungradeable."""

    score: AnswerScore = score_answer("", _GOLD_ANSWER, [])

    assert score.f1 == 0.0
    assert score.exact == 0


def test_the_answer_f1_is_always_a_float() -> None:
    """The upstream `compute_f1` returns the INT 0 or 1 on its early exits; a Named Score is a
    float on the wire, so the wrapper converts rather than leaking an int."""

    assert isinstance(score_answer("", _GOLD_ANSWER, []).f1, float)
    assert isinstance(score_answer(_GOLD_ANSWER, _GOLD_ANSWER, []).f1, float)


def test_both_support_sets_empty_count_as_full_agreement() -> None:
    """PROTOCOL: the official SupportMetric sets F1 to 1.0 when prediction and gold are both
    empty. Unreachable on MuSiQue-Ans (every Case has 2 to 4 supporting paragraphs), pinned so
    the wrapper never special-cases it differently."""

    assert score_support(frozenset(), frozenset()) == 1.0


def test_a_cited_number_outside_the_paragraphs_is_a_false_positive() -> None:
    """An out-of-range number is not dropped: it counts against precision, as upstream does.
    {5, 10, 99} against {5, 10}: precision 2/3, recall 1, F1 = 0.8."""

    assert score_support(frozenset({5, 10, 99}), _GOLD_SUPPORT) == pytest.approx(0.8)


def test_each_support_score_is_independent_of_the_previous_case() -> None:
    """The upstream SupportMetric ACCUMULATES across calls. A shared instance would make one
    Case's score the running mean of every Case before it; a fresh one per Case prevents that."""

    assert score_support(frozenset(), _GOLD_SUPPORT) == 0.0
    assert score_support(_GOLD_SUPPORT, _GOLD_SUPPORT) == 1.0
