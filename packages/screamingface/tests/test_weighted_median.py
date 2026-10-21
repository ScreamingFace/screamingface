"""sf.Median(weights=...) and the median block compile to weighted_median@1 (E4b, WM#1, WM#13-14).

FEATURE: a median with weights is a weighted median; a median without weights keeps its bytes.
STORY: as an SDK author, I write sf.Median(weights=(1, 1, 3)) or sf.Median(over="field:x",
weights=sf.signal(...)), and the Candidate runs the weighted median in the Engine.
INVARIANT: an unweighted median compiles to the same url4 bytes as before; weights round-trip
through url4; a judge signal is refused because a Median has no judge.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from _combine_contract import engine_operators
from _combine_flow_fixtures import flow_operators
from _nodes import MedianNode, ReduceNode, fusion_node, lowered

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec

_MEMBERS3 = ["provider/a", "provider/b", "provider/c"]
_UNWEIGHTED_TEXT = (
    '{"extract":{"args":{},"op":"last_number@1"},"members":["member_1","member_2","member_3"],'
    '"normalize":{"args":{},"op":"numeric@1"},"reduce":{"args":{},"op":"median@1"},'
    '"reducer":"median","schema":"screamingface.combine-spec.v1",'
    '"select":{"args":{},"op":"nearest@1"},"weights":null}'
)
_VALUE_SELECT_TEXT = (
    '{"extract":{"args":{},"op":"last_number@1"},"members":["member_1","member_2","member_3"],'
    '"normalize":{"args":{},"op":"numeric@1"},"reduce":{"args":{},"op":"median@1"},'
    '"reducer":"median","schema":"screamingface.combine-spec.v1",'
    '"select":{"args":{},"op":"value@1"},"weights":null}'
)


def test_sdk_median_without_weights_compiles_the_same_bytes() -> None:
    text = combine_spec_text(MedianNode(), member_count=3, operators=engine_operators())
    assert text == _UNWEIGHTED_TEXT
    block = ReduceNode("median", extract=sf.Extract("last_number"))
    assert (
        combine_spec_text(block, member_count=3, operators=engine_operators()) == _UNWEIGHTED_TEXT
    )
    value_text = combine_spec_text(
        MedianNode(select="value"), member_count=3, operators=engine_operators()
    )
    assert value_text == _VALUE_SELECT_TEXT
    assert repr(MedianNode()) == "Median(extract='last_number', select='nearest')"


def test_sdk_median_with_weights_compiles_weighted_median() -> None:
    spec = decode_combine_spec(
        combine_spec_text(
            MedianNode(weights=(1, 1, 3)), member_count=3, operators=engine_operators()
        )
    )
    assert spec["reducer"] == "median"
    assert spec["reduce"] == {"op": "weighted_median@1", "args": {}}
    assert spec["select"] == {"op": "nearest@1", "args": {}}
    assert spec["normalize"] == {"op": "numeric@1", "args": {}}
    assert spec["extract"] == {"op": "last_number@1", "args": {}}
    assert spec["weights"] == {"member_1": 1.0, "member_2": 1.0, "member_3": 3.0}

    signal_spec = decode_combine_spec(
        combine_spec_text(
            MedianNode(select="value", weights=sf.signal("field:confidence")),
            member_count=3,
            operators=engine_operators(),
        )
    )
    assert signal_spec["select"] == {"op": "value@1", "args": {}}
    assert signal_spec["weights"] == {"signal": "field:confidence"}

    assert (
        repr(MedianNode(weights=(1, 1, 3)))
        == "Median(extract='last_number', select='nearest', weights=(1.0, 1.0, 3.0))"
    )


def test_sdk_reduce_block_median_accepts_weights_and_round_trips() -> None:
    block = ReduceNode(
        "median",
        extract=sf.Extract("field", path="answer"),
        weights=sf.signal("field:confidence"),
    )
    spec = decode_combine_spec(combine_spec_text(block, member_count=3, operators=flow_operators()))
    assert spec["extract"] == {"op": "json_field@1", "args": {"path": "answer"}}
    assert spec["reduce"] == {"op": "weighted_median@1", "args": {}}
    assert spec["select"] == {"op": "nearest@1", "args": {}}
    assert spec["weights"] == {"signal": "field:confidence"}

    fusion = fusion_node(_MEMBERS3, block)
    url4 = compile_candidate(fusion, operators=flow_operators()).url4
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    assert type(lowered(namespace["candidate"]).synthesizer) is ReduceNode
    assert lowered(namespace["candidate"]).synthesizer == block
    assert compile_candidate(namespace["candidate"], operators=flow_operators()).url4 == url4

    block_text = combine_spec_text(
        ReduceNode(
            "median",
            mode="compute",
            extract=sf.Extract("last_number"),
            weights=(1, 1, 3),
        ),
        member_count=3,
        operators=engine_operators(),
    )
    median_text = combine_spec_text(
        MedianNode(select="value", weights=(1, 1, 3)),
        member_count=3,
        operators=engine_operators(),
    )
    assert block_text == median_text


def test_sdk_median_with_weights_round_trips_through_url4() -> None:
    fusion = sf.Fanout(_MEMBERS3) >> sf.Median(weights=(1, 1, 3))
    url4 = compile_candidate(fusion, operators=engine_operators()).url4
    code = sf.Url4(url4).to_python()
    assert "weights=(1.0, 1.0, 3.0)" in code
    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 - our own generated code
    synthesizer = lowered(namespace["candidate"]).synthesizer
    assert type(synthesizer) is MedianNode
    assert synthesizer.weights == (1.0, 1.0, 3.0)
    again = fusion_node(_MEMBERS3, synthesizer)
    assert compile_candidate(again, operators=engine_operators()).url4 == url4


def test_sdk_median_weights_refuse_bad_input() -> None:
    with pytest.raises(ValueError, match="has 2 weights for 3 members"):
        _ = sf.Fanout(_MEMBERS3) >> sf.Median(weights=(1, 2))
    with pytest.raises(ValueError, match="has no judge"):
        sf.Median(weights=sf.signal("score:judge"))
    with pytest.raises(ValueError, match="has no judge"):
        sf.Median(over=sf.Extract("last_number"), weights=sf.signal("score:judge"))
    with pytest.raises(TypeError, match="must be a sequence of numbers"):
        sf.Median(weights=("a", "b", "c"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="greater than zero"):
        sf.Median(weights=(1, 0, 1))
    # a string is a signal key on the surface, so the block refuses a key it does not declare
    undeclared = (
        "a step reads sf.signal('abc'), which this sf.Fanout does not declare (declared: none)"
    )
    with pytest.raises(ValueError, match=f"^{re.escape(undeclared)}$"):
        _ = sf.Fanout(_MEMBERS3) >> sf.Median(weights="abc")
