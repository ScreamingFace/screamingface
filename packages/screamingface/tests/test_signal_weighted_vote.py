"""Signal-weighted sf.Vote: weights on the Median, the block twin, the spec and recovery (OME-1289).

FEATURE: ``sf.Vote(weights=[...] | sf.signal(key))`` and the weighted block are one Candidate
(unit 7, BK#4, SR#9).
INVARIANT: since E4b, sf.Median(weights=...) and the median block take weights; both refuse
sf.signal("score:judge").
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from _combine_contract import engine_operators
from _nodes import ReduceNode, VoteNode, fusion_node, lowered

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._surface.chain import Step
from screamingface.reducer import Reducer

_MEMBERS = ["provider/a", "provider/b", "provider/c"]
_NUMBER: dict[str, Any] = {"over": "last_number", "normalize": "numeric"}
_FIELD = sf.Extract("field", path="answer", normalize="text")


def _url4(step: Step) -> str:
    return compile_candidate(sf.Fanout(_MEMBERS) >> step, operators=engine_operators()).url4


def _node_url4(synthesizer: Reducer) -> str:
    """The url4 of a rebuilt internal reducer, in a block of the same members."""
    fusion = fusion_node(_MEMBERS, synthesizer)
    return compile_candidate(fusion, operators=engine_operators()).url4


def test_median_rejects_signal_weights() -> None:
    # E4b weighted median (WM#13): Median and the median block take weights now; only the judge
    # signal is refused, because a Median has no judge.
    with pytest.raises(ValueError, match="has no judge"):
        sf.Median(weights=sf.signal("score:judge"))
    with pytest.raises(ValueError, match="has no judge"):
        sf.Median(over=sf.Extract("last_number"), weights=sf.signal("score:judge"))
    assert sf.Median(weights=None).select == "nearest"


def test_score_judge_weights_wait_for_the_judge() -> None:
    # 8S F5: the pairing rule fails at construction, before any compile or paid call
    judge = sf.signal("score:judge")
    with pytest.raises(
        ValueError, match=re.escape("score:judge needs sf.Judge(...) after sf.Fanout")
    ):
        _ = sf.Fanout(_MEMBERS) >> sf.Vote(over=_FIELD, weights=judge)
    with pytest.raises(
        ValueError, match=re.escape("score:judge needs sf.Judge(...) after sf.Fanout")
    ):
        _ = sf.Fanout(_MEMBERS) >> sf.Vote(**_NUMBER, weights=judge)


def _signal_vote_spec(key: str) -> dict[str, Any]:
    text = combine_spec_text(
        VoteNode(extract="last_number", normalize="numeric", weights=sf.signal(key)),
        member_count=3,
        operators=engine_operators(),
    )
    return decode_combine_spec(text)


def test_signal_weights_value_repr_python_and_recovery() -> None:
    vote = VoteNode(weights=sf.signal("cost_usd"))
    assert repr(vote) == "Vote(extract='last_line', normalize='text', weights=signal('cost_usd'))"
    assert eval(repr(vote), {"Vote": VoteNode, "signal": sf.signal}) == vote  # noqa: S307
    assert vote == VoteNode(weights=sf.signal("cost_usd"))
    assert vote != VoteNode(weights=sf.signal("latency_ms"))
    assert vote != VoteNode(weights=[1.0])
    recovered = VoteNode._from_spec(_signal_vote_spec("field:confidence"))
    assert recovered == VoteNode(
        extract="last_number@1", normalize="numeric@1", weights=sf.signal("field:confidence")
    )


@pytest.mark.parametrize("key", ["field:confidence"])
def test_signal_vote_round_trips_through_url4(key: str) -> None:
    url4 = _url4(sf.Vote(**_NUMBER, weights=sf.signal(key)))
    code = sf.Url4(url4).to_python()
    assert f">> sf.Vote(over='last_number@1', normalize='numeric@1', weights={key!r})" in code
    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 - our own generated code
    assert type(lowered(namespace["candidate"]).synthesizer) is VoteNode
    assert _node_url4(lowered(namespace["candidate"]).synthesizer) == url4


def test_signal_block_with_a_field_path_recovers_as_reduce() -> None:
    block = ReduceNode("weighted", extract=_FIELD, weights=sf.signal("field:confidence"))
    url4 = _node_url4(block)
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    assert lowered(namespace["candidate"]).synthesizer == block
    assert _node_url4(lowered(namespace["candidate"]).synthesizer) == url4


@pytest.mark.parametrize("weights", [{"signal": 3}, {"signal": "x", "y": 1}, [1, 2, 3], "cost_usd"])
def test_from_spec_refuses_a_malformed_signal_weight(weights: dict[str, Any]) -> None:
    spec = _signal_vote_spec("cost_usd")
    spec["weights"] = weights
    with pytest.raises(ValueError, match="cannot rebuild"):
        VoteNode._from_spec(spec)
