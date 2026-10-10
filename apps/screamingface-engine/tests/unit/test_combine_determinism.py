"""Same inputs, same output, same evidence bytes (FW-3, FW-H3; OME-1289 E4a, unit 1).

FEATURE: a replay of a reducer Candidate must match the original byte for byte.
INVARIANT: no iteration order of a dict or set, and no hash seed, reaches an output.
"""

from __future__ import annotations

from combine_golden_support import (
    inspect_scenario,
    median_scenario,
    regex_scenario,
    set_scenario,
    vote_scenario,
)
from combine_scenarios import (
    argmax_scenario,
    concat_scenario,
    core_scenario,
    core_signal_scenario,
    label_scenario,
    merge_scenario,
    pattern_scenario,
    pick_scenario,
    projection_scenario,
    rank_selection_scenario,
    rank_signal_scenario,
    score_weight_scenario,
    scores_scenario,
    threshold_scenario,
)
from hash_seed_support import stdout_across_seeds

_SEEDS = range(20)
_SCENARIO_NAMES = [
    "vote_scenario",
    "median_scenario",
    "regex_scenario",
    "set_scenario",
    "inspect_scenario",
    "core_scenario",
    "core_signal_scenario",
    "merge_scenario",
    "pick_scenario",
    "projection_scenario",
    "scores_scenario",
    "label_scenario",
    "score_weight_scenario",
    "rank_selection_scenario",
    "concat_scenario",
    "argmax_scenario",
    "rank_signal_scenario",
    "threshold_scenario",
    "pattern_scenario",
]

_SCRIPT = (
    "from combine_golden_support import (\n"
    "    inspect_scenario, median_scenario, regex_scenario, set_scenario, vote_scenario)\n"
    "from combine_scenarios import (\n"
    "    argmax_scenario, concat_scenario, core_scenario, core_signal_scenario, label_scenario,\n"
    "    merge_scenario, pattern_scenario, pick_scenario, projection_scenario,\n"
    "    rank_selection_scenario, rank_signal_scenario, score_weight_scenario,\n"
    "    scores_scenario, threshold_scenario)\n"
    "scenarios = [\n"
    "    vote_scenario, median_scenario, regex_scenario, set_scenario, inspect_scenario,\n"
    "    core_scenario, core_signal_scenario,\n"
    "    merge_scenario, pick_scenario, projection_scenario,\n"
    "    scores_scenario, label_scenario, score_weight_scenario,\n"
    "    rank_selection_scenario, concat_scenario,\n"
    "    argmax_scenario, rank_signal_scenario, threshold_scenario, pattern_scenario,\n"
    "]\n"
    "print('\\0'.join(scenario() for scenario in scenarios), end='')\n"
)


def _expected() -> str:
    scenarios = (
        vote_scenario,
        median_scenario,
        regex_scenario,
        set_scenario,
        inspect_scenario,
        core_scenario,
        core_signal_scenario,
        merge_scenario,
        pick_scenario,
        projection_scenario,
        scores_scenario,
        label_scenario,
        score_weight_scenario,
        rank_selection_scenario,
        concat_scenario,
        argmax_scenario,
        rank_signal_scenario,
        threshold_scenario,
        pattern_scenario,
    )
    return "\0".join(scenario() for scenario in scenarios)


def test_combine_output_and_evidence_are_identical_across_hash_seeds() -> None:
    expected = _expected()
    assert all(expected.split("\0")), "every scenario must produce real output"
    results = stdout_across_seeds(_SCRIPT, _SEEDS)
    assert set(results) == {expected}
