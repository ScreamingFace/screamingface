"""The built-in operators give the same bytes under every hash seed (FW-3; OME-1289 E4a, unit 2).

FEATURE: a replay of a vote or median Candidate must match the original byte for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
"""

from __future__ import annotations

from combine_golden_support import median_scenario, vote_scenario
from hash_seed_support import stdout_across_seeds

_SEEDS = range(20)
_SCRIPT = (
    "from combine_golden_support import median_scenario, vote_scenario\n"
    "print(vote_scenario(), end='\\0')\n"
    "print(median_scenario(), end='')\n"
)


def test_builtin_vote_and_median_are_identical_across_hash_seeds() -> None:
    expected = vote_scenario() + "\0" + median_scenario()
    assert set(stdout_across_seeds(_SCRIPT, _SEEDS)) == {expected}
