"""Rank and concat give the same bytes under every hash seed (FW-3; OME-1289 E4a, unit 10).

FEATURE: a replay of a rank or concat Candidate must match the original byte for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
"""

from __future__ import annotations

from combine_selection_scenarios import concat_scenario, rank_scenario
from hash_seed_support import stdout_across_seeds

_SEEDS = range(20)
_SCRIPT = (
    "from combine_selection_scenarios import concat_scenario, rank_scenario\n"
    "print(rank_scenario(), end='\\0')\n"
    "print(concat_scenario(), end='')\n"
)


def test_rank_and_concat_are_identical_across_hash_seeds() -> None:
    expected = rank_scenario() + "\0" + concat_scenario()
    assert set(stdout_across_seeds(_SCRIPT, _SEEDS)) == {expected}


def test_the_rank_scenario_keeps_the_first_of_the_tied_members_at_the_cut() -> None:
    assert '"chosen":["member_3","member_9","member_1","member_5","member_7"]' in rank_scenario()
    assert '"tie":true' in rank_scenario()


def test_the_concat_scenario_flags_the_separator_collision() -> None:
    assert '"separator_collision":true' in concat_scenario()
