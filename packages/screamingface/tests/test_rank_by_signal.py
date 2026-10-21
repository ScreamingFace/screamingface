"""sf.Rank by a named signal (OME-1289 gap, SR#9).

FEATURE: ``sf.Rank(k, by_signal=sf.signal(key), order="max"|"min")`` keeps the k members with the
highest or lowest value of a named number on each Answer.
INVARIANT (10E F3): the SAME order goes in ``by_signal@1`` and in ``top_k@1``; the Engine does not
cross-check them, and the select step's order decides which members are kept.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import JudgeNode, RankNode, fusion_node
from url4 import Expression, RelExpr, Source, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.reducer import Reducer

_KEYS = ["field:score", "cost_usd", "latency_ms"]


# WHY the internal nodes: the combine spec and the reprs are checks on the Rank node that the
# surface ``sf.Rank(k, by=...)`` lowers to.
def _scores_judge() -> JudgeNode:
    return JudgeNode("provider/j", returns="scores", rubric=RUBRIC)


def _spec(reducer: Reducer, members: int = 3) -> dict[str, Any]:
    text = combine_spec_text(reducer, member_count=members, operators=flow_operators())
    return json.loads(text)


def _wrapped(reducer: Reducer | sf.Rank) -> sf.Recipe:
    if isinstance(reducer, sf.Rank):
        return sf.Fanout(members3()) >> reducer >> sf.Synthesize("provider/next")
    return sf.Pipeline([fusion_node(members3(), reducer), "provider/next"])


def _url4(reducer: Reducer | sf.Rank) -> str:
    return compile_candidate(_wrapped(reducer), operators=flow_operators()).url4


def _combine_context(url4: str) -> str:
    """The context of the combine call: the question, the panel, and any ``sources``."""

    root = build(url4)
    assert isinstance(root, Expression)
    for source in root.sources:
        if isinstance(source, Source) and source.name == "synthesis_1":
            assert isinstance(source.value, RelExpr)
            return str(source.value.context)
    raise AssertionError("no synthesis_1 source")


def test_rank_by_signal_compiles_by_signal_and_top_k() -> None:
    rank = RankNode(2, by_signal=sf.signal("field:score"))
    spec = _spec(rank)

    assert spec["reducer"] == "rank"
    assert (spec["extract"], spec["normalize"], spec["weights"]) == (None, None, None)
    assert spec["reduce"] == {"args": {"key": "field:score", "order": "max"}, "op": "by_signal@1"}
    assert spec["select"] == {"args": {"k": 2, "order": "max"}, "op": "top_k@1"}

    lowest = _spec(RankNode(2, by_signal=sf.signal("field:score"), order="min"))
    assert lowest["reduce"]["args"] == {"key": "field:score", "order": "min"}
    assert lowest["select"]["args"] == {"k": 2, "order": "min"}


def test_the_max_default_keeps_the_old_bytes_of_rank_by_field_and_by_judge() -> None:
    judged = _spec(RankNode(2, by=_scores_judge()))
    assert judged["select"] == {"args": {"k": 2}, "op": "top_k@1"}


def test_the_order_option_of_by_field_and_by_judge_writes_the_order_into_top_k_only() -> None:
    by_judge = _spec(RankNode(2, by=_scores_judge(), order="min"))

    assert by_judge["select"] == {"args": {"k": 2, "order": "min"}, "op": "top_k@1"}
    assert by_judge["reduce"] == {"args": {"source": "judge"}, "op": "scores@1"}


@pytest.mark.parametrize("key", ["cost_usd"])
def test_an_accounting_key_emits_sources_through_the_signal_seam(key: str) -> None:
    named = _url4(sf.Rank(2, by=key, order="min"))

    assert "sources:" in _combine_context(named)
    # a field signal needs no accounting sources
    assert "sources:" not in _combine_context(_url4(sf.Rank(2, by="field:score")))


def test_rank_by_signal_validation() -> None:
    with pytest.raises(TypeError, match="sf.Rank by must be a sf.signal"):
        RankNode(2, by_signal="field:score")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sf.Rank order must be 'max' or 'min'"):
        sf.Rank(2, by="cost_usd", order="avg")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sf.Rank order must be 'max' or 'min'"):
        sf.Rank(2, by="score:judge", order=None)  # type: ignore[arg-type]
    # score:judge has no judge here: the message names the step that writes it
    with pytest.raises(
        ValueError, match=r"^score:judge needs sf\.Judge\(\.\.\.\) after sf\.Fanout$"
    ) as hint:
        _ = sf.Fanout(members3()) >> sf.Rank(2, by="score:judge") >> sf.Synthesize("provider/next")
    assert "sf.Judge(...) after sf.Fanout" in str(hint.value)
    with pytest.raises(ValueError, match="sf.Rank k must be between 1 and 256"):
        sf.Rank(0, by="cost_usd")
    with pytest.raises(ValueError, match="k=4"):
        _ = sf.Fanout(members3()) >> sf.Rank(4, by="cost_usd") >> sf.Synthesize("provider/next")


def test_rank_by_signal_fields_repr_and_equality() -> None:
    signal = sf.signal("field:score")
    by_signal = RankNode(2, by_signal=signal)
    lowest = RankNode(2, by_signal=signal, order="min")

    assert (by_signal.by_signal, by_signal.order, by_signal.by) == (signal, "max", None)
    assert repr(by_signal) == "Rank(k=2, by_signal=signal('field:score'))"
    assert repr(lowest) == "Rank(k=2, by_signal=signal('field:score'), order='min')"
    assert by_signal != lowest
    assert by_signal == RankNode(2, by_signal=sf.signal("field:score"), order="max")
    assert by_signal != RankNode(2, by_signal=sf.signal("cost_usd"))
    assert by_signal != RankNode(3, by_signal=signal)
