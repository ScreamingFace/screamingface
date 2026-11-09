"""The sum source on the wire: old data keeps its shape, the spec schema names the sum (E4b part 6).

FEATURE: the combine spec ``signals`` union gets the member ``{"source": "sum", ...}``
(signal-sum PRD SM-D5, erd §7).
STORY: as a maintainer, I see that no existing spec, url4 fixture or evidence case holds a sum, and
that the pinned spec v1 schema names the new union member with its two required keys.
INVARIANT defended: SU-I5 (a spec with no sum keeps its bytes); the schema change is additive,
with no new schema id. The lists are FIXED (test-plan §6), never a glob, so a later unit that
adds a case or a url4 file does not turn this file red.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from screamingface_engine.combine.spec import COMBINE_SPEC_SCHEMA, parse_spec

_DATA = Path(__file__).parent / "data" / "combine_contract"
SCHEMAS = _DATA / "schemas"

# test-plan §6 L37: the 37 evidence case names on base 633fec3a1. A fixed list, never the file.
L37 = (
    "argmax_cost_min",
    "concat_collision",
    "filter_none_pass",
    "filter_pattern",
    "filter_signal_excluded",
    "filter_threshold",
    "judge_label",
    "judge_scores",
    "mean_weighted_value",
    "median_nearest",
    "median_value",
    "merge_abstain",
    "merge_model_field",
    "pick",
    "pick_output",
    "pick_output_missing",
    "projection",
    "rank_by_judge",
    "rank_by_signal",
    "rank_cut_not_met",
    "rank_min_cost",
    "rank_reduce_abstain",
    "regex_no_match",
    "set_normalized",
    "vote_abstain",
    "vote_cost_signal",
    "vote_field_signal",
    "vote_gate_abstain",
    "vote_gate_judge",
    "vote_gate_majority",
    "vote_gate_not_run",
    "vote_gate_writer",
    "vote_judge_weights",
    "vote_one_failed",
    "vote_tie",
    "vote_weight_excluded",
    "vote_weighted",
)
# test-plan §6 L47: the 47 url4 files on base 633fec3a1. A fixed list, never a glob.
L47 = (
    "argmax_cost_candidate.url4",
    "corrective_vote_candidate.url4",
    "entropy_pick_min_candidate.url4",
    "filter_judge_candidate.url4",
    "filter_pipeline_candidate.url4",
    "gate_abstain_vote_candidate.url4",
    "gate_judge_vote_candidate.url4",
    "gate_verbalized_vote_candidate.url4",
    "gate_writer_vote_candidate.url4",
    "judge_order_min_candidate.url4",
    "judge_vote_candidate.url4",
    "logprob_entropy_shared_candidate.url4",
    "logprob_filter_mean_candidate.url4",
    "logprob_filter_prob_candidate.url4",
    "logprob_pick_mean_candidate.url4",
    "logprob_pick_sum_candidate.url4",
    "logprob_rank_mean_candidate.url4",
    "logprob_samples_pick_candidate.url4",
    "logprob_steer_filter_candidate.url4",
    "logprob_vote_prob_candidate.url4",
    "model_synthesizer_candidate.url4",
    "quorum_judge_vote_candidate.url4",
    "quorum_vote_candidate.url4",
    "recipe_s1.url4",
    "recipe_s10.url4",
    "recipe_s11_max.url4",
    "recipe_s12.url4",
    "recipe_s13.url4",
    "recipe_s14.url4",
    "recipe_s15.url4",
    "recipe_s16.url4",
    "recipe_s2.url4",
    "recipe_s3.url4",
    "recipe_s4.url4",
    "recipe_s4_median.url4",
    "recipe_s5.url4",
    "recipe_s5_pick_output.url4",
    "recipe_s7.url4",
    "recipe_s8.url4",
    "recipe_s8_pick_output.url4",
    "recipe_s9.url4",
    "samples_vote_candidate.url4",
    "signal_vote_candidate.url4",
    "two_reducers_candidate.url4",
    "verbalized_vote_candidate.url4",
    "vote_candidate.url4",
    "weighted_median_confidence_candidate.url4",
)
# The files of L47 that do not hold exactly one combine spec (counted on 633fec3a1).
_SPEC_COUNTS = {
    "corrective_vote_candidate.url4": 2,
    "model_synthesizer_candidate.url4": 0,
    "two_reducers_candidate.url4": 2,
}
_SPEC_START = '{"extract":'  # canonical JSON sorts the keys, so every spec starts here


def _combine_specs(text: str) -> list[str]:
    """Every combine spec text in one url4 file (a spec may sit in a quoted loop body)."""
    decoder = json.JSONDecoder()
    specs: list[str] = []
    start = text.find(_SPEC_START)
    while start != -1:
        _, end = decoder.raw_decode(text, start)
        specs.append(text[start:end])
        start = text.find(_SPEC_START, end)
    return specs


def _pinned(schema_id: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / f"{schema_id}.json").read_text(encoding="utf-8"))


# --- SM#1 (CHAR): no existing spec, url4 fixture or evidence case holds a sum ------------------


def test_existing_specs_and_evidence_have_no_sum_source() -> None:
    total = 0
    for name in L47:
        specs = _combine_specs((_DATA / name).read_text(encoding="utf-8"))
        assert len(specs) == _SPEC_COUNTS.get(name, 1), name
        for text in specs:
            signals = parse_spec(text).signals or {}
            assert all(entry.source != "sum" for entry in signals.values()), name
        total += len(specs)
    assert total == 48

    cases = json.loads((_DATA / "evidence_cases.json").read_text(encoding="utf-8"))
    for name in L37:
        declared = cases[name].get("declared") or {}
        assert all(entry["source"] != "sum" for entry in declared.values()), name


# --- SM#13 (PIN): the pinned spec v1 schema names the sum source -------------------------------


def test_spec_schema_snapshot_holds_the_sum_source() -> None:
    schema = _pinned(COMBINE_SPEC_SCHEMA)

    assert "SumSource" in schema["$defs"]
    sum_source = schema["$defs"]["SumSource"]
    assert sum_source["required"] == ["source", "coefficients"]
    assert sum_source["additionalProperties"] is False
    assert sum_source["properties"]["source"]["const"] == "sum"
    coefficients = sum_source["properties"]["coefficients"]
    assert (coefficients["minProperties"], coefficients["maxProperties"]) == (1, 7)
    assert coefficients["additionalProperties"] == {"type": "number"}
    union = schema["properties"]["signals"]["anyOf"][0]["additionalProperties"]
    assert union["discriminator"]["mapping"]["sum"] == "#/$defs/SumSource"
    assert {"$ref": "#/$defs/SumSource"} in union["oneOf"]
