"""The abstain band on sf.Gate: keyword, compile and rebuild (E4b part 6, unit 5; BA#1-6).

FEATURE: sf.Gate(..., abstain_band=(lo, hi)) names the numbers that are too close to call. The band
is data in the spec gate ("abstain_band": [lo, hi]), and Url4.to_python() writes it back.
STORY: as a benchmark author, I write sf.Gate("mean:risk", "<=", 3.0, abstain_band=(2.5, 3.5)); a
bad band fails at construction, and the url4 rebuilds the same gate.
INVARIANT defended: a gate without a band keeps its part 5 bytes, repr and fixtures (BA-D1); a band
is a closed pair of finite floats with lo <= hi (P7); a hand-edited band never rebuilds as a
different gate (BA-E2).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from _combine_contract import engine_operators, requires_engine_app
from _vote_run_fixtures import spec_of
from test_gate_contract_fixtures import assert_fixture_matches

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
_RUBRIC = "Pick the best answer."
_PAIR = "Gate abstain_band must be a pair (lo, hi) of numbers"
_FINITE = "Gate abstain_band must be finite"
_ORDER = "Gate abstain_band needs lo <= hi"
_AGREEMENT_BAND = "an agreement gate abstain_band must be between 0 and 1"
_CANNOT_REBUILD = "URL4 Candidate has a vote spec this SDK version cannot rebuild"
_BAND_SPEC = '"abstain_band":[2.5,3.5]'
_G_GATE_SPEC = (
    '"gate":{"abstain_band":[2.5,3.5],"cmp":"<=","observe":"mean:risk",'
    '"otherwise":"abstain","threshold":3.0}'
)
_G_TEXT = "sf.Gate('mean:risk', '<=', 3.0, abstain_band=(2.5, 3.5))"
_G_JUDGE_TEXT = (
    "sf.Gate('mean:risk', '<=', 3.0, otherwise=sf.Judge('prov/judge', returns='label', "
    "rubric='Pick the best answer.'), abstain_band=(2.5, 3.5))"
)
# The four part 5 gate fixtures. A FIXED tuple, never a glob (test-plan §6).
_PART5_GATE_FIXTURES: tuple[str, ...] = (
    "gate_abstain_vote_candidate.url4",
    "gate_judge_vote_candidate.url4",
    "gate_verbalized_vote_candidate.url4",
    "gate_writer_vote_candidate.url4",
)


def _judge() -> sf.Judge:
    return sx.JudgePick("prov/judge", rubric=_RUBRIC)


def _recipe_g(otherwise: Any = "abstain") -> sf.Fusion:
    """Recipe G of band-api §3; ``otherwise`` is the gate fallback (BA-3)."""

    return sf.Fusion(
        _MEMBERS,
        name="vote",
        signals={
            "risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}),
            "sev_a": sf.Verbalized("A: ([0-9]+)"),
            "sev_b": sf.Verbalized("B: ([0-9]+)"),
        },
        synthesizer=sf.Vote(
            gate=sf.Gate("mean:risk", "<=", 3.0, otherwise=otherwise, abstain_band=(2.5, 3.5))
        ),
    )


def _compiled(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def _rebuilt(url4: str) -> sf.Fusion:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Fusion)
    return candidate


# --- BA#1 (CHAR): a gate without a band keeps its part 5 form and fixtures (BA-D1) ---


@requires_engine_app
def test_a_gate_without_a_band_keeps_its_part_5_form() -> None:
    gate = sf.Gate("agreement", ">=", 0.7)
    spec = gate._spec()
    assert spec == {"cmp": ">=", "observe": "agreement", "otherwise": "abstain", "threshold": 0.7}
    assert list(spec) == ["cmp", "observe", "otherwise", "threshold"]
    assert repr(gate) == "Gate('agreement', '>=', 0.7)"
    assert gate._python() == "sf.Gate('agreement', '>=', 0.7)"
    for name in _PART5_GATE_FIXTURES:
        assert_fixture_matches(name)


# --- BA#2: a closed band is kept as two floats (BA-1, BA-D2) ---


def test_gate_takes_a_closed_band() -> None:
    listed: Any = [0.6, 0.7]
    gate = sf.Gate("agreement", ">=", 0.7, abstain_band=listed)
    assert gate.abstain_band == (0.6, 0.7)
    assert isinstance(gate.abstain_band, tuple)
    assert repr(gate) == "Gate('agreement', '>=', 0.7, abstain_band=(0.6, 0.7))"
    assert gate._python() == "sf.Gate('agreement', '>=', 0.7, abstain_band=(0.6, 0.7))"
    assert gate._spec() == {
        "cmp": ">=",
        "observe": "agreement",
        "otherwise": "abstain",
        "threshold": 0.7,
        "abstain_band": [0.6, 0.7],
    }
    ints = sf.Gate("chosen:x", "<", 1, abstain_band=(0, 2))
    band = ints.abstain_band
    assert band == (0.0, 2.0)
    assert band is not None
    assert [type(end) for end in band] == [float, float]
    assert repr(ints) == "Gate('chosen:x', '<', 1.0, abstain_band=(0.0, 2.0))"
    assert sf.Gate("agreement", ">=", 0.7, abstain_band=(0.7, 0.7)).abstain_band == (0.7, 0.7)
    assert sf.Gate("chosen:x", "<=", 1.0, abstain_band=(-5.0, 1.5)).abstain_band == (-5.0, 1.5)
    assert sf.Gate("agreement", ">=", 0.7, abstain_band=(0.6, 0.7)) == gate
    assert gate != sf.Gate("agreement", ">=", 0.7)
    assert sf.Gate("agreement", ">=", 0.7, abstain_band=None) == sf.Gate("agreement", ">=", 0.7)
    parameter = inspect.signature(sf.Gate).parameters["abstain_band"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


# --- BA#3: a bad band fails at construction with a fixed message (BA-E1) ---


@pytest.mark.parametrize(
    ("observe", "band", "error", "message"),
    [
        ("chosen:x", 0.5, TypeError, _PAIR),
        ("chosen:x", (0.5,), TypeError, _PAIR),
        ("chosen:x", (0.1, 0.2, 0.3), TypeError, _PAIR),
        ("chosen:x", "ab", TypeError, _PAIR),
        ("chosen:x", (True, 0.7), TypeError, _PAIR),
        ("chosen:x", ("0.6", 0.7), TypeError, _PAIR),
        ("chosen:x", (10**400, 0.7), ValueError, _FINITE),
        ("chosen:x", (float("nan"), 0.7), ValueError, _FINITE),
        ("chosen:x", (0.0, float("inf")), ValueError, _FINITE),
        ("chosen:x", (0.7, 0.6), ValueError, _ORDER),
        ("agreement", (0.5, 1.5), ValueError, _AGREEMENT_BAND),
        ("agreement", (-0.1, 0.5), ValueError, _AGREEMENT_BAND),
    ],
    ids=[
        "a_number",
        "one_item",
        "three_items",
        "text",
        "a_bool",
        "a_text_item",
        "an_int_too_large",
        "nan",
        "infinity",
        "lo_above_hi",
        "agreement_above_1",
        "agreement_below_0",
    ],
)
def test_gate_refuses_bad_bands(
    observe: str, band: Any, error: type[Exception], message: str
) -> None:
    with pytest.raises(error) as caught:
        sf.Gate(observe, ">=", 0.7, abstain_band=band)
    assert type(caught.value) is error
    assert str(caught.value) == message


# --- BA#4: the compile writes the band into the spec gate (BA-2) ---


@requires_engine_app
def test_compile_writes_the_band() -> None:
    url4 = _compiled(_recipe_g())
    assert spec_of(url4)["gate"] == {
        "abstain_band": [2.5, 3.5],
        "cmp": "<=",
        "observe": "mean:risk",
        "otherwise": "abstain",
        "threshold": 3.0,
    }
    assert url4.count(_G_GATE_SPEC) == 1
    judged = sf.Gate("mean:risk", "<=", 3.0, otherwise=_judge(), abstain_band=(2.5, 3.5))
    assert judged._spec() == {
        "cmp": "<=",
        "observe": "mean:risk",
        "otherwise": "judge",
        "threshold": 3.0,
        "abstain_band": [2.5, 3.5],
    }


# --- BA#5: the url4 rebuilds the band, with and without a fallback judge (BA-3) ---


@requires_engine_app
@pytest.mark.parametrize("fallback", ["abstain", "judge"])
def test_url4_rebuilds_a_band_with_and_without_a_fallback_judge(fallback: str) -> None:
    recipe = _recipe_g("abstain" if fallback == "abstain" else _judge())
    url4 = _compiled(recipe)
    text = _G_TEXT if fallback == "abstain" else _G_JUDGE_TEXT
    assert text in sf.Url4(url4).to_python()
    original, rebuilt = recipe.synthesizer, _rebuilt(url4).synthesizer
    assert isinstance(original, sf.Vote)
    assert isinstance(rebuilt, sf.Vote)
    assert rebuilt.gate is not None
    assert rebuilt.gate.abstain_band == (2.5, 3.5)
    assert rebuilt.gate == original.gate
    assert _compiled(_rebuilt(url4)) == url4


# --- BA#6: a hand-edited band never rebuilds (BA-E2); the declared-name rule holds (BA-D3) ---


@requires_engine_app
@pytest.mark.parametrize(
    "edited",
    [
        '"abstain_band":null',
        '"abstain_band":[2.5]',
        '"abstain_band":[2.5,3.5,4.5]',
        '"abstain_band":["a",3.5]',
        '"abstain_band":[3.5,2.5]',
        '"abstain_band":[2.5,3.5],"note":"x"',
    ],
    ids=["null", "one_end", "three_ends", "a_text_end", "lo_above_hi", "extra_key"],
)
def test_rebuild_refuses_a_hand_edited_band(edited: str) -> None:
    url4 = _compiled(_recipe_g())
    assert url4.count(_BAND_SPEC) == 1
    with pytest.raises(ValueError) as caught:
        sf.Url4(url4.replace(_BAND_SPEC, edited)).to_python()
    assert str(caught.value) == _CANNOT_REBUILD


def test_a_band_keeps_the_declared_name_rule() -> None:
    vote = sx.Gate(
        when=sx.signal("zzz").mean() <= 3.0,
        then=sx.Vote(),
        abstain_if=sx.signal("zzz").mean().between(2.5, 3.5),
    )
    with pytest.raises(ValueError) as caught:
        (
            sx.Fanout(
                _MEMBERS, signals={"conf": sf.Verbalized("Confidence: ([0-9]+)")}, name="vote"
            )
            >> vote
        )
    assert str(caught.value) == (
        "the gate reads 'mean:zzz', but this Fusion does not declare 'zzz' (declared: conf)"
    )
