"""The judge reducers give the same bytes under every hash seed (FW-3; OME-1289 E4a, unit 8).

FEATURE: a replay of a judge Candidate must match the original byte for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
"""

from __future__ import annotations

import json

from combine_judge_scenarios import label_scenario, score_weight_scenario, scores_scenario
from hash_seed_support import stdout_across_seeds

_SEEDS = range(20)
_SCRIPT = (
    "from combine_judge_scenarios import label_scenario, score_weight_scenario, scores_scenario\n"
    "print(scores_scenario(), end='\\0')\n"
    "print(label_scenario(), end='\\0')\n"
    "print(score_weight_scenario(), end='')\n"
)


def test_judge_reducers_are_identical_across_hash_seeds() -> None:
    expected = scores_scenario() + "\0" + label_scenario() + "\0" + score_weight_scenario()
    assert set(stdout_across_seeds(_SCRIPT, _SEEDS)) == {expected}


def test_the_scores_scenario_picks_the_first_of_the_tied_members() -> None:
    assert scores_scenario().startswith("member 4: ")


def test_the_score_weight_scenario_ties_two_rows_and_picks_the_first_holder() -> None:
    result = score_weight_scenario()
    assert result.startswith("member 1: ")
    evidence = json.loads(result.partition("\n")[2])
    assert evidence["tie"] is True
    assert [row["score"] for row in evidence["tally"][:2]] == [1.0, 1.0]
