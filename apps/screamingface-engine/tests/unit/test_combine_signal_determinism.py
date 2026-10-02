"""Signal reducers give the same bytes under every hash seed (FW-3; OME-1289 E4a, unit 10E).

FEATURE: a replay of an argmax, rank-by-signal or filter Candidate must match the original byte
for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
"""

from __future__ import annotations

from combine_signal_scenarios import (
    argmax_scenario,
    pattern_scenario,
    rank_scenario,
    threshold_scenario,
)
from hash_seed_support import stdout_across_seeds

_SEEDS = range(20)
_SCRIPT = (
    "from combine_signal_scenarios import (\n"
    "    argmax_scenario, pattern_scenario, rank_scenario, threshold_scenario)\n"
    "print(argmax_scenario(), end='\\0')\n"
    "print(rank_scenario(), end='\\0')\n"
    "print(threshold_scenario(), end='\\0')\n"
    "print(pattern_scenario(), end='')\n"
)


def test_signal_reducers_are_identical_across_hash_seeds() -> None:
    expected = "\0".join(
        [argmax_scenario(), rank_scenario(), threshold_scenario(), pattern_scenario()]
    )
    assert set(stdout_across_seeds(_SCRIPT, _SEEDS)) == {expected}


def test_the_argmax_scenario_picks_the_first_of_the_tied_members() -> None:
    assert '"chosen":["member_2"]' in argmax_scenario()
    assert '"tie":true' in argmax_scenario()


def test_the_rank_scenario_keeps_the_first_of_the_tied_members_at_the_cut() -> None:
    assert '"chosen":["member_2","member_6","member_1"]' in rank_scenario()
    assert '"tie":true' in rank_scenario()


def test_the_threshold_scenario_keeps_members_at_the_limit() -> None:
    chosen = '"chosen":["member_1","member_3","member_4","member_6","member_7","member_9"]'
    assert chosen in threshold_scenario()


def test_the_pattern_scenario_keeps_the_matching_members() -> None:
    chosen = (
        '"chosen":["member_1","member_2","member_3","member_4","member_7","member_8","member_9"]'
    )
    assert chosen in pattern_scenario()
