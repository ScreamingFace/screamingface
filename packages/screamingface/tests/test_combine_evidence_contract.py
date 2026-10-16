"""The SDK decodes the evidence the real Engine writes (OME-1289 E4a, unit 12).

The Engine's own test (``test_combine_evidence_contract_fixture.py``) builds
``evidence_cases.json`` from the real combine core and pins it. This test only READS that file.
It is a contract fixture, not an oracle: the Engine's output is whatever the file holds, and the
SDK must decode every entry strictly and write it back unchanged.

A missing file FAILS when the Engine app is present; the test is skipped only when the Engine app
directory is absent (an installed run).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, requires_engine_app

from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.combine_evidence import CombineEvidence

_CASES = COMBINE_CONTRACT / "evidence_cases.json"
_EXPECTED_NAMES = {
    "argmax_cost_min",
    "concat_collision",
    "filter_none_pass",
    "filter_pattern",
    "filter_threshold",
    "judge_label",
    "judge_scores",
    "mean_weighted_value",
    "median_nearest",
    "median_value",
    "merge_abstain",
    "merge_model_field",
    "pick",
    "projection",
    "rank_by_judge",
    "rank_by_signal",
    "rank_cut_not_met",
    "regex_no_match",
    "set_normalized",
    "vote_abstain",
    "vote_cost_signal",
    "vote_field_signal",
    "vote_judge_weights",
    "vote_one_failed",
    "vote_tie",
    "vote_weighted",
}
_EXPECTED_NAMES |= {"pick_output", "pick_output_missing"}  # E4b pick-output
_EXPECTED_NAMES |= {"vote_weight_excluded", "filter_signal_excluded"}  # E4b part 2 X1, X2
_EXPECTED_NAMES |= {"rank_min_cost", "rank_reduce_abstain"}  # E4b part 2 unit 3 rank and cut
_EXPECTED_NAMES |= {  # E4b part 5 unit 2: the five gate cases
    "vote_gate_abstain",
    "vote_gate_judge",
    "vote_gate_majority",
    "vote_gate_not_run",
    "vote_gate_writer",
}


def _cases() -> dict[str, Any]:
    assert _CASES.is_file(), f"missing Engine contract fixture {_CASES}"
    return json.loads(_CASES.read_text(encoding="utf-8"))


@requires_engine_app
def test_the_engine_fixture_holds_the_25_scenarios() -> None:
    assert set(_cases()) == _EXPECTED_NAMES


@requires_engine_app
@pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
def test_an_engine_evidence_decodes_and_round_trips_exactly(name: str) -> None:
    wire = _cases()[name]

    decoded = decode_combine_evidence(wire, f"Engine evidence {name}")

    assert isinstance(decoded, CombineEvidence)
    assert decoded.to_dict() == wire


@requires_engine_app
def test_sdk_decodes_every_engine_evidence_case_with_an_excluded_row() -> None:
    # E4b part 2 unit 2 (ES#5): the four excluded rows of the Engine fixture decode and round-trip.
    cases = _cases()
    excluded = {
        (name, row["member_id"], row["reason"])
        for name, wire in cases.items()
        for row in wire["members"]
        if row["status"] == "excluded"
    }
    assert excluded >= {
        ("filter_signal_excluded", "member_3", "no_signal"),
        ("mean_weighted_value", "member_2", "no_weight"),
        ("rank_cut_not_met", "member_2", "no_signal"),
        ("vote_weight_excluded", "member_3", "no_weight"),
    }
    for name in (
        "filter_signal_excluded",
        "mean_weighted_value",
        "rank_cut_not_met",
        "vote_weight_excluded",
    ):
        decoded = decode_combine_evidence(cases[name], f"Engine evidence {name}")
        assert decoded is not None
        assert decoded.to_dict() == cases[name]
