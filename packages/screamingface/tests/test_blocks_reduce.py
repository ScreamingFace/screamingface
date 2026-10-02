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
from _reducer_fixtures import FixtureVote, engine_operators, fixture_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.blocks import Matches, Reduce
from screamingface.reducer import Reducer

LAST = sf.Extract("last_number")
NUMERIC = sf.Extract("last_number", normalize="numeric")
_OPS = (
    "plurality, weighted, argmax, top_k, filter, pick_field, concat, median, judge, merge, context"
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
        sf.Reduce(op, **options)


def test_reduce_without_exactly_one_selector_raises_at_construction() -> None:
    with pytest.raises(ValueError, match="exactly one of by, by_field, by_signal"):
        sf.Reduce("top_k", k=2)
    with pytest.raises(ValueError, match="exactly one of by, by_field, by_signal"):
        sf.Reduce("top_k", k=2, by_field="a", by_signal=sf.signal("cost_usd"))
    with pytest.raises(ValueError, match="exactly one of order, equals"):
        sf.Reduce("pick_field", field="a")


def test_reduce_rejects_mode_the_op_does_not_have() -> None:
    for op, options in (("concat", {}), ("merge", {}), ("context", {})):
        with pytest.raises(ValueError, match="is a compute op"):
            sf.Reduce(op, mode="select", **options)
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
            sf.Reduce(op, mode="compute", **options)
    assert sf.Reduce("median", mode="select", extract=LAST).mode == "select"
    assert sf.Reduce("median", mode="compute", extract=LAST).mode == "compute"
    assert sf.Reduce("median", extract=LAST).mode == "select"
    with pytest.raises(ValueError, match="mode must be 'select' or 'compute'"):
        sf.Reduce("median", mode="foo", extract=LAST)  # type: ignore[arg-type]
    assert sf.Reduce("concat") == sf.Reduce("concat", mode="compute")
    assert sf.Reduce("concat").mode == "compute"


def test_reduce_rejects_unknown_op_and_foreign_options() -> None:
    with pytest.raises(ValueError, match=_OPS):
        sf.Reduce("mean")
    with pytest.raises(TypeError):
        sf.Reduce(3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"'plurality'.*'k'|'k'.*'plurality'"):
        sf.Reduce("plurality", extract=LAST, k=2)
    with pytest.raises(ValueError, match="takes no options"):
        sf.Reduce("context", k=1)
    with pytest.raises(ValueError, match="arrives with sf.Rank"):
        sf.Reduce("top_k", k=2, by="x")
    with pytest.raises(ValueError, match="arrives with sf.Judge"):
        sf.Reduce("judge", judge="m")
    with pytest.raises(ValueError, match="arrives with sf.Merge"):
        sf.Reduce("merge", fields={"a": "b"})
    with pytest.raises(ValueError, match="sf.Judge"):
        sf.Reduce("judge", judge="m", rubric="r")


@pytest.mark.parametrize(
    ("op", "options", "error"),
    [
        ("weighted", {"extract": LAST, "weights": [0]}, ValueError),
        ("weighted", {"extract": LAST, "weights": [-1.0]}, ValueError),
        ("weighted", {"extract": LAST, "weights": [True]}, TypeError),
        ("weighted", {"extract": LAST, "weights": [math.inf]}, ValueError),
        ("weighted", {"extract": LAST, "weights": [math.nan]}, ValueError),
        ("weighted", {"extract": LAST, "weights": []}, ValueError),
        ("weighted", {"extract": LAST, "weights": "123"}, TypeError),
        ("weighted", {"extract": LAST, "weights": ["1"]}, TypeError),
        ("weighted", {"extract": LAST, "weights": [1e308]}, ValueError),
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
        sf.Reduce(op, **options)


def test_reduce_median_takes_only_the_numeric_normalizer_and_no_benchmark_rule() -> None:
    with pytest.raises(ValueError, match="numeric"):
        sf.Reduce("median", extract=sf.Extract("last_number", normalize="text"))
    with pytest.raises(ValueError, match="benchmark"):
        sf.Reduce("median", extract=sf.Extract("benchmark"))
    assert sf.Reduce("median", extract=LAST).options["extract"] == NUMERIC


def _one_per_row() -> list[Reduce]:
    return [
        sf.Reduce("plurality", extract=NUMERIC),
        sf.Reduce("weighted", extract=NUMERIC, weights=[1, 2.5, 3]),
        sf.Reduce("weighted", extract=NUMERIC, weights=sf.signal("field:c")),
        sf.Reduce("argmax", by_signal=sf.signal("cost_usd"), order="min"),
        sf.Reduce("top_k", k=2, by_field="a.b[0]", order="max"),
        sf.Reduce("top_k", k=2, by_signal=sf.signal("latency_ms")),
        sf.Reduce("filter", where=sf.matches("a+", ignore_case=True), extract=NUMERIC),
        sf.Reduce("pick_field", field="verdict", normalize="text", equals="yes"),
        sf.Reduce("pick_field", field="score", order="max"),
        sf.Reduce("concat", separator="\n--\n", label=True),
        sf.Reduce("median", mode="compute", extract=LAST),
        sf.Reduce("context"),
    ]


def test_equal_reduce_blocks_are_equal_and_hash_equal() -> None:
    for block in _one_per_row():
        twin = eval(block._python(), {"sf": sf})  # noqa: S307
        assert twin == block
        assert hash(twin) == hash(block)
        assert len({block, twin}) == 1
    assert sf.Reduce("plurality", extract=LAST) != sf.Reduce("plurality", extract=NUMERIC)
    assert sf.Reduce("weighted", extract=LAST, weights=[1]) != sf.Reduce(
        "weighted", extract=LAST, weights=[2]
    )
    assert sf.Reduce("median", extract=LAST) == sf.Reduce("median", extract=NUMERIC)
    assert hash(sf.Reduce("median", extract=LAST)) == hash(sf.Reduce("median", extract=NUMERIC))
    # Python's True == 1 == 1.0, but the three compile to different JSON: they are three blocks
    blocks = [sf.Reduce("pick_field", field="a", equals=value) for value in (True, 1, 1.0)]
    assert blocks[0] != blocks[1] != blocks[2]
    assert blocks[0] != blocks[2]
    assert len({hash(block) for block in blocks}) == 3
    assert len(set(blocks)) == 3
    assert sf.Reduce("median", mode="select", extract=LAST) != sf.Reduce(
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
        "context": "context",
    }


def test_reduce_repr_shows_mode_only_when_not_the_default() -> None:
    assert repr(sf.Reduce("median", mode="compute", extract=LAST)) == (
        "Reduce('median', mode='compute', extract=Extract('last_number', normalize='numeric'))"
    )
    assert repr(sf.Reduce("median", extract=LAST)) == (
        "Reduce('median', extract=Extract('last_number', normalize='numeric'))"
    )
    assert repr(sf.Reduce("concat")) == "Reduce('concat')"
    assert isinstance(sf.matches("a"), Matches)


def _compiled_text(reducer: Reduce, members: int = 3) -> str:
    return combine_spec_text(reducer, member_count=members, operators=engine_operators())


def test_reduce_plurality_compiles_byte_identical_to_the_fixture_vote() -> None:
    members = ["provider/a", "provider/b", "provider/c"]
    block = sf.Reduce("plurality", extract=NUMERIC)
    block_url4 = compile_candidate(
        sf.Fusion(members, synthesizer=block), operators=fixture_operators()
    ).url4
    fixture_url4 = compile_candidate(
        sf.Fusion(members, synthesizer=FixtureVote()), operators=fixture_operators()
    ).url4

    assert block_url4 == fixture_url4

    weighted = _compiled_text(sf.Reduce("weighted", extract=LAST, weights=[1, 2.5, 3]))
    assert '"reduce":{"args":{},"op":"weighted_mode@1"}' in weighted
    assert '"select":{"args":{},"op":"max_weight_holder@1"}' in weighted
    assert '"weights":{"member_1":1.0,"member_2":2.5,"member_3":3.0}' in weighted

    compute = _compiled_text(sf.Reduce("median", mode="compute", extract=LAST))
    select = _compiled_text(sf.Reduce("median", mode="select", extract=LAST))
    assert '"select":{"args":{},"op":"value@1"}' in compute
    assert '"select":{"args":{},"op":"nearest@1"}' in select
    assert '"normalize":{"args":{},"op":"numeric@1"}' in compute
    assert '"reduce":{"args":{},"op":"median@1"}' in compute
    assert '"reducer":"median"' in compute


def test_only_ops_with_engine_operators_compile_at_this_unit() -> None:
    not_yet = [
        sf.Reduce("argmax", by_signal=sf.signal("cost_usd")),
        sf.Reduce("top_k", k=1, by_field="a"),
        sf.Reduce("filter", where=sf.matches("a")),
        sf.Reduce("pick_field", field="a", order="max"),
        sf.Reduce("concat"),
        sf.Reduce("context"),
    ]
    for block in not_yet:
        with pytest.raises(ValueError, match="does not compile in this SDK version yet"):
            _compiled_text(block)
    # a signal-weighted block compiles since unit 7; only score:judge waits for the judge
    assert '"weights":{"signal":"field:c"}' in _compiled_text(
        sf.Reduce("weighted", extract=LAST, weights=sf.signal("field:c"))
    )
    with pytest.raises(ValueError, match="unknown extract operator 'json_object'"):
        _compiled_text(sf.Reduce("plurality", extract=sf.Extract("json")))
    with pytest.raises(ValueError, match="has 3 weights for 2 members"):
        sf.Fusion(
            ["provider/a", "provider/b"],
            synthesizer=sf.Reduce("weighted", extract=LAST, weights=[1, 2, 3]),
        )


def test_extract_benchmark_without_benchmark_raises() -> None:
    block = sf.Reduce("plurality", extract=sf.Extract("benchmark"))

    with pytest.raises(ValueError, match="extract='benchmark' needs a benchmark"):
        _compiled_text(block)


_RULES: list[tuple[Any, dict[str, Any]]] = [
    ("boxed", {}),
    ("last_number", {}),
    ("field", {"path": "answer"}),
    ("regex", {"pattern": r"Final: (\w+)\$'", "group": 1}),
    ("last_line", {}),
    ("whole", {}),
    ("inspect_number", {}),
    ("inspect_aime", {}),
]
_NORMALIZED = [None, "numeric", "text", "set", "inspect_numeric", "identity"]


def _roundtrip_cases() -> list[Reduce]:
    cases: list[Reduce] = []
    for rule, args in _RULES:
        cases.extend(
            sf.Reduce("plurality", extract=sf.Extract(rule, normalize=norm, **args))  # type: ignore[arg-type]
            for norm in _NORMALIZED
        )
        cases.append(
            sf.Reduce(
                "weighted",
                extract=sf.Extract(rule, normalize="text", **args),
                weights=[1, 2.5, 3],
            )
        )
    for mode in ("select", "compute"):
        for rule in ("last_number", "boxed", "inspect_number"):
            cases.append(sf.Reduce("median", mode=mode, extract=sf.Extract(rule)))  # type: ignore[arg-type]
    return cases


def _named_or_block(reducer: Reduce) -> type[Reducer]:
    """What a url4 of this block is recovered as (BK#8): the named class when it fits exactly."""

    if reducer.op == "median":
        return sf.Median
    extract = reducer.options.get("extract")
    if (
        reducer.op in ("plurality", "weighted")
        and isinstance(extract, sf.Extract)
        and not extract.args
    ):
        return sf.Vote
    return Reduce


@pytest.mark.parametrize("reducer", _roundtrip_cases(), ids=lambda value: repr(value)[:90])
def test_reduce_to_python_round_trips(reducer: Reduce) -> None:
    fusion = sf.Fusion(["provider/a", "provider/b", "provider/c"], synthesizer=reducer)
    url4 = compile_candidate(fusion, operators=engine_operators()).url4

    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102

    # The named form wins when it holds the spec exactly (Vote, Median); sf.Reduce keeps the rest.
    assert type(namespace["candidate"].synthesizer) is _named_or_block(reducer)
    if isinstance(namespace["candidate"].synthesizer, Reduce):
        assert namespace["candidate"] == fusion
    assert compile_candidate(namespace["candidate"], operators=engine_operators()).url4 == url4


@pytest.mark.parametrize("reducer", _one_per_row())
def test_every_constructible_reduce_row_rebuilds_from_its_source(reducer: Reduce) -> None:
    assert eval(reducer._python(), {"sf": sf}) == reducer  # noqa: S307


def _spec(reducer: Reduce) -> dict[str, Any]:
    return json.loads(_compiled_text(reducer))


def test_reduce_from_spec_refuses_shapes_it_cannot_rebuild() -> None:
    plurality = _spec(sf.Reduce("plurality", extract=NUMERIC))
    weighted = _spec(sf.Reduce("weighted", extract=NUMERIC, weights=[1, 2, 3]))
    median = _spec(sf.Reduce("median", extract=LAST))

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
            Reduce._from_spec(spec)
    assert Reduce._from_spec(plurality) == sf.Reduce("plurality", extract=NUMERIC)
    assert Reduce._from_spec(weighted) == sf.Reduce("weighted", extract=NUMERIC, weights=[1, 2, 3])
    assert Reduce._from_spec(median) == sf.Reduce("median", extract=LAST)


def test_weighted_from_spec_keeps_member_order_past_ten_members() -> None:
    # canonical JSON sorts member_10 before member_2: the weights must follow the member list
    weights = [float(k) for k in range(1, 13)]
    block = sf.Reduce("weighted", extract=NUMERIC, weights=weights)
    text = _compiled_text(block, members=12)
    spec = json.loads(text)

    sorted_weights = text[text.index('"weights"') :]
    assert sorted_weights.index('"member_10"') < sorted_weights.index('"member_2"')
    assert list(spec["weights"])[:3] == ["member_1", "member_10", "member_11"]
    assert Reduce._from_spec(spec) == block
    assert Reduce._from_spec(spec).options["weights"] == tuple(weights)
