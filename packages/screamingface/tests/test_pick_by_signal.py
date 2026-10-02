"""sf.Pick(by_signal=..., order=...) picks the member with the best named signal (OME-1289, 9S).

FEATURE: argmax. The reducer compiles to ``by_signal@1`` and ``best_holder@1`` (reducer ``pick``,
no extract and no normalize) and the Engine returns the best member's text byte for byte.
INVARIANT (10E F3): the SAME ``order`` goes into both steps, because the select step decides.
INVARIANT (F7): an accounting key (cost_usd, latency_ms, ...) adds ``sources`` to the context.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import replace
from typing import Any

import pytest
from _combine_flow_fixtures import flow_operators, members3
from test_combine_sources import _call, _context, context_of
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import accounting_signal, combine_spec_text
from screamingface.reducer import Reducer, _Step, _Steps
from screamingface.url4 import _Call, _calls, _reducer_from_call

_KEYS = ["cost_usd", "latency_ms", "field:confidence"]
_ORDERS: list[Any] = ["max", "min"]


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


def _fusion(synthesizer: Reducer) -> sf.Fusion:
    return sf.Fusion(members3(), synthesizer=synthesizer)


def _spec(reducer: Reducer) -> dict[str, Any]:
    return json.loads(combine_spec_text(reducer, member_count=3, operators=flow_operators()))


def test_pick_by_signal_compiles_by_signal_and_best_holder() -> None:
    pick = sf.Pick(by_signal=sf.signal("field:confidence"), order="min")
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
    default = _spec(sf.Pick(by_signal=sf.signal("cost_usd")))
    assert default["reduce"]["args"] == {"key": "cost_usd", "order": "max"}
    assert default["select"]["args"] == {"order": "max"}
    # it is an answer, so it can be the last stage of a candidate
    plan = pick._plan()
    assert (plan.reducer, plan.kind) == ("pick", "answer")
    assert plan.steps == _Steps(
        reduce=_Step("by_signal", {"key": "field:confidence", "order": "min"}),
        select=_Step("best_holder", {"order": "min"}),
    )
    assert _url4(sf.Pipeline(["provider/q", _fusion(pick)]))


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("order", _ORDERS)
def test_the_same_order_goes_into_both_steps(key: str, order: Any) -> None:
    # 10E F3: the Engine does not cross-check them, and the select step's order decides the pick
    for reducer in (
        sf.Pick(by_signal=sf.signal(key), order=order),
        sf.Reduce("argmax", by_signal=sf.signal(key), order=order),
    ):
        spec = _spec(reducer)

        assert spec["reduce"]["args"]["order"] == order
        assert spec["select"]["args"]["order"] == order


def test_pick_by_signal_validation() -> None:
    cost = sf.signal("cost_usd")

    with pytest.raises(ValueError, match="Pick needs a field or by_signal=$"):
        sf.Pick()
    with pytest.raises(ValueError, match="Pick needs a field or by_signal=, not both"):
        sf.Pick("a", by_signal=cost, order="max")
    with pytest.raises(TypeError, match="Pick by_signal must be an sf.signal"):
        sf.Pick(by_signal="cost_usd")  # type: ignore[arg-type]
    extras: list[dict[str, Any]] = [
        {"equals": "x"},
        {"normalize": "text"},
        {"equals": "x", "normalize": "text"},
    ]
    for extra in extras:
        with pytest.raises(ValueError, match=r"Pick\(by_signal=\.\.\.\) takes order only"):
            sf.Pick(by_signal=cost, **extra)
    with pytest.raises(ValueError, match="Pick order must be 'max' or 'min', not 'up'"):
        sf.Pick(by_signal=cost, order="up")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"Pick takes order='max'\|'min' or equals"):
        sf.Pick("a")
    message = (
        r"Pick cannot read sf\.signal\('score:judge'\): it has no judge; "
        r"use sf\.Judge\(\.\.\., returns='scores'\), which picks the highest judge score"
    )
    with pytest.raises(ValueError, match=message):
        sf.Pick(by_signal=sf.signal("score:judge"))
    with pytest.raises(ValueError, match=r"sf\.Reduce\('argmax'\): " + message):
        sf.Reduce("argmax", by_signal=sf.signal("score:judge"))


def test_pick_by_signal_value_equality_repr_and_python() -> None:
    pick = sf.Pick(by_signal=sf.signal("cost_usd"), order="min")

    assert (pick.field, pick.by_signal, pick.order) == (None, sf.signal("cost_usd"), "min")
    assert sf.Pick(by_signal=sf.signal("cost_usd")).order == "max"
    assert repr(pick) == "Pick(by_signal=signal('cost_usd'), order='min')"
    assert pick._python() == "sf.Pick(by_signal=sf.signal('cost_usd'), order='min')"
    assert eval(pick._python(), {"sf": sf}) == pick  # noqa: S307 - our own generated code
    assert pick == sf.Pick(by_signal=sf.signal("cost_usd"), order="min")
    assert pick != sf.Pick(by_signal=sf.signal("cost_usd"), order="max")
    assert pick != sf.Pick(by_signal=sf.signal("latency_ms"), order="min")
    with pytest.raises(TypeError):
        hash(pick)
    # the field form is unchanged
    assert repr(sf.Pick("c", order="max")) == "Pick('c', order='max')"
    assert sf.Pick("c", order="max")._python() == "sf.Pick('c', order='max')"


def _argmax(key: str = "cost_usd") -> sf.Fusion:
    members: list[Any] = [sf.Model("p/a", params={"temperature": 0.5}), "p/b", "p/c"]
    return sf.Fusion(members, synthesizer=sf.Pick(by_signal=sf.signal(key), order="min"))


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

    duplicates = sf.Fusion(
        ["p/a", "p/a", "p/b"], synthesizer=sf.Pick(by_signal=sf.signal("cost_usd"), order="min")
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        url4 = _url4(duplicates)
    assert "sources: {member_1: {}, member_2: {}, member_3: {model_3: {" in url4
    assert sum(issubclass(item.category, sf.DuplicateMembersWarning) for item in caught) == 1


def test_accounting_signal_reads_a_pick_and_still_reads_the_weights() -> None:
    assert accounting_signal(sf.Pick(by_signal=sf.signal("cost_usd"))) == "cost_usd"
    assert accounting_signal(sf.Pick(by_signal=sf.signal("field:confidence"))) is None
    assert accounting_signal(sf.Pick("a", order="max")) is None
    assert accounting_signal(sf.Vote(weights=sf.signal("tokens_in"))) == "tokens_in"
    assert accounting_signal(sf.Vote()) is None


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("order", _ORDERS)
def test_argmax_block_matches_pick(key: str, order: Any) -> None:
    signal = sf.signal(key)

    block = sf.Reduce("argmax", by_signal=signal, order=order)
    named = sf.Pick(by_signal=signal, order=order)

    assert _url4(_fusion(block)) == _url4(_fusion(named))


def test_argmax_block_canonical_form() -> None:
    signal = sf.signal("cost_usd")
    default = sf.Reduce("argmax", by_signal=signal)

    assert default == sf.Reduce("argmax", by_signal=signal, order="max")
    assert hash(default) == hash(sf.Reduce("argmax", by_signal=signal, order="max"))
    assert dict(default.options) == {"by_signal": signal}
    assert dict(sf.Reduce("argmax", by_signal=signal, order="min").options) == {
        "by_signal": signal,
        "order": "min",
    }
    assert default != sf.Reduce("argmax", by_signal=signal, order="min")
    for block in (default, sf.Reduce("argmax", by_signal=signal, order="min")):
        assert eval(block._python(), {"sf": sf}) == block  # noqa: S307 - our own generated code
    with pytest.raises(TypeError, match="option 'by_signal' must be an sf.signal"):
        sf.Reduce("argmax", by_signal="cost_usd")  # type: ignore[arg-type]


def _recovered(url4: str) -> Reducer:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    synthesizer = namespace["candidate"].synthesizer
    assert isinstance(synthesizer, Reducer)
    return synthesizer


def test_argmax_round_trips_through_url4_and_recovers_as_pick() -> None:
    pick = sf.Pick(by_signal=sf.signal("cost_usd"), order="min")
    url4 = _url4(_fusion(pick))

    source = sf.Url4(url4).to_python()
    assert "sf.Pick(by_signal=sf.signal('cost_usd'), order='min')" in source
    recovered = _recovered(url4)
    assert type(recovered) is sf.Pick
    assert recovered == pick
    namespace: dict[str, Any] = {}
    exec(source, namespace)  # noqa: S102 - our own generated code
    assert _url4(namespace["candidate"]) == url4
    assert "sources:" in url4  # the recompiled text keeps the accounting sources
    # BK#8: the block form is recovered as the named class too
    block_url4 = _url4(_fusion(sf.Reduce("argmax", by_signal=sf.signal("cost_usd"), order="min")))
    assert block_url4 == url4
    assert type(_recovered(block_url4)) is sf.Pick


def _synthesis_call(url4: str) -> _Call:
    root = build(url4)
    assert isinstance(root, Expression)
    return _calls(root)["synthesis_1"]


def _synthesis_spec(url4: str) -> dict[str, Any]:
    return json.loads(_synthesis_call(url4).raw_intent)


def _recover_from(spec: dict[str, Any]) -> Reducer:
    return sf.Pick._from_spec(spec)


@pytest.mark.parametrize(
    "change",
    [
        {"select": {"op": "best_holder@1", "args": {"order": "max"}}},
        {"reduce": {"op": "by_signal@1", "args": {"key": "logprob_mean", "order": "min"}}},
        {"reduce": {"op": "by_signal@1", "args": {"key": "score:judge", "order": "min"}}},
        {"reduce": {"op": "by_signal@1", "args": {"key": 3, "order": "min"}}},
        {"reduce": {"op": "by_signal@1", "args": {"key": "cost_usd", "order": "up"}}},
        {"reduce": {"op": "by_signal@1", "args": {"key": "cost_usd"}}},
        {"extract": {"op": "boxed@1", "args": {}}},
        {"normalize": {"op": "numeric@1", "args": {}}},
        {"weights": {"signal": "cost_usd"}},
        {"select": {"op": "best_holder@1", "args": {"order": "min", "x": 1}}},
        {"select": {"op": "first_holder@1", "args": {}}},
    ],
    ids=[
        "orders differ",
        "unknown key",
        "judge key",
        "key not text",
        "bad order",
        "no order",
        "stray extract",
        "stray normalize",
        "weights",
        "stray select arg",
        "other select",
    ],
)
def test_a_tampered_argmax_spec_cannot_be_rebuilt(change: dict[str, Any]) -> None:
    spec = {
        **_synthesis_spec(_url4(_fusion(sf.Pick(by_signal=sf.signal("cost_usd"), order="min")))),
        **change,
    }

    with pytest.raises(ValueError, match="URL4 Candidate has a pick spec this SDK version cannot"):
        _recover_from(spec)


def test_a_tampered_argmax_url4_is_refused_through_the_url4_reader() -> None:
    url4 = _url4(_fusion(sf.Pick(by_signal=sf.signal("cost_usd"), order="min")))
    spec = _synthesis_spec(url4)
    spec["select"] = {"op": "best_holder@1", "args": {"order": "max"}}
    call = replace(_synthesis_call(url4), raw_intent=json.dumps(spec))

    with pytest.raises(ValueError, match="pick spec this SDK version cannot rebuild"):
        _reducer_from_call(call)
