"""OME-791 crosscheck — EVERY choice must be finished before a permanent row is written.

FEATURE: one globally shared exact-request cache whose rows carry ``expires_at = NULL``.
A fill decision is therefore a permanent decision.

STORY: as a benchmark operator I send ``n=2`` and the provider finishes only the first
completion. The half-built pair is not stored, so the next identical request dispatches
again instead of replaying an answer that was never finished.

WHY THIS MODULE EXISTS SEPARATELY from ``test_global_cache_write_eligibility.py``: that
module drives the guard through the whole chat route and every one of its cases carries a
SINGLE choice, so it pins the route contract but is structurally unable to see the
later-choice question. These are direct unit tests of the predicate at the one boundary
the route-level suite does not reach.

THE HAZARD. ``n`` is KEYED (``parameters.py``; the same holds for openrouter and openai),
so ``n=2`` and ``n=1`` are different keys and a two-choice body is replayed only to another
two-choice request. That is exactly what makes an incomplete SECOND choice permanent: the
row is a faithful answer to a key that will be asked again. Judging only ``choices[0]``
stores it.

AIDEV-NOTE: the guard stays STRUCTURAL. It asks "did the provider declare this choice
finished", never "is the text any good". ``finish_reason: "length"`` is a finished answer
to a request that set ``max_tokens`` and MUST keep storing — see the dependency note on
``_is_a_whole_answer`` itself.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.routes.chat_cache_stage import _is_a_whole_answer

_COMPLETE: dict[str, Any] = {"message": {"content": "4"}, "finish_reason": "stop"}
_TRUNCATED: dict[str, Any] = {"message": {"content": "4"}, "finish_reason": "length"}
_NULL_REASON: dict[str, Any] = {"message": {"content": "4"}, "finish_reason": None}
_ABSENT_REASON: dict[str, Any] = {"message": {"content": "4"}}
_NO_MESSAGE: dict[str, Any] = {"delta": {"content": "4"}, "finish_reason": "stop"}


def _result(*choices: object) -> dict[str, Any]:
    return {"choices": list(choices)}


# --- the later-choice hazard, which is what this module is for --------------------------


def test_a_later_choice_that_never_finished_blocks_the_write() -> None:
    # The n=2 case the single-choice suite cannot express: choices[0] is a perfectly
    # good answer, so a guard that reads only the first choice stores the pair forever.
    assert _is_a_whole_answer(_result(_COMPLETE, _NULL_REASON)) is False


def test_a_later_choice_with_no_message_blocks_the_write() -> None:
    # A delta or a shell in the second slot is the same "not an answer" the first-choice
    # rule already refuses; position must not change the verdict.
    assert _is_a_whole_answer(_result(_COMPLETE, _NO_MESSAGE)) is False


def test_a_later_choice_with_an_absent_finish_reason_blocks_the_write() -> None:
    # INVARIANT: absent and explicit null are treated identically wherever they appear.
    # Distinguishing them would reward a provider for spelling an unfinished answer one
    # way rather than the other.
    assert _is_a_whole_answer(_result(_COMPLETE, _ABSENT_REASON)) is False


def test_a_later_choice_that_is_not_a_mapping_blocks_the_write() -> None:
    assert _is_a_whole_answer(_result(_COMPLETE, "not-a-choice")) is False


def test_an_incomplete_FIRST_choice_still_blocks_when_a_later_choice_is_whole() -> None:
    # The mirror of the hazard: widening the check must not accidentally let a good
    # later choice vouch for a bad first one.
    assert _is_a_whole_answer(_result(_NULL_REASON, _COMPLETE)) is False


def test_every_choice_finished_is_storable() -> None:
    # WHY this positive case is mandatory: a guard that refused every multi-choice
    # response would satisfy all four refusals above while silently un-caching all
    # ``n>1`` traffic — a regression the refusal-only tests could not see.
    assert _is_a_whole_answer(_result(_COMPLETE, _COMPLETE)) is True


def test_a_finished_pair_is_storable_even_when_one_was_truncated() -> None:
    # ``length`` is a FINISHED answer, not a partial one, and ``max_tokens`` is keyed.
    # The widened check must not start judging content.
    assert _is_a_whole_answer(_result(_TRUNCATED, _COMPLETE)) is True


def test_many_choices_are_all_checked_not_just_the_first_two() -> None:
    # Guards against a two-choice special case rather than a real quantifier.
    assert _is_a_whole_answer(_result(*([_COMPLETE] * 4))) is True
    assert _is_a_whole_answer(_result(*([_COMPLETE] * 4), _NULL_REASON)) is False


# --- the single-choice contract, restated so widening cannot regress it -----------------


@pytest.mark.parametrize(
    ("result", "storable"),
    [
        pytest.param(_result(_COMPLETE), True, id="finish_reason-stop"),
        pytest.param(_result(_TRUNCATED), True, id="finish_reason-length"),
        pytest.param(_result(_NULL_REASON), False, id="explicit-null-finish_reason"),
        pytest.param(_result(_ABSENT_REASON), False, id="absent-finish_reason"),
        pytest.param(_result(_NO_MESSAGE), False, id="a-choice-carrying-no-message"),
        pytest.param(_result(), False, id="an-empty-choices-list"),
        pytest.param({}, False, id="no-choices-key-at-all"),
        pytest.param({"choices": "not-a-list"}, False, id="choices-that-is-not-a-list"),
        pytest.param({"choices": None}, False, id="choices-that-is-null"),
    ],
)
def test_the_single_choice_contract_is_unchanged(result: dict[str, Any], storable: bool) -> None:
    """AIDEV-NOTE: deliberately duplicated from the route-level suite at the UNIT level.

    Those cases prove the route honours the guard; these prove the predicate itself
    still answers the same way after being widened to every choice. A change that
    satisfied the new quantifier by loosening the per-choice rule would pass the
    multi-choice tests above and be caught only here.
    """
    assert _is_a_whole_answer(result) is storable
