"""The built-in operators give the same bytes under every hash seed (FW-3; OME-1289 E4a, unit 2).

FEATURE: a replay of a vote or median Candidate must match the original byte for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
RX#12: the regex, set and Inspect-rule operators hold to it too (F22: the Chinese decimal-word set
of the vendored rule is iterated in hash order, and the result must not depend on it).
"""

from __future__ import annotations

from combine_golden_support import (
    inspect_scenario,
    median_scenario,
    regex_scenario,
    set_scenario,
    vote_scenario,
)
from hash_seed_support import stdout_across_seeds

_SEEDS = range(20)
_SCRIPT = (
    "from combine_golden_support import (\n"
    "    inspect_scenario, median_scenario, regex_scenario, set_scenario, vote_scenario)\n"
    "print(vote_scenario(), end='\\0')\n"
    "print(median_scenario(), end='\\0')\n"
    "print(regex_scenario(), end='\\0')\n"
    "print(set_scenario(), end='\\0')\n"
    "print(inspect_scenario(), end='')\n"
)


def _expected() -> str:
    scenarios = (vote_scenario, median_scenario, regex_scenario, set_scenario, inspect_scenario)
    return "\0".join(scenario() for scenario in scenarios)


def test_builtin_vote_and_median_are_identical_across_hash_seeds() -> None:
    expected = _expected()
    assert all(expected.split("\0")), "every scenario must produce real output"
    assert set(stdout_across_seeds(_SCRIPT, _SEEDS)) == {expected}
