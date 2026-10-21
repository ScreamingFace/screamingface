"""A url4 reducer is recovered as its named class when that class accepts the spec exactly (BK#8).

FEATURE: ``Url4(...).to_python()`` writes ``sf.Vote(...)`` or ``sf.Median(...)`` when the combine
spec is exactly one, and ``sf.Reduce(...)`` for every other shape (operator args).
INVARIANT: the recovered Python recompiles to the very same url4.
"""

from __future__ import annotations

from typing import Any

import pytest
from _nodes import FusionNode, MedianNode, ReduceNode, VoteNode, fusion_node
from _reducer_fixtures import engine_operators
from url4 import Expression, build

import screamingface as sf
import screamingface.reducer as reducer_module
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import canonical_json, decode_combine_spec
from screamingface.reducer import Reducer
from screamingface.url4 import _Call, _calls, _reducer_from_call

_REGEX = sf.Extract("regex", normalize="text", pattern=r"Final: (\w+)", group=1)
_FIELD = sf.Extract("field", normalize="text", path="answer")
_NUMERIC = sf.Extract("last_number", normalize="numeric")


_MEMBERS = ["provider/a", "provider/b", "provider/c"]


# WHY the internal nodes: these rows recover a reducer node from a url4 and compare it with the
# node that wrote it (the block preference of BK#8).
def _fusion(synthesizer: Reducer) -> FusionNode:
    return fusion_node(_MEMBERS, synthesizer)


def _url4(synthesizer: Reducer) -> str:
    return compile_candidate(_fusion(synthesizer), operators=engine_operators()).url4


def _synthesis_call(url4: str) -> _Call:
    root = build(url4)
    assert isinstance(root, Expression)
    return _calls(root)["synthesis_1"]


def _call_with(spec: dict[str, Any]) -> _Call:
    return _Call(
        binding="synthesis_1",
        model="ensemble/combine/v1",
        dependencies=(),
        context="",
        prompt="",
        params=(),
        raw_intent=canonical_json(spec),
    )


_ROWS: list[tuple[Reducer, type[Reducer], str | None]] = [
    (
        VoteNode(extract="last_number", normalize="numeric"),
        VoteNode,
        "sf.Vote(extract='last_number@1', normalize='numeric@1')",
    ),
    (
        ReduceNode("plurality", extract=_NUMERIC),
        VoteNode,
        "sf.Vote(extract='last_number@1', normalize='numeric@1')",
    ),
    (VoteNode(normalize=None), VoteNode, "sf.Vote(extract='last_line@1', normalize=None)"),
    (
        MedianNode(select="value"),
        MedianNode,
        "sf.Median(extract='last_number@1', select='value@1')",
    ),
    (
        ReduceNode("median", extract=sf.Extract("boxed")),
        MedianNode,
        "sf.Median(extract='boxed@1', select='nearest@1')",
    ),
    (ReduceNode("plurality", extract=_REGEX), ReduceNode, None),
    (ReduceNode("plurality", extract=_FIELD), ReduceNode, None),
    (
        ReduceNode("weighted", extract=_NUMERIC, weights=[1, 2.5, 3]),
        VoteNode,
        "sf.Vote(extract='last_number@1', normalize='numeric@1', weights=(1.0, 2.5, 3.0))",
    ),
    (ReduceNode("weighted", extract=_REGEX, weights=[1, 2.5, 3]), ReduceNode, None),
]


@pytest.mark.parametrize(("source", "recovered_type", "python"), _ROWS, ids=repr)
def test_recovered_spec_prefers_named_class_else_reduce(
    source: Reducer, recovered_type: type[Reducer], python: str | None
) -> None:
    url4 = _url4(source)

    recovered = _reducer_from_call(_synthesis_call(url4))

    assert type(recovered) is recovered_type
    # WHY repr: the old ``_python()`` renderer went in unit 7f; the repr is that text without "sf."
    assert repr(recovered) == (repr(source) if python is None else python.removeprefix("sf."))
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    assert compile_candidate(namespace["candidate"], operators=engine_operators()).url4 == url4


def test_named_refusal_falls_back_and_an_unrebuildable_spec_still_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vote_url4 = _url4(VoteNode(extract="last_number", normalize="numeric"))
    spec = decode_combine_spec(_synthesis_call(vote_url4).raw_intent)

    spec_median = {**spec, "reduce": {"op": "median@1", "args": {}}}
    with pytest.raises(ValueError, match="cannot rebuild"):
        _reducer_from_call(_call_with(spec_median))

    # With no named class registered, the same url4 comes back as the block.
    monkeypatch.setattr(reducer_module, "_REDUCER_CLASSES", {})
    recovered = _reducer_from_call(_synthesis_call(vote_url4))
    assert type(recovered) is ReduceNode


@pytest.mark.parametrize("op", ["benchmark", "benchmark@1"])
def test_benchmark_extract_op_in_a_hand_edited_url4_is_refused(op: str) -> None:
    # A hand-edited url4 cannot name the benchmark's rule: Vote refuses it, so does sf.Reduce.
    vote = sf.Fanout(_MEMBERS) >> sf.Vote(over="last_number", normalize="numeric")
    vote_url4 = compile_candidate(vote, operators=engine_operators()).url4
    spec = decode_combine_spec(_synthesis_call(vote_url4).raw_intent)

    with pytest.raises(ValueError, match="cannot rebuild"):
        _reducer_from_call(_call_with({**spec, "extract": {"op": op, "args": {}}}))
