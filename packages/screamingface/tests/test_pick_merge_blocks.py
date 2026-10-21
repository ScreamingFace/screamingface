"""sf.Reduce("pick_field") and sf.Reduce("merge") are the block forms of sf.Pick and sf.Merge.

FEATURE: a block and its named form compile to the same combine call (OME-1289, BK#4, 9S F4/F5).
INVARIANT: the canonical block holds what the named form holds. A Pick keeps its target as text, so
``equals=7`` and ``equals="7"`` are one block. A Merge keeps its field order, so it changes the
bytes. Equal blocks hash equal, and a bool, an int and a float stay three different values.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from _nodes import MergeNode, PickNode, ReduceNode, fusion_node

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.fields import _FieldRules
from screamingface.reducer import Reducer

_WRITER = sf.FieldRule.model("provider/w", prompt="Write.")


# WHY the internal nodes: the pick_field and merge blocks go in 7f (swap D7-8), so these rows
# compare them with the nodes they name; the surface Merge is ``sx.Merge``.
def _url4(synthesizer: Reducer | sf.Merge) -> str:
    if isinstance(synthesizer, sf.Merge):
        recipe: sf.Recipe = sf.Fanout(members3()) >> synthesizer
    else:
        recipe = fusion_node(members3(), synthesizer)
    return compile_candidate(recipe, operators=flow_operators()).url4


_PAIRS: list[tuple[str, ReduceNode, Reducer]] = [
    (
        "order-max",
        ReduceNode("pick_field", field="confidence", order="max"),
        PickNode("confidence", order="max"),
    ),
    (
        "equals-7-numeric",
        ReduceNode("pick_field", field="answer", equals=7, normalize="numeric"),
        PickNode("answer", equals=7, normalize="numeric"),
    ),
    (
        "merge-model-field",
        ReduceNode("merge", fields={"summary": _WRITER}),
        MergeNode({"summary": _WRITER}),
    ),
]


@pytest.mark.parametrize(
    ("block", "named"), [pair[1:] for pair in _PAIRS], ids=[p[0] for p in _PAIRS]
)
def test_every_op_table_row_matches_its_named_form(block: ReduceNode, named: Reducer) -> None:
    assert _url4(block) == _url4(named)


def test_pick_and_merge_blocks_canonical_equality_hash_and_errors() -> None:
    _check_canonical_equality_and_hash()
    _check_errors()


def _check_canonical_equality_and_hash() -> None:
    # F5: a Pick stores its target as text, so a number and its text are one block
    assert ReduceNode("pick_field", field="x", equals=7) == ReduceNode(
        "pick_field", field="x", equals="7"
    )
    assert ReduceNode("pick_field", field="x", order="max").options == {
        "field": "x",
        "order": "max",
    }
    assert ReduceNode("pick_field", field="x", equals=7, normalize="numeric").options == {
        "field": "x",
        "normalize": "numeric",
        "equals": "7",
    }
    # the three JSON spellings stay three blocks
    assert len({ReduceNode("pick_field", field="x", equals=value) for value in (True, 1, 1.0)}) == 3

    one = ReduceNode("merge", fields={"a": sf.FieldRule.majority(), "b": _WRITER})
    twin = ReduceNode("merge", fields={"a": sf.FieldRule.majority(), "b": _WRITER})
    assert one == twin
    assert hash(one) == hash(twin)
    assert len({one, twin}) == 1
    assert isinstance(one.options["fields"], _FieldRules)
    assert repr(one.options["fields"]).startswith(
        "{'a': FieldRule.majority(), 'b': FieldRule.model("
    )
    assert one._python().startswith("sf.Reduce('merge', fields={'a': sf.FieldRule.majority()")

    # the field order is the spec order, so it is part of the block
    ab = ReduceNode("merge", fields={"a": sf.FieldRule.max(), "b": sf.FieldRule.max()})
    ba = ReduceNode("merge", fields={"b": sf.FieldRule.max(), "a": sf.FieldRule.max()})
    assert ab != ba
    assert _url4(ab) != _url4(ba)

    # the block also takes the canonical value of another block
    assert ReduceNode("merge", fields=one.options["fields"]) == one  # type: ignore[arg-type]


def _check_errors() -> None:
    # F5: the Pick refusals carry the block prefix
    prefix = r"sf\.Reduce\('pick_field'\): "
    bad: list[tuple[dict[str, Any], str]] = [
        (
            {"field": "x", "equals": "y", "normalize": "set"},
            "normalize must be 'text' or 'numeric'",
        ),
        ({"field": "x", "order": "max", "normalize": "text"}, "normalize applies to equals only"),
        ({"field": "x", "equals": " "}, "equals must not be blank"),
    ]
    for options, message in bad:
        with pytest.raises(ValueError, match=prefix + ".*" + message):
            ReduceNode("pick_field", **options)
    # the path cap is the block's own check (10S): the op-table message, not the Pick's
    with pytest.raises(ValueError, match=r"sf\.Reduce\('pick_field'\) option 'field'.*256"):
        ReduceNode("pick_field", field="a" * 257, order="max")

    with pytest.raises(ValueError, match=r"from_member\(4\).*needs 4 members"):
        fusion_node(members3(), ReduceNode("merge", fields={"a": sf.FieldRule.from_member(4)}))
    with pytest.raises(TypeError, match=r"sf\.Reduce\('merge'\) option 'fields' must be a mapping"):
        ReduceNode("merge", fields=[])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"sf\.Reduce\('merge'\): Merge needs at least one field"):
        ReduceNode("merge", fields={})


def test_field_rule_params_are_compared_by_type_and_value() -> None:
    # GE21: Python's True == 1 == 1.0, but the three compile to different JSON
    rules = [
        sf.FieldRule.model("provider/w", prompt="Write.", params={"seed": value})
        for value in (True, 1, 1.0)
    ]

    assert rules[0] != rules[1] != rules[2]
    assert rules[0] != rules[2]
    assert len(set(rules)) == 3
    blocks = [ReduceNode("merge", fields={"a": rule}) for rule in rules]
    assert len(set(blocks)) == 3
    assert blocks[0] != blocks[1] != blocks[2]
    merges = [sf.Merge({"a": rule}) for rule in rules]
    assert merges[0] != merges[1] != merges[2]
    assert len({_url4(merge) for merge in merges}) == 3

    same = sf.FieldRule.model("provider/w", prompt="Write.", params={"seed": 1})
    assert same == rules[1]
    assert hash(same) == hash(rules[1])
    assert _url4(sf.Merge({"a": same})) == _url4(merges[1])
    assert _FieldRules((("a", rules[0]),)) != _FieldRules((("a", rules[1]),))
    assert _FieldRules((("a", rules[1]),)) == _FieldRules((("a", same),))
    assert hash(_FieldRules((("a", rules[1]),))) == hash(_FieldRules((("a", same),)))
