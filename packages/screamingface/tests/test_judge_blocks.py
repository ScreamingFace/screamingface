"""sf.Judge params keep their value types: a bool, an int and a float are three judges (GE21).

The sf.Reduce("judge", judge=...) block form was deleted in unit 7f (swap D7-8).
"""

from __future__ import annotations

from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import JudgeNode, fusion_node

from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer


def _url4(synthesizer: Reducer) -> str:
    fusion = fusion_node(members3(), synthesizer)
    return compile_candidate(fusion, operators=flow_operators()).url4


def test_judge_equality_and_hash_keep_the_param_value_types() -> None:
    # True == 1 == 1.0 in Python, but a bool, an int and a float compile to different url4 text.
    judges = [
        JudgeNode("provider/j", returns="label", rubric=RUBRIC, params={"temperature": value})
        for value in (True, 1, 1.0)
    ]

    assert judges[0] != judges[1] != judges[2]
    assert judges[0] != judges[2]
    assert len({hash(judge) for judge in judges}) == 3
    assert len({_url4(judge) for judge in judges}) == 3
    twin = JudgeNode("provider/j", returns="label", rubric=RUBRIC, params={"temperature": 1})
    assert twin == judges[1]
    assert hash(twin) == hash(judges[1])
    assert _url4(twin) == _url4(judges[1])
