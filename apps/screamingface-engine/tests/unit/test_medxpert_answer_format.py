"""MedXpertQA's page states the answer format its grader reads, and the statement is true.

FEATURE: answer format on the Benchmark page (OME-1906). medxpert is hand-built core code, so
its sentence lives in its own definition rather than in the inspect plugin's `answer_formats`
package; this file holds it to the same rule: every reply the sentence quotes grades the way
the sentence says, through the real grader.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.medxpert import grading
from screamingface_engine.benchmarks.medxpert.definition import ANSWER_FORMAT, MEDXPERT

#: The key the quoted replies are written for.
_KEY: str = "D"
_ACCEPTED: tuple[str, ...] = ("D", "(D)", "**D**", "the answer is D")
_REJECTED: tuple[str, ...] = ("not sure",)


def test_the_page_ends_with_the_answer_format() -> None:
    assert MEDXPERT.description.endswith(" " + ANSWER_FORMAT)


@pytest.mark.parametrize("reply", [*_ACCEPTED, *_REJECTED])
def test_every_graded_reply_is_quoted_on_the_page(reply: str) -> None:
    """INVARIANT: the replies under test are exactly what the submitter reads."""

    assert f"'{reply}'" in ANSWER_FORMAT


@pytest.mark.parametrize("reply", _ACCEPTED)
def test_a_reply_the_page_accepts_is_graded_right(reply: str) -> None:
    assert grading.grade(expected_answer=_KEY, model_answer=reply)["is_correct"] is True


@pytest.mark.parametrize("reply", _REJECTED)
def test_a_reply_with_no_option_letter_scores_zero(reply: str) -> None:
    graded: dict[str, object] = grading.grade(expected_answer=_KEY, model_answer=reply)

    assert graded["is_correct"] is False
    assert graded["answered"] is False
