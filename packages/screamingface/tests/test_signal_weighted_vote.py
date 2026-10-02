"""Signal-weighted sf.Vote: weights on the Median, the block twin, the spec and recovery (OME-1289).

FEATURE: ``sf.Vote(weights=[...] | sf.signal(key))`` and ``sf.Reduce("weighted", ...)`` are one
Candidate (unit 7, BK#4, SR#9).
INVARIANT: ``sf.Median(weights=...)`` raises TypeError, while ``sf.Reduce("median", weights=...)``
raises ValueError ("does not take option"): both rules are pinned (F10).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_contract import engine_operators
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface.reducer import Reducer
from screamingface.url4 import _calls

_MEMBERS = ["provider/a", "provider/b", "provider/c"]
_NUMBER: dict[str, Any] = {"extract": "last_number", "normalize": "numeric"}
_FIELD = sf.Extract("field", path="answer", normalize="text")


def _url4(synthesizer: Reducer) -> str:
    fusion = sf.Fusion(_MEMBERS, synthesizer=synthesizer)
    return compile_candidate(fusion, operators=engine_operators()).url4


def _spec_of(url4: str) -> dict[str, Any]:
    root = build(url4)
    assert isinstance(root, Expression)
    return json.loads(_calls(root)["synthesis_1"].raw_intent)


def test_median_rejects_signal_weights() -> None:
    with pytest.raises(TypeError, match="weights apply to Vote only"):
        sf.Median(weights=sf.signal("cost_usd"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="weights apply to Vote only"):
        sf.Median(weights=[1, 2])  # type: ignore[arg-type]
    assert sf.Median(weights=None).select == "nearest"
    # BK-D1 keeps the block's own rule: a ValueError that names the option (F10).
    with pytest.raises(ValueError, match="does not take option 'weights'"):
        sf.Reduce("median", extract=sf.Extract("last_number"), weights=sf.signal("cost_usd"))


def test_vote_signal_weights_compile_to_a_signal_spec() -> None:
    weights = sf.signal("field:confidence")
    block = sf.Reduce("weighted", extract=_FIELD, weights=weights)
    spec = _spec_of(_url4(block))
    assert spec["weights"] == {"signal": "field:confidence"}
    assert (spec["reduce"]["op"], spec["select"]["op"]) == (
        "weighted_mode@1",
        "max_weight_holder@1",
    )
    assert spec["extract"] == {"op": "json_field@1", "args": {"path": "answer"}}

    spec = _spec_of(_url4(sf.Vote(**_NUMBER, weights=weights)))
    assert spec["weights"] == {"signal": "field:confidence"}
    assert (spec["reduce"]["op"], spec["select"]["op"]) == (
        "weighted_mode@1",
        "max_weight_holder@1",
    )


def test_score_judge_weights_wait_for_the_judge() -> None:
    judge = sf.signal("score:judge")
    with pytest.raises(ValueError, match="needs a judge"):
        _url4(sf.Reduce("weighted", extract=_FIELD, weights=judge))
    with pytest.raises(ValueError, match="needs a judge"):
        _url4(sf.Vote(**_NUMBER, weights=judge))


def _signal_vote_spec(key: str) -> dict[str, Any]:
    text = combine_spec_text(
        sf.Vote(**_NUMBER, weights=sf.signal(key)), member_count=3, operators=engine_operators()
    )
    return decode_combine_spec(text)


def test_signal_weights_value_repr_python_and_recovery() -> None:
    vote = sf.Vote(weights=sf.signal("cost_usd"))
    assert repr(vote) == "Vote(extract='last_line', normalize='text', weights=signal('cost_usd'))"
    assert eval(repr(vote), {"Vote": sf.Vote, "signal": sf.signal}) == vote  # noqa: S307
    assert "weights=sf.signal('cost_usd')" in vote._python()
    assert vote._python().startswith("sf.Vote(")
    assert vote == sf.Vote(weights=sf.signal("cost_usd"))
    assert vote != sf.Vote(weights=sf.signal("latency_ms"))
    assert vote != sf.Vote(weights=[1.0])
    recovered = sf.Vote._from_spec(_signal_vote_spec("field:confidence"))
    assert recovered == sf.Vote(
        extract="last_number@1", normalize="numeric@1", weights=sf.signal("field:confidence")
    )


@pytest.mark.parametrize("key", ["field:confidence", "cost_usd"])
def test_signal_vote_round_trips_through_url4(key: str) -> None:
    url4 = _url4(sf.Vote(**_NUMBER, weights=sf.signal(key)))
    code = sf.Url4(url4).to_python()
    assert f"weights=sf.signal({key!r})" in code
    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 - our own generated code
    assert type(namespace["candidate"].synthesizer) is sf.Vote
    assert _url4(namespace["candidate"].synthesizer) == url4


def test_signal_block_with_a_field_path_recovers_as_reduce() -> None:
    block = sf.Reduce("weighted", extract=_FIELD, weights=sf.signal("field:confidence"))
    url4 = _url4(block)
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    assert namespace["candidate"].synthesizer == block
    assert _url4(namespace["candidate"].synthesizer) == url4


@pytest.mark.parametrize("weights", [{"signal": 3}, {"signal": "x", "y": 1}, [1, 2, 3], "cost_usd"])
def test_from_spec_refuses_a_malformed_signal_weight(weights: dict[str, Any]) -> None:
    spec = _signal_vote_spec("cost_usd")
    spec["weights"] = weights
    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Vote._from_spec(spec)
