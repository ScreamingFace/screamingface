"""sf.Reduce("median"|"mean") takes select= as sf.Median and sf.Mean do (E4b playground fix).

FEATURE: an author who copies select="value" from sf.Median to the median block gets the number,
not the nearest member's whole reply. select is a second name for the block mode: "value" is
mode="compute" and "nearest" is mode="select".
INVARIANT defended: the block keeps only the mode, so the select form and the mode form are one
block, with one repr and one url4.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from _nodes import ReduceNode, fusion_node, lowered
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.reducer import Reducer
from screamingface.url4 import _calls

LAST = sf.Extract("last_number")
FIELD = sf.Extract("field", path="answer")
CONFIDENCE = sf.signal("field:confidence")


# WHY the internal node: these rows check the block form (``ReduceNode``) and its select option;
# the surface spells the same reducers as ``sf.Median`` and ``sf.Mean``.
def _url4(synthesizer: Reducer | sf.Median | sf.Mean) -> str:
    if isinstance(synthesizer, sf.Median | sf.Mean):
        recipe: sf.Recipe = sf.Fanout(members3()) >> synthesizer
    else:
        recipe = fusion_node(members3(), synthesizer)
    return compile_candidate(recipe, operators=flow_operators()).url4


def _spec(synthesizer: Reducer) -> dict[str, Any]:
    root = build(_url4(synthesizer))
    assert isinstance(root, Expression)
    return json.loads(_calls(root)["synthesis_1"].raw_intent)


def test_median_block_select_is_a_second_name_for_mode() -> None:
    value = ReduceNode("median", extract=LAST, select="value")
    assert value == ReduceNode("median", mode="compute", extract=LAST)
    assert value.mode == "compute"
    assert "select" not in value.options
    assert repr(value) == (
        "Reduce('median', mode='compute', extract=Extract('last_number', normalize='numeric'))"
    )
    nearest = ReduceNode("median", extract=LAST, select="nearest")
    assert nearest == ReduceNode("median", extract=LAST)
    assert nearest.mode == "select"


def test_mean_block_select_is_a_second_name_for_mode() -> None:
    nearest = ReduceNode("mean", extract=LAST, select="nearest")
    assert nearest == ReduceNode("mean", mode="select", extract=LAST)
    assert nearest.mode == "select"
    value = ReduceNode("mean", extract=LAST, select="value")
    assert value == ReduceNode("mean", extract=LAST)
    assert value.mode == "compute"


@pytest.mark.parametrize(
    ("block", "named"),
    [
        (
            lambda: ReduceNode("median", extract=LAST, select="value"),
            lambda: sf.Median(select="value"),
        ),
        (
            lambda: ReduceNode("median", extract=LAST, select="nearest", weights=(1, 1, 3)),
            lambda: sf.Median(weights=(1, 1, 3)),
        ),
        (
            lambda: ReduceNode("mean", extract=LAST, select="nearest", weights=(1, 1, 2)),
            lambda: sf.Mean(select="nearest", weights=(1, 1, 2)),
        ),
        (lambda: ReduceNode("mean", extract=LAST, select="value"), lambda: sf.Mean()),
    ],
)
def test_numeric_block_select_compiles_to_the_named_form_bytes(block: Any, named: Any) -> None:
    assert _url4(block()) == _url4(named())


def test_s4_median_value_block_compiles_value_and_weighted_median() -> None:
    spec = _spec(ReduceNode("median", extract=FIELD, weights=CONFIDENCE, select="value"))
    assert spec["reducer"] == "median"
    assert spec["extract"] == {"args": {"path": "answer"}, "op": "json_field@1"}
    assert spec["normalize"] == {"args": {}, "op": "numeric@1"}
    assert spec["reduce"] == {"args": {}, "op": "weighted_median@1"}
    assert spec["select"] == {"args": {}, "op": "value@1"}
    assert spec["weights"] == {"signal": "field:confidence"}


@pytest.mark.parametrize(
    "make",
    [
        lambda: ReduceNode("median", extract=FIELD, weights=CONFIDENCE, select="value"),
        lambda: ReduceNode("median", extract=FIELD, select="nearest"),
        lambda: ReduceNode("mean", extract=FIELD, weights=CONFIDENCE, select="nearest"),
        lambda: ReduceNode("mean", extract=FIELD, select="value"),
    ],
)
def test_url4_round_trip_keeps_the_select_of_a_numeric_block(make: Any) -> None:
    authored: ReduceNode = make()
    url4 = _url4(authored)
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)
    recovered = lowered(namespace["candidate"]).synthesizer
    assert type(recovered) is ReduceNode
    assert recovered == authored
    assert recovered.mode == authored.mode
    assert compile_candidate(namespace["candidate"], operators=flow_operators()).url4 == url4


@pytest.mark.parametrize(
    ("op", "options", "message"),
    [
        (
            "median",
            {"extract": LAST, "select": "mean"},
            "sf.Reduce('median') option 'select' must be 'nearest' or 'value', not 'mean'",
        ),
        (
            "mean",
            {"extract": LAST, "select": "value@1"},
            "sf.Reduce('mean') option 'select' must be 'value' or 'nearest', not 'value@1'",
        ),
        (
            "median",
            {"extract": LAST, "select": 1},
            "sf.Reduce('median') option 'select' must be 'nearest' or 'value', not 1",
        ),
        (
            "median",
            {"mode": "compute", "extract": LAST, "select": "value"},
            "sf.Reduce('median') takes mode or select, not both",
        ),
        (
            "mean",
            {"mode": "select", "extract": LAST, "select": "nearest"},
            "sf.Reduce('mean') takes mode or select, not both",
        ),
        (
            "plurality",
            {"extract": LAST, "select": "value"},
            "sf.Reduce('plurality') does not take option 'select'; it takes extract",
        ),
        (
            "median",
            {"extract": LAST, "foo": 1},
            "sf.Reduce('median') does not take option 'foo'; it takes extract, weights, select",
        ),
        (
            "mean",
            {"extract": LAST, "foo": 1},
            "sf.Reduce('mean') does not take option 'foo'; it takes extract, weights, select",
        ),
    ],
)
def test_numeric_block_select_refusals(op: str, options: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        ReduceNode(op, **options)
