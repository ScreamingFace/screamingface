"""Pick and merge give the same bytes under every hash seed (FW-3; OME-1289 E4a, unit 9).

FEATURE: a replay of a Pick or Merge Candidate must match the original byte for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
"""

from __future__ import annotations

import json

from combine_fields_scenarios import merge_scenario, pick_scenario, projection_scenario
from hash_seed_support import stdout_across_seeds

_SEEDS = range(20)
_SCRIPT = (
    "from combine_fields_scenarios import merge_scenario, pick_scenario, projection_scenario\n"
    "print(merge_scenario(), end='\\0')\n"
    "print(pick_scenario(), end='\\0')\n"
    "print(projection_scenario(), end='')\n"
)


def test_pick_and_merge_are_identical_across_hash_seeds() -> None:
    expected = "\0".join((merge_scenario(), pick_scenario(), projection_scenario()))
    assert set(stdout_across_seeds(_SCRIPT, _SEEDS)) == {expected}


def test_the_pick_scenario_takes_the_first_of_the_tied_members() -> None:
    assert pick_scenario().startswith('{"answer"')
    assert '"chosen":["member_1"]' in pick_scenario()


def test_the_merge_scenario_builds_the_declared_fields_only() -> None:
    assert merge_scenario().startswith('{"answer":')
    assert '"summary":"A summary \u00e9."' in merge_scenario().split("\n")[0]
    assert "nused" not in merge_scenario().split("\n")[0]


def test_the_projection_scenario_lists_members_in_canonical_order() -> None:
    projection = json.loads(projection_scenario().split("\n")[0])
    assert list(projection) == sorted(f"member_{index}" for index in range(1, 13))
