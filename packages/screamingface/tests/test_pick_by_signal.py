"""sf.Pick(by_signal=..., order=...) picks the member with the best named signal (OME-1289, 9S).

FEATURE: argmax. The reducer compiles to ``by_signal@1`` and ``best_holder@1`` (reducer ``pick``,
no extract and no normalize) and the Engine returns the best member's text byte for byte.
INVARIANT (10E F3): the SAME ``order`` goes into both steps, because the select step decides.
INVARIANT (F7): an accounting key (cost_usd, latency_ms, ...) adds ``sources`` to the context.
"""

from __future__ import annotations

import json
import warnings
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from _nodes import FusionNode, PickNode, lowered
from test_combine_sources import _call, _context, context_of
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface._surface.chain import Step
from screamingface._surface.lowering import lower
from screamingface._surface.render import render
from screamingface.reducer import Reducer, _Step, _Steps
from screamingface.url4 import _Call, _calls


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


def _block(step: Step) -> sf.Recipe:
    return sf.Fanout(members3()) >> step


def _reducer(step: Step) -> Reducer:
    """The reducer node that ``step`` lowers to: the compile reads its plan."""

    node = lower(_block(step))
    assert isinstance(node, FusionNode)
    assert isinstance(node.synthesizer, Reducer)
    return node.synthesizer


def _spec(reducer: Reducer) -> dict[str, Any]:
    return json.loads(combine_spec_text(reducer, member_count=3, operators=flow_operators()))


def test_pick_by_signal_compiles_by_signal_and_best_holder() -> None:
    pick = _reducer(sf.ArgMin("field:confidence"))
    text = combine_spec_text(pick, member_count=3, operators=flow_operators())
    spec = json.loads(text)

    assert spec["reducer"] == "pick"
    assert (spec["extract"], spec["normalize"], spec["weights"]) == (None, None, None)
    assert spec["reduce"] == {
        "args": {"key": "field:confidence", "order": "min"},
        "op": "by_signal@1",
    }
    assert spec["select"] == {"args": {"order": "min"}, "op": "best_holder@1"}
    assert (
        '"reduce":{"args":{"key":"field:confidence","order":"min"},"op":"by_signal@1"},'
        '"reducer":"pick"' in text
    )
    assert '"select":{"args":{"order":"min"},"op":"best_holder@1"}' in text
    # the default order is "max" in both steps
    default = _spec(_reducer(sf.ArgMax("cost_usd")))
    assert default["reduce"]["args"] == {"key": "cost_usd", "order": "max"}
    assert default["select"]["args"] == {"order": "max"}
    # it is an answer, so it can be the last stage of a candidate
    plan = pick._plan()
    assert (plan.reducer, plan.kind) == ("pick", "answer")
    assert plan.steps == _Steps(
        reduce=_Step("by_signal", {"key": "field:confidence", "order": "min"}),
        select=_Step("best_holder", {"order": "min"}),
    )
    assert _url4(sf.Pipeline(["provider/q", _block(sf.ArgMin("field:confidence"))]))


def test_pick_by_signal_validation() -> None:
    with pytest.raises(
        ValueError, match=r"^score:judge needs sf\.Judge\(\.\.\.\) after sf\.Fanout$"
    ):
        _ = _block(sf.ArgMax("score:judge"))


def test_pick_by_signal_value_equality_repr_and_python() -> None:
    pick = sf.ArgMin("cost_usd")

    assert (pick.by, pick.output, pick._order) == (sf.signal("cost_usd"), None, "min")
    assert sf.ArgMax("cost_usd")._order == "max"
    assert repr(pick) == "ArgMin('cost_usd')"
    assert render(pick, "sf.") == "sf.ArgMin('cost_usd')"
    assert eval(render(pick, "sf."), {"sf": sf}) == pick  # noqa: S307 - our own generated code
    assert pick == sf.ArgMin("cost_usd")
    assert pick != sf.ArgMax("cost_usd")
    assert pick != sf.ArgMin("latency_ms")
    with pytest.raises(TypeError):
        hash(pick)


def _argmax(key: str = "cost_usd") -> sf.Recipe:
    members: list[Any] = [sf.Model("p/a", params={"temperature": 0.5}), "p/b", "p/c"]
    return sf.Fanout(members) >> sf.ArgMin(key)


_OUTPUTS = {"member_1": "$model_1", "member_2": "$model_2", "member_3": "$model_3"}


def test_argmax_by_accounting_signal_emits_sources() -> None:
    sources = {
        "member_1": {"model_1": _call("/p/a", "temperature=0.5")},
        "member_2": {"model_2": _call("/p/b")},
        "member_3": {"model_3": _call("/p/c")},
    }

    for key in ("cost_usd", "latency_ms", "tokens_in", "tokens_out"):
        url4 = _url4(_argmax(key))

        assert context_of(url4, "synthesis_1") == _context(_OUTPUTS, sources)
    # a field: key reads the answer, not the calls: no sources
    assert context_of(_url4(_argmax("field:confidence")), "synthesis_1") == _context(_OUTPUTS)
    assert "sources:" not in _url4(_argmax("field:confidence"))

    duplicates = sf.Fanout(["p/a", "p/a", "p/b"]) >> sf.ArgMin("cost_usd")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        url4 = _url4(duplicates)
    assert "sources: {member_1: {}, member_2: {}, member_3: {model_3: {" in url4
    assert sum(issubclass(item.category, sf.DuplicateMembersWarning) for item in caught) == 1


def _recovered(url4: str) -> Reducer:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    synthesizer = lowered(namespace["candidate"]).synthesizer
    assert isinstance(synthesizer, Reducer)
    return synthesizer


def test_argmax_round_trips_through_url4_and_recovers_as_pick() -> None:
    pick = sf.ArgMin("cost_usd")
    url4 = _url4(_block(pick))

    source = sf.Url4(url4).to_python()
    assert source.endswith(
        "candidate = sf.Fanout(['provider/a', 'provider/b', 'provider/c']) >> sf.ArgMin('cost_usd')"
    )
    recovered = _recovered(url4)
    # the chain's lowered node holds the Pick the url4 is recovered as
    assert type(recovered) is PickNode
    assert recovered == _reducer(pick)
    namespace: dict[str, Any] = {}
    exec(source, namespace)  # noqa: S102 - our own generated code
    assert namespace["candidate"] == _block(pick)
    assert _url4(namespace["candidate"]) == url4
    assert "sources:" in url4  # the recompiled text keeps the accounting sources


def _synthesis_call(url4: str) -> _Call:
    root = build(url4)
    assert isinstance(root, Expression)
    return _calls(root)["synthesis_1"]


def _synthesis_spec(url4: str) -> dict[str, Any]:
    return json.loads(_synthesis_call(url4).raw_intent)


def _recover_from(spec: dict[str, Any]) -> Reducer:
    return PickNode._from_spec(spec)


@pytest.mark.parametrize(
    "change",
    [
        {"select": {"op": "best_holder@1", "args": {"order": "max"}}},
        {"reduce": {"op": "by_signal@1", "args": {"key": 3, "order": "min"}}},
    ],
    ids=["orders differ", "key not text"],
)
def test_a_tampered_argmax_spec_cannot_be_rebuilt(change: dict[str, Any]) -> None:
    spec = {
        **_synthesis_spec(_url4(_block(sf.ArgMin("cost_usd")))),
        **change,
    }

    with pytest.raises(ValueError, match="URL4 Candidate has a pick spec this SDK version cannot"):
        _recover_from(spec)
