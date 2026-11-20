"""MedXpertQA's page describes the parser that actually scores, not the one beside it.

FEATURE: answer format on the Benchmark page (OME-1906). The sentence once described
`grading.extract_letter` (last letter wins), which never runs when a Case is scored; scoring
runs `answering.extract_choice_letter` on the turn-2 reply (first letter wins). A user read the
page, wrote a prose commit, and lost points to a stray article "A". These tests grade every
reply the sentence quotes through the scoring parser, called the way the check route calls it.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.medxpert.answering import (
    extract_choice_letter,
    format_trigger,
)
from screamingface_engine.benchmarks.medxpert.definition import ANSWER_FORMAT

#: MedXpertQA Text rows carry ten options, A to J.
_OPTIONS: int = 10
#: The key the quoted replies are written for.
_KEY: str = "D"
_COUNTED_AS_KEY: tuple[str, ...] = (
    "D",
    "(D)",
    "**D**",
    "the answer is D",
    "the answer is D. B would be wrong.",
)
#: A prose-first reply: the article "A" stands alone before the intended D.
_PROSE_FIRST: str = "A humeral shaft fracture, so D"
_NO_LETTER: str = "not sure"


def _committed(reply: str) -> str | None:
    """The letter the check route commits for ``reply`` (runtime `_check`'s exact call)."""

    return extract_choice_letter(reply, _OPTIONS, trigger=format_trigger(_OPTIONS))


@pytest.mark.parametrize("reply", [*_COUNTED_AS_KEY, _PROSE_FIRST, _NO_LETTER])
def test_every_reply_the_scoring_test_grades_is_quoted_on_the_page(reply: str) -> None:
    """INVARIANT: the replies graded below are exactly what the submitter reads."""

    assert f"'{reply}'" in ANSWER_FORMAT


@pytest.mark.parametrize("reply", _COUNTED_AS_KEY)
def test_a_reply_the_page_counts_as_d_commits_d(reply: str) -> None:
    assert _committed(reply) == _KEY


def test_a_prose_first_reply_commits_its_first_standalone_capital() -> None:
    """WHY pinned: this is the trap the page warns about. The first standalone capital wins,
    so the article "A" is committed and the intended D is never read."""

    assert _committed(_PROSE_FIRST) == "A"


def test_a_reply_with_no_option_letter_commits_nothing() -> None:
    assert _committed(_NO_LETTER) is None


def test_the_page_tells_recipe_authors_to_commit_the_letter_alone() -> None:
    assert "letter alone" in ANSWER_FORMAT


def test_the_page_no_longer_claims_the_last_letter_wins() -> None:
    """WHY: "last" describes `grading.extract_letter`, which is not on the scoring path."""

    assert "last" not in ANSWER_FORMAT
