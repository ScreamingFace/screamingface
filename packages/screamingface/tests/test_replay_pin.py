"""`replay_pin` checks a replay request before any grant call (E14 simplify, contract C6).

INVARIANT: the checks run in a fixed order and none needs the network, so a bad pin or a bad
candidate spends nothing and the grant request stays the first network call.
"""

from __future__ import annotations

from uuid import UUID

import pytest

import screamingface as sf
from screamingface._evaluation.replay import replay_pin
from screamingface._scoreboard.replay_pin import _ReplayPin

RECIPE = sf.Model("anthropic/claude-haiku-4-5", name="haiku")
OTHER_RECIPE = sf.Model("anthropic/claude-haiku-4-5", name="other")
RESULT_ID = UUID("3f0c5d0e-6f0b-4d75-a1f1-0c6f0b7d2a10")


def test_a_good_request_gives_the_parsed_pin() -> None:
    assert replay_pin(f" result:{RESULT_ID} ", RECIPE, "draco", 1) == _ReplayPin(
        f"result:{RESULT_ID}", "result"
    )


def test_a_list_of_one_recipe_is_one_candidate() -> None:
    assert replay_pin("kevins-best", [RECIPE], "draco", None) == _ReplayPin("kevins-best", "name")


def test_a_bad_pin_fails_before_a_bad_candidate_count() -> None:
    with pytest.raises(ValueError, match="invalid replay pin"):
        replay_pin("Not A Pin!", [RECIPE, OTHER_RECIPE], "draco", 1)


def test_a_pin_that_is_not_text_fails_before_a_bad_candidate_count() -> None:
    with pytest.raises(TypeError, match="replay must be a pin string"):
        replay_pin(7, [RECIPE, OTHER_RECIPE], "draco", 1)


def test_two_candidates_fail_after_a_good_pin() -> None:
    with pytest.raises(ValueError, match="exactly one Recipe"):
        replay_pin("kevins-best", [RECIPE, OTHER_RECIPE], "draco", 1)


def test_a_bad_benchmark_fails_before_the_candidate_count_check_is_reached() -> None:
    with pytest.raises(ValueError, match="benchmark must be a non-empty string"):
        replay_pin("kevins-best", [RECIPE, OTHER_RECIPE], " ", 1)


def test_a_bad_limit_fails_before_the_grant_call() -> None:
    with pytest.raises(ValueError):
        replay_pin("kevins-best", RECIPE, "draco", 0)
