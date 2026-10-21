"""sf.FieldRule params in sf.Merge: equal values compile alike, and a bool, an int and a float stay
three different values (GE21).

The sf.Reduce("pick_field") and sf.Reduce("merge") block forms were deleted in unit 7f (swap D7-8).
"""

from __future__ import annotations

from _combine_flow_fixtures import flow_operators, members3

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate


def _url4(merge: sf.Merge) -> str:
    return compile_candidate(sf.Fanout(members3()) >> merge, operators=flow_operators()).url4


def test_field_rule_params_are_compared_by_type_and_value() -> None:
    # GE21: Python's True == 1 == 1.0, but the three compile to different JSON
    rules = [
        sf.FieldRule.model("provider/w", prompt="Write.", params={"seed": value})
        for value in (True, 1, 1.0)
    ]

    assert rules[0] != rules[1] != rules[2]
    assert rules[0] != rules[2]
    assert len(set(rules)) == 3
    merges = [sf.Merge({"a": rule}) for rule in rules]
    assert merges[0] != merges[1] != merges[2]
    assert len({_url4(merge) for merge in merges}) == 3

    same = sf.FieldRule.model("provider/w", prompt="Write.", params={"seed": 1})
    assert same == rules[1]
    assert hash(same) == hash(rules[1])
    assert _url4(sf.Merge({"a": same})) == _url4(merges[1])
