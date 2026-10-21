"""sf.Sum: a declared derived signal of a Fusion (E4b part 6, unit 2; PRD sum-api SA#1-SA#11).

FEATURE: ``signals={"risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}), ...}`` gives each member
risk = 0.5 x sev_a + 0.3 x sev_b, and any rule or gate reads it by name (ans:Q1).
STORY: as a benchmark author, I sum the severities that a member states with fixed coefficients
and pick the member with the lowest total; a mistake fails at construction, before any call.
INVARIANT defended: the terms are sorted floats (one url4 spelling, P2); a component is a declared
non-sum name of the same Fusion (P3); a sum that adds a raw logprob or an entropy is not a vote
weight (P13); the url4 rebuilds the same Python (P15); a Fusion without a sum keeps its bytes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import MappingProxyType
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app
from _nodes import FusionNode
from _vote_run_fixtures import spec_of
from test_gate_contract_fixtures import gate_verbalized_vote_url4
from test_verbalized_contract_fixture import verbalized_vote_url4

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.chain import Step
from screamingface._surface.lowering import lower
from screamingface.signal_sources import SignalSource, declared_from_spec, injected_member_params

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
_OPENROUTER = ["openrouter/acme/alpha", "openrouter/acme/beta", "openrouter/acme/gamma"]
_A = "A: ([0-9]+)"
_B = "B: ([0-9]+)"
_CONF = "Confidence: ([0-9]+)"
_CANNOT_REBUILD = "URL4 Candidate has a signals declaration this SDK version cannot rebuild"
_SUM_ENTRY = '"risk":{"coefficients":{"sev_a":0.5,"sev_b":0.3},"source":"sum"}'
_SPEC_SIGNALS = {
    "risk": {"coefficients": {"sev_a": 0.5, "sev_b": 0.3}, "source": "sum"},
    "sev_a": {"pattern": _A, "source": "verbalized"},
    "sev_b": {"pattern": _B, "source": "verbalized"},
}
_SIGNALS_LINE = (
    "    sf.Fanout(['prov/alpha', 'prov/beta', 'prov/gamma'], "
    "signals={'risk': sf.Sum({'sev_a': 0.5, 'sev_b': 0.3}), "
    "'sev_a': sf.Verbalized('A: ([0-9]+)'), 'sev_b': sf.Verbalized('B: ([0-9]+)')}, name='pick')"
)


def _declaration(risk: sf.Sum | None = None) -> dict[str, SignalSource]:
    return {
        "risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}) if risk is None else risk,
        "sev_a": sf.Verbalized(_A),
        "sev_b": sf.Verbalized(_B),
    }


def _recipe_r(risk: sf.Sum | None = None, terminal: Step | None = None) -> sf.Pipeline:
    """Recipe R of the sum-api PRD §3, or R with another terminal step."""
    return sf.Fanout(_MEMBERS, name="pick", signals=_declaration(risk)) >> (
        sf.ArgMin("risk") if terminal is None else terminal
    )


def _fanout(recipe: sf.Recipe) -> sf.Fanout:
    """The ``sf.Fanout`` that opens ``recipe``, a chain of one block."""
    assert isinstance(recipe, sf.Pipeline)
    fanout = recipe.steps[0]
    assert isinstance(fanout, sf.Fanout)
    return fanout


def _compiled(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def _pick(name: str) -> sf.ArgMin:
    return sf.ArgMin(sf.signal(name))


# --- SA#1 (CHAR, SA-D1): a Fusion without an sf.Sum compiles to the same url4 bytes ------------


@requires_engine_app
@pytest.mark.parametrize(
    ("name", "builder"),
    [
        ("verbalized_vote_candidate.url4", verbalized_vote_url4),
        ("gate_verbalized_vote_candidate.url4", gate_verbalized_vote_url4),
    ],
)
def test_fusions_without_a_sum_compile_unchanged(name: str, builder: Callable[[], str]) -> None:
    assert ENGINE_APP.exists()
    fixture = (COMBINE_CONTRACT / name).read_text(encoding="utf-8").removesuffix("\n")
    assert fixture == builder()
    assert '"source":"sum"' not in fixture


# --- SA#2 (SA-1, SA-D5): sorted float terms, a short repr, unhashable ---------------------------


def test_sum_keeps_sorted_float_coefficients_and_a_short_repr() -> None:
    terms: dict[str, float] = {"sev_b": 0.3, "sev_a": 1}
    total = sf.Sum(terms)
    terms["zzz"] = 2.0  # a later change of the input does not reach the sum

    assert dict(total.coefficients) == {"sev_a": 1.0, "sev_b": 0.3}
    assert list(total.coefficients) == ["sev_a", "sev_b"]
    assert [type(value) for value in total.coefficients.values()] == [float, float]
    assert isinstance(total.coefficients, MappingProxyType)
    assert repr(total) == "Sum({'sev_a': 1.0, 'sev_b': 0.3})"
    assert total.source == "sum"
    assert isinstance(total, SignalSource)
    assert "Sum" in sf.__all__
    assert sf.Sum({"b": 2, "a": -0.5}) == sf.Sum({"a": -0.5, "b": 2.0})
    assert sf.Sum({"a": 1.0}) != sf.Sum({"a": 2.0})
    with pytest.raises(TypeError):
        hash(total)


# --- SA#3 (SA-E1): each bad term gives its exact error ------------------------------------------


def _not_declared(name: str) -> str:
    return (
        f"sf.Sum adds {name!r}, which is not a declared signal name; an E4a key such as "
        "cost_usd cannot be a sum component"
    )


_BAD_TERMS: list[Any] = [
    pytest.param(
        [("a", 1.0)],
        TypeError,
        "sf.Sum takes a mapping of declared names to numbers, such as {'sev_a': 0.5}",
        id="not-a-mapping",
    ),
    pytest.param({}, ValueError, "sf.Sum adds 1 to 7 declared names, not 0", id="empty"),
    pytest.param(
        {f"a{index}": 1.0 for index in range(1, 9)},
        ValueError,
        "sf.Sum adds 1 to 7 declared names, not 8",
        id="eight",
    ),
    pytest.param({1: 0.5}, TypeError, "sf.Sum names must be text", id="int-name"),
    pytest.param({"cost_usd": 0.5}, ValueError, _not_declared("cost_usd"), id="e4a-key"),
    pytest.param({"Sev": 0.5}, ValueError, _not_declared("Sev"), id="upper-case"),
    pytest.param({"logprob_x": 0.5}, ValueError, _not_declared("logprob_x"), id="reserved"),
    pytest.param({"a": True}, TypeError, "sf.Sum coefficient of 'a' must be a number", id="bool"),
    pytest.param({"a": "0.5"}, TypeError, "sf.Sum coefficient of 'a' must be a number", id="text"),
    pytest.param({"a": 10**400}, ValueError, "sf.Sum coefficient of 'a' must be finite", id="huge"),
    pytest.param(
        {"a": float("inf")}, ValueError, "sf.Sum coefficient of 'a' must be finite", id="inf"
    ),
    pytest.param(
        {"a": float("nan")}, ValueError, "sf.Sum coefficient of 'a' must be finite", id="nan"
    ),
    pytest.param({"a": 0}, ValueError, "sf.Sum coefficient of 'a' must not be zero", id="zero"),
    pytest.param(
        {"a": -0.0}, ValueError, "sf.Sum coefficient of 'a' must not be zero", id="minus-zero"
    ),
]


@pytest.mark.parametrize(("value", "error", "message"), _BAD_TERMS)
def test_sum_refuses_bad_terms(value: Any, error: type[Exception], message: str) -> None:
    with pytest.raises(error) as caught:
        sf.Sum(value)
    assert type(caught.value) is error
    assert str(caught.value) == message


# --- SA#4 (SA-E2): a component the Fusion does not declare --------------------------------------


def test_fusion_refuses_a_sum_of_an_undeclared_name() -> None:
    message = (
        "sf.Sum 'risk' adds 'zzz', which this sf.Fanout does not declare (declared: risk, sev_a)"
    )
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(
            _MEMBERS,
            signals={"risk": sf.Sum({"sev_a": 0.5, "zzz": 1.0}), "sev_a": sf.Verbalized(_A)},
        ) >> _pick("risk")
    assert str(caught.value) == message
    # the listed names are sorted, whatever the dict order of signals=
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(
            _MEMBERS,
            signals={"sev_a": sf.Verbalized(_A), "risk": sf.Sum({"zzz": 1.0, "sev_a": 0.5})},
        ) >> _pick("risk")
    assert str(caught.value) == message


# --- SA#5 (SA-E3): a sum of a sum, and a sum of itself ------------------------------------------


def test_fusion_refuses_a_sum_of_a_sum_and_a_sum_of_itself() -> None:
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(
            _MEMBERS,
            signals={
                "a": sf.Verbalized(_A),
                "r1": sf.Sum({"a": 1.0}),
                "r2": sf.Sum({"r1": 1.0}),
            },
        ) >> _pick("r2")
    assert str(caught.value) == (
        "sf.Sum 'r2' adds 'r1', which is an sf.Sum; a sum adds only other sources, not sums"
    )
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(_MEMBERS, signals={"r": sf.Sum({"r": 1.0})}) >> _pick("r")
    assert str(caught.value) == (
        "sf.Sum 'r' adds 'r', which is an sf.Sum; a sum adds only other sources, not sums"
    )


# --- SA#6 (SA-E4, P13): a sum with a raw logprob or an entropy is not a vote weight --------------

_WEIGHTED: list[Any] = [
    pytest.param(lambda s: sf.Vote(weights=s), id="vote"),
    pytest.param(lambda s: sf.Median(weights=s), id="median"),
    pytest.param(lambda s: sf.Mean(weights=s), id="mean"),
]
_RAW: list[Any] = [
    pytest.param(lambda: sf.Logprob("mean"), "Logprob('mean')", id="logprob-mean"),
    pytest.param(lambda: sf.Logprob("sum"), "Logprob('sum')", id="logprob-sum"),
    pytest.param(lambda: sf.Entropy(), "Entropy(top_logprobs=5)", id="entropy"),
]


def _weight_signals(lp: SignalSource) -> dict[str, SignalSource]:
    return {"w": sf.Sum({"lp": 1.0, "conf": 0.01}), "lp": lp, "conf": sf.Verbalized(_CONF)}


@pytest.mark.parametrize("weighted", _WEIGHTED)
@pytest.mark.parametrize(("raw", "shown"), _RAW)
def test_fusion_refuses_a_vote_weight_sum_with_a_raw_logprob_or_entropy(
    weighted: Callable[[Any], Step], raw: Callable[[], SignalSource], shown: str
) -> None:
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(_OPENROUTER, signals=_weight_signals(raw())) >> weighted(sf.signal("w"))
    assert str(caught.value) == (
        f"sf.Sum 'w' cannot be a vote weight: it adds 'lp' ({shown}), and a weight must be "
        "greater than 0; read sf.signal('w') with sf.ArgMax, sf.Rank or sf.Filter instead"
    )


def test_a_sum_weight_may_add_a_logprob_prob_and_a_pick_may_read_any_sum() -> None:
    weighted = sf.Fanout(_OPENROUTER, signals=_weight_signals(sf.Logprob("prob"))) >> sf.Vote(
        weights=sf.signal("w")
    )
    weights = _fanout(weighted).signals
    assert weights is not None
    assert weights["w"] == sf.Sum({"conf": 0.01, "lp": 1.0})
    for raw in (sf.Logprob("mean"), sf.Logprob("sum"), sf.Entropy()):
        picked = sf.Fanout(_OPENROUTER, signals=_weight_signals(raw)) >> sf.ArgMax("w")
        declared = _fanout(picked).signals
        assert declared is not None
        assert declared["lp"] == raw


# --- SA#7 (SA-3, SA-D4): every rule and gate reads a sum by name --------------------------------

_READERS: list[Any] = [
    pytest.param(lambda: sf.ArgMin("risk"), id="pick"),
    pytest.param(lambda: sf.Rank(1, by="risk", order="min"), id="rank"),
    pytest.param(lambda: sf.Filter(where=sf.signal("risk") <= 3.0), id="filter"),
    pytest.param(lambda: sf.Vote(weights=sf.signal("risk")), id="vote-weight"),
    pytest.param(
        lambda: sf.Gate(when=sf.signal("risk").chosen() <= 3.0, then=sf.Vote()), id="gate-chosen"
    ),
    pytest.param(
        lambda: sf.Gate(when=sf.signal("risk").mean() <= 3.0, then=sf.Vote()), id="gate-mean"
    ),
]


@pytest.mark.parametrize("reader", _READERS)
def test_rules_and_gates_read_a_sum_by_name(reader: Callable[[], Step]) -> None:
    step = reader()
    fusion = _recipe_r(terminal=step)
    signals = _fanout(fusion).signals
    assert signals is not None
    assert list(signals) == ["risk", "sev_a", "sev_b"]
    # WHY the next stage: a Rank or a Filter ends a candidate with a selection, and the compile
    # refuses that unless a writer follows (test_rank_by_signal.py _wrapped precedent)
    narrow = isinstance(step, sf.Rank | sf.Filter)
    spec = spec_of(
        _compiled(fusion >> (sf.Synthesize("provider/next") if narrow else "provider/next"))
    )
    assert spec["signals"] == _SPEC_SIGNALS
    # the rule or the gate names the sum outside the signals map
    assert "risk" in json.dumps({key: value for key, value in spec.items() if key != "signals"})


def test_a_sum_counts_toward_the_eight_names() -> None:
    names: dict[str, SignalSource] = {f"a{index}": sf.Verbalized(_A) for index in range(1, 8)}
    fusion = sf.Fanout(_MEMBERS, signals={"s": sf.Sum({"a1": 1.0}), **names}) >> _pick("s")
    signals = _fanout(fusion).signals
    assert signals is not None
    assert len(signals) == 8
    with pytest.raises(ValueError) as caught:
        _ = sf.Fanout(
            _MEMBERS, signals={"s": sf.Sum({"a1": 1.0}), "a8": sf.Verbalized(_A), **names}
        ) >> _pick("s")
    assert str(caught.value) == "a sf.Fanout declares at most 8 signals, not 9"


# --- SA#8 (SA-2): the compile writes the sum entry ----------------------------------------------


def test_compile_writes_the_sum_entry() -> None:
    url4 = _compiled(_recipe_r())
    assert spec_of(url4)["signals"] == _SPEC_SIGNALS
    assert _SUM_ENTRY in url4
    # the input order of the terms does not change the bytes
    assert _compiled(_recipe_r(sf.Sum({"sev_b": 0.3, "sev_a": 0.5}))) == url4
    entry = sf.Sum({"b": 2, "a": -0.5})._spec()
    assert json.dumps(entry) == '{"source": "sum", "coefficients": {"a": -0.5, "b": 2.0}}'


# --- SA#9 (SA-D3): a sum adds no member call param ----------------------------------------------


def test_a_sum_adds_no_member_param() -> None:
    plain = {"risk": sf.Sum({"a": 1.0}), "a": sf.Verbalized(_A)}
    assert injected_member_params(plain) == {}
    with_prob = {"risk": sf.Sum({"a": 1.0}), "a": sf.Logprob("prob")}
    assert injected_member_params(with_prob) == {"logprobs": True}


# --- SA#10 (SA-4, P15): the url4 rebuilds the same Python ---------------------------------------


def test_url4_rebuilds_a_sum() -> None:
    fusion = _recipe_r()
    url4 = _compiled(fusion)
    code = sf.Url4(url4).to_python()
    assert _SIGNALS_LINE in code.splitlines()
    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 - our own generated code
    recovered = namespace["candidate"]
    assert recovered == fusion
    assert repr(recovered) == repr(fusion)
    node, lowered = lower(recovered), lower(fusion)
    assert isinstance(node, FusionNode)
    assert isinstance(lowered, FusionNode)
    assert node.signals == lowered.signals
    assert _compiled(recovered) == url4


# --- SA#11 (SA-D2): a hand-edited sum entry does not rebuild ------------------------------------

_HAND_EDITS: list[Any] = [
    pytest.param(
        '"risk":{"coefficients":{"sev_a":0.5,"sev_b":0.3},"note":1,"source":"sum"}', id="extra-key"
    ),
    pytest.param('"risk":{"coefficients":[0.5,0.3],"source":"sum"}', id="list"),
    pytest.param('"risk":{"coefficients":{"sev_a":true,"sev_b":0.3},"source":"sum"}', id="bool"),
    pytest.param('"risk":{"coefficients":{"sev_a":0,"sev_b":0.3},"source":"sum"}', id="zero"),
    pytest.param(
        '"risk":{"coefficients":{"sev_a":0.5,"sev_b":0.3},"source":"sums"}', id="source-word"
    ),
]


@pytest.mark.parametrize("edited", _HAND_EDITS)
def test_rebuild_refuses_a_hand_edited_sum_entry(edited: str) -> None:
    url4 = _compiled(_recipe_r())
    assert _SUM_ENTRY in url4
    with pytest.raises(ValueError) as caught:
        sf.Url4(url4.replace(_SUM_ENTRY, edited)).to_python()
    assert str(caught.value) == _CANNOT_REBUILD


def test_declared_from_spec_rebuilds_and_refuses_sum_entries() -> None:
    verbalized = {"source": "verbalized", "pattern": _A}
    rebuilt = declared_from_spec(
        {"a": verbalized, "risk": {"source": "sum", "coefficients": {"a": 1}}}
    )
    assert rebuilt == {"a": sf.Verbalized(_A), "risk": sf.Sum({"a": 1.0})}
    bad_entries: list[Any] = [
        {"source": "sum"},
        {"source": "sum", "coefficients": {}},
        {"source": "sum", "coefficients": {"a": None}},
        {"source": "sum", "coefficients": {"a": float("nan")}},
        {"source": "sum", "coefficients": {"A": 1.0}},
        {"source": "sum", "coefficients": {1: 1.0}},
        {"source": "sum", "coefficients": {"a": 1.0}, "form": "mean"},
    ]
    for entry in bad_entries:
        with pytest.raises(ValueError, match="cannot rebuild"):
            declared_from_spec({"risk": entry})
