"""sf.Reduce: the generic block reducer over the op table (OME-1289 gap, BK#5-7, 9-10, 13).

STORY: as a researcher, I build a reducer from blocks, a wrong block fails when I build it, and
the same block compiles to the same combine call as its named form.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators
from _nodes import (
    ConcatNode,
    FilterNode,
    JudgeNode,
    MedianNode,
    MergeNode,
    PickNode,
    RankNode,
    ReduceNode,
    VoteNode,
    fusion_node,
)
from _reducer_fixtures import engine_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.blocks import Matches
from screamingface.reducer import Reducer

# WHY the internal nodes: this file checks the block reducer itself (ReduceNode), which the surface
# steps lower to; the ops other than plurality, weighted, median and mean go in 7f (swap D7-8).
LAST = sf.Extract("last_number")
NUMERIC = sf.Extract("last_number", normalize="numeric")
_OPS = (
    "plurality, weighted, argmax, top_k, filter, pick_field, concat, median, mean, judge, merge, "
    "context"
)


@pytest.mark.parametrize(
    ("op", "options", "missing"),
    [
        ("plurality", {}, "extract"),
        ("weighted", {"extract": LAST}, "weights"),
        ("weighted", {"weights": [1]}, "extract"),
        ("argmax", {}, "by_signal"),
        ("top_k", {"by_field": "a"}, "k"),
        ("filter", {}, "where"),
        ("pick_field", {"order": "max"}, "field"),
        ("median", {}, "extract"),
        ("judge", {}, "judge"),
        ("merge", {}, "fields"),
    ],
)
def test_reduce_without_required_option_raises_at_construction(
    op: str, options: dict[str, Any], missing: str
) -> None:
    with pytest.raises(ValueError, match=f"needs option '{missing}'"):
        ReduceNode(op, **options)


def test_reduce_without_exactly_one_selector_raises_at_construction() -> None:
    with pytest.raises(ValueError, match="exactly one of by, by_field, by_signal"):
        ReduceNode("top_k", k=2)
    with pytest.raises(ValueError, match="exactly one of by, by_field, by_signal"):
        ReduceNode("top_k", k=2, by_field="a", by_signal=sf.signal("cost_usd"))
    with pytest.raises(ValueError, match="exactly one of order, equals"):
        ReduceNode("pick_field", field="a")


def test_reduce_rejects_mode_the_op_does_not_have() -> None:
    for op, options in (("concat", {}), ("merge", {}), ("context", {})):
        with pytest.raises(ValueError, match="is a compute op"):
            ReduceNode(op, mode="select", **options)
    selectors: dict[str, dict[str, Any]] = {
        "plurality": {"extract": LAST},
        "weighted": {"extract": LAST, "weights": [1]},
        "argmax": {"by_signal": sf.signal("cost_usd")},
        "top_k": {"k": 1, "by_field": "a"},
        "filter": {"where": sf.matches("a")},
        "pick_field": {"field": "a", "order": "max"},
    }
    for op, options in selectors.items():
        with pytest.raises(ValueError, match="is a select op"):
            ReduceNode(op, mode="compute", **options)
    assert ReduceNode("median", mode="select", extract=LAST).mode == "select"
    assert ReduceNode("median", mode="compute", extract=LAST).mode == "compute"
    assert ReduceNode("median", extract=LAST).mode == "select"
    with pytest.raises(ValueError, match="mode must be 'select' or 'compute'"):
        ReduceNode("median", mode="foo", extract=LAST)  # type: ignore[arg-type]
    assert ReduceNode("concat") == ReduceNode("concat", mode="compute")
    assert ReduceNode("concat").mode == "compute"


def test_reduce_rejects_unknown_op_and_foreign_options() -> None:
    with pytest.raises(ValueError, match=_OPS):
        ReduceNode("trimmed_mean")
    with pytest.raises(TypeError):
        ReduceNode(3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"'plurality'.*'k'|'k'.*'plurality'"):
        ReduceNode("plurality", extract=LAST, k=2)
    with pytest.raises(ValueError, match="takes no options"):
        ReduceNode("context", k=1)
    with pytest.raises(TypeError, match="option 'by' must be an sf.Judge"):
        ReduceNode("top_k", k=2, by="x")
    with pytest.raises(TypeError, match="option 'judge' must be an sf.Judge"):
        ReduceNode("judge", judge="m")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="option 'fields' must be a mapping of field name"):
        ReduceNode("merge", fields=["a"])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="sf.Judge"):
        ReduceNode("judge", judge="m", rubric="r")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("op", "options", "error"),
    [
        ("weighted", {"extract": LAST, "weights": "123"}, TypeError),
        ("plurality", {"extract": "last_number"}, TypeError),
        ("top_k", {"k": 0, "by_field": "a"}, ValueError),
        ("top_k", {"k": 257, "by_field": "a"}, ValueError),
        ("top_k", {"k": True, "by_field": "a"}, TypeError),
        ("top_k", {"k": 1, "by_field": "a..b"}, ValueError),
        ("top_k", {"k": 1, "by_field": 3}, TypeError),
        ("top_k", {"k": 1, "by_signal": "cost_usd"}, TypeError),
        ("filter", {"where": "x"}, TypeError),
        ("argmax", {"by_signal": sf.signal("cost_usd"), "order": "up"}, ValueError),
        ("pick_field", {"field": "a", "equals": [1]}, TypeError),
        ("pick_field", {"field": "a", "equals": math.inf}, ValueError),
        ("pick_field", {"field": "a", "order": "max", "normalize": "nope"}, ValueError),
        ("concat", {"separator": ""}, ValueError),
        ("concat", {"separator": "x" * 1025}, ValueError),
        ("concat", {"separator": 3}, TypeError),
        ("concat", {"label": 1}, TypeError),
    ],
)
def test_reduce_rejects_bad_option_values(op: str, options: dict[str, Any], error: type) -> None:
    with pytest.raises(error):
        ReduceNode(op, **options)


def test_reduce_median_takes_only_the_numeric_normalizer_and_no_benchmark_rule() -> None:
    with pytest.raises(ValueError, match="numeric"):
        ReduceNode("median", extract=sf.Extract("last_number", normalize="text"))
    with pytest.raises(ValueError, match="benchmark"):
        ReduceNode("median", extract=sf.Extract("benchmark"))
    assert ReduceNode("median", extract=LAST).options["extract"] == NUMERIC


def _one_per_row() -> list[ReduceNode]:
    return [
        ReduceNode("plurality", extract=NUMERIC),
        ReduceNode("weighted", extract=NUMERIC, weights=[1, 2.5, 3]),
        ReduceNode("weighted", extract=NUMERIC, weights=sf.signal("field:c")),
        ReduceNode("argmax", by_signal=sf.signal("cost_usd"), order="min"),
        ReduceNode("top_k", k=2, by_field="a.b[0]", order="max"),
        ReduceNode("top_k", k=2, by_signal=sf.signal("latency_ms")),
        ReduceNode("filter", where=sf.matches("a+", ignore_case=True), extract=NUMERIC),
        ReduceNode("pick_field", field="verdict", normalize="text", equals="yes"),
        ReduceNode("pick_field", field="score", order="max"),
        ReduceNode("merge", fields={"summary": sf.FieldRule.model("provider/w", prompt="Write.")}),
        ReduceNode("concat", separator="\n--\n", label=True),
        ReduceNode("median", mode="compute", extract=LAST),
        ReduceNode(
            "judge",
            judge=JudgeNode("provider/j", returns="scores", rubric="r", params={"seed": 1}),
        ),
        ReduceNode("context"),
    ]


def test_equal_reduce_blocks_are_equal_and_hash_equal() -> None:
    for block in _one_per_row():
        twin = eval(block._python(), {"sf": sf})  # noqa: S307
        assert twin == block
        assert hash(twin) == hash(block)
        assert len({block, twin}) == 1
    assert ReduceNode("plurality", extract=LAST) != ReduceNode("plurality", extract=NUMERIC)
    assert ReduceNode("weighted", extract=LAST, weights=[1]) != ReduceNode(
        "weighted", extract=LAST, weights=[2]
    )
    assert ReduceNode("median", extract=LAST) == ReduceNode("median", extract=NUMERIC)
    assert hash(ReduceNode("median", extract=LAST)) == hash(ReduceNode("median", extract=NUMERIC))
    # Python's True == 1 == 1.0, but the three compile to different JSON: they are three blocks
    blocks = [ReduceNode("pick_field", field="a", equals=value) for value in (True, 1, 1.0)]
    assert blocks[0] != blocks[1] != blocks[2]
    assert blocks[0] != blocks[2]
    assert len({hash(block) for block in blocks}) == 3
    assert len(set(blocks)) == 3
    assert ReduceNode("median", mode="select", extract=LAST) != ReduceNode(
        "median", mode="compute", extract=LAST
    )


def test_reduce_names_follow_the_spec_reducers() -> None:
    names = {block.op: block.name for block in _one_per_row()}

    assert names == {
        "plurality": "vote",
        "weighted": "vote",
        "argmax": "pick",
        "top_k": "rank",
        "filter": "filter",
        "pick_field": "pick",
        "concat": "concat",
        "median": "median",
        "judge": "judge",
        "merge": "merge",
        "context": "context",
    }


def test_reduce_repr_shows_mode_only_when_not_the_default() -> None:
    assert repr(ReduceNode("median", mode="compute", extract=LAST)) == (
        "Reduce('median', mode='compute', extract=Extract('last_number', normalize='numeric'))"
    )
    assert repr(ReduceNode("median", extract=LAST)) == (
        "Reduce('median', extract=Extract('last_number', normalize='numeric'))"
    )
    assert repr(ReduceNode("concat")) == "Reduce('concat')"
    assert isinstance(sf.matches("a"), Matches)


def _compiled_text(reducer: ReduceNode, members: int = 3) -> str:
    return combine_spec_text(reducer, member_count=members, operators=engine_operators())


def test_only_ops_with_engine_operators_compile_at_this_unit() -> None:
    # every op but 'context' compiles now. 'context' is the first half of the Fusion recipe, and
    # only the recipe rewrite takes it (FR#10).
    with pytest.raises(ValueError, match="first half of the Fusion recipe"):
        _compiled_text(ReduceNode("context"))
    # the engine catalog fixture holds every built-in operator (one list with FLOW_OPERATOR_IDS),
    # so each op compiles against it
    reducers = {
        "pick": [
            ReduceNode("argmax", by_signal=sf.signal("cost_usd")),
            ReduceNode("pick_field", field="a", order="max"),
        ],
        "rank": [ReduceNode("top_k", k=1, by_field="a")],
        "filter": [ReduceNode("filter", where=sf.matches("a"))],
        "concat": [ReduceNode("concat")],
        "judge": [ReduceNode("judge", judge=JudgeNode("provider/j", returns="label", rubric="r"))],
    }
    for name, blocks in reducers.items():
        for block in blocks:
            assert json.loads(_compiled_text(block))["reducer"] == name
    # a signal-weighted block compiles since unit 7; only score:judge waits for the judge
    assert '"weights":{"signal":"field:c"}' in _compiled_text(
        ReduceNode("weighted", extract=LAST, weights=sf.signal("field:c"))
    )
    assert json.loads(_compiled_text(ReduceNode("plurality", extract=sf.Extract("json"))))
    with pytest.raises(ValueError, match="has 3 weights for 2 members"):
        fusion_node(
            ["provider/a", "provider/b"], ReduceNode("weighted", extract=LAST, weights=[1, 2, 3])
        )


def test_extract_benchmark_without_benchmark_raises() -> None:
    block = ReduceNode("plurality", extract=sf.Extract("benchmark"))

    with pytest.raises(ValueError, match="extract='benchmark' needs a benchmark"):
        _compiled_text(block)


def _roundtrip_cases() -> list[ReduceNode]:
    regex = {"pattern": r"Final: (\w+)\$'", "group": 1}
    cases: list[ReduceNode] = [
        ReduceNode("plurality", extract=sf.Extract("last_number", normalize=None)),
        ReduceNode("plurality", extract=sf.Extract("last_number", normalize="numeric")),
        ReduceNode("plurality", extract=sf.Extract("field", normalize="text", path="answer")),
        ReduceNode("plurality", extract=sf.Extract("regex", normalize=None, **regex)),  # type: ignore[arg-type]
        ReduceNode("plurality", extract=sf.Extract("regex", normalize="numeric", **regex)),  # type: ignore[arg-type]
        ReduceNode("plurality", extract=sf.Extract("inspect_aime", normalize="identity")),
        ReduceNode(
            "weighted", extract=sf.Extract("last_number", normalize="text"), weights=[1, 2.5, 3]
        ),
        ReduceNode(
            "weighted",
            extract=sf.Extract("regex", normalize="text", **regex),  # type: ignore[arg-type]
            weights=[1, 2.5, 3],
        ),
        ReduceNode("median", mode="select", extract=sf.Extract("last_number")),
        ReduceNode("median", mode="compute", extract=sf.Extract("boxed")),
    ]
    cases.extend(
        ReduceNode("judge", judge=JudgeNode("provider/j", returns=returns, rubric="Pick one."))  # type: ignore[arg-type]
        for returns in ("label", "scores")
    )
    cases.extend(
        [
            ReduceNode("argmax", by_signal=sf.signal("cost_usd"), order="min"),
            ReduceNode("argmax", by_signal=sf.signal("field:confidence")),
            ReduceNode("pick_field", field="score", order="min"),
            ReduceNode("pick_field", field="verdict", normalize="text", equals="yes"),
            ReduceNode("merge", fields={"a": sf.FieldRule.majority(normalize="text")}),
            ReduceNode("merge", fields={"s": sf.FieldRule.model("provider/w", prompt="Write.")}),
            ReduceNode("top_k", k=2, by_field="score"),
            ReduceNode("top_k", k=2, by_field="a.b[0]", order="min"),
            ReduceNode("top_k", k=1, by=JudgeNode("provider/j", returns="scores", rubric="Score.")),
            ReduceNode("top_k", k=2, by_signal=sf.signal("cost_usd"), order="min"),
            ReduceNode("top_k", k=2, by_signal=sf.signal("field:confidence")),
            ReduceNode("concat"),
            ReduceNode("concat", separator="\n--\n", label=False),
            ReduceNode("filter", where=sf.signal("field:confidence") >= 0.6),  # type: ignore[arg-type]
            ReduceNode("filter", where=sf.matches("yes", ignore_case=True)),
            ReduceNode(
                "filter", where=sf.matches("^y"), extract=sf.Extract("field", "text", path="answer")
            ),
        ]
    )
    return cases


def _named_or_block(reducer: ReduceNode) -> type[Reducer]:
    """What a url4 of this block is recovered as (BK#8): the named class when it fits exactly."""

    extract = reducer.options.get("extract")
    plain_vote = (
        reducer.op in ("plurality", "weighted")
        and isinstance(extract, sf.Extract)
        and not extract.args
    )
    named: dict[str, type[Reducer]] = {
        "median": MedianNode,
        "judge": JudgeNode,
        "argmax": PickNode,
        "pick_field": PickNode,
        "merge": MergeNode,
        "top_k": RankNode,
        "concat": ConcatNode,
        "filter": FilterNode,
    }
    return VoteNode if plain_vote else named.get(reducer.op, ReduceNode)


# a selection hands its result to the next stage, so it cannot end a candidate (10S)
_SELECTION_OPS = ("top_k", "concat", "filter")


@pytest.mark.parametrize("reducer", _roundtrip_cases(), ids=lambda value: repr(value)[:90])
def test_reduce_to_python_round_trips(reducer: ReduceNode) -> None:
    fusion = fusion_node(["provider/a", "provider/b", "provider/c"], reducer)
    selection = reducer.op in _SELECTION_OPS
    candidate: sf.Recipe = sf.Pipeline([fusion, "provider/next"]) if selection else fusion
    # the judge, argmax, pick, merge, top_k and concat ops come with the Engine's flow catalog,
    # not units 1-3
    flow = reducer.op in ("judge", "argmax", "pick_field", "merge", *_SELECTION_OPS)
    operators = flow_operators() if flow else engine_operators()
    url4 = compile_candidate(candidate, operators=operators).url4

    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102

    recovered = namespace["candidate"]
    synthesizer = (recovered.stages[0] if selection else recovered).synthesizer
    # The named form wins when it holds the spec exactly (Vote, Median, Judge, Pick, Merge, Rank,
    # Concat).
    assert type(synthesizer) is _named_or_block(reducer)
    if isinstance(synthesizer, ReduceNode):
        assert recovered == candidate
    assert compile_candidate(recovered, operators=operators).url4 == url4


def _spec(reducer: ReduceNode) -> dict[str, Any]:
    return json.loads(_compiled_text(reducer))


def test_reduce_from_spec_refuses_shapes_it_cannot_rebuild() -> None:
    plurality = _spec(ReduceNode("plurality", extract=NUMERIC))
    weighted = _spec(ReduceNode("weighted", extract=NUMERIC, weights=[1, 2, 3]))
    median = _spec(ReduceNode("median", extract=LAST))

    def changed(base: dict[str, Any], **change: Any) -> dict[str, Any]:
        return {**copy.deepcopy(base), **change}

    broken = [
        changed(plurality, reducer="judge"),
        changed(plurality, extract=None),
        changed(plurality, extract={"op": "boxed@1", "args": None}),
        changed(plurality, reduce=None),
        changed(plurality, select="first_holder@1"),
        changed(weighted, members="member_1"),
        changed(median, extract=None),
        changed(plurality, reduce={"op": "mode@1", "args": {"x": 1}}),
        changed(plurality, select={"op": "max_weight_holder@1", "args": {}}),
        changed(plurality, extract={"op": "bogus@1", "args": {}}),
        changed(plurality, extract={"op": "boxed@1", "args": {"x": 1}}),
        changed(plurality, normalize={"op": "bogus@1", "args": {}}),
        changed(plurality, weights={"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}),
        changed(weighted, weights={"member_1": 1.0, "member_2": 1.0, "member_9": 1.0}),
        changed(weighted, weights=None),
        changed(median, weights={"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}),
        changed(median, normalize={"op": "text@1", "args": {}}),
        changed(median, select={"op": "first_holder@1", "args": {}}),
        changed(median, reduce={"op": "mode@1", "args": {}}),
        {},
    ]
    for spec in broken:
        with pytest.raises(ValueError, match="this SDK version cannot rebuild"):
            ReduceNode._from_spec(spec)
    assert ReduceNode._from_spec(plurality) == ReduceNode("plurality", extract=NUMERIC)
    assert ReduceNode._from_spec(weighted) == ReduceNode(
        "weighted", extract=NUMERIC, weights=[1, 2, 3]
    )
    assert ReduceNode._from_spec(median) == ReduceNode("median", extract=LAST)
