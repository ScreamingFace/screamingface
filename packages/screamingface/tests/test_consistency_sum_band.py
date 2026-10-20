"""Part 6 and part 7 together in the SDK (restack of part 7 on part 6, 2026-10-16).

FEATURE: one Fusion may declare ``sf.Consistency`` and an ``sf.Sum`` that adds it, and gate on its
mean with an abstain band. The part 7 recompile trigger (any combine spec that declares
``signals``, S/url4.py ``_validate_topology``) now also covers the part 6 sum and band url4s.
STORY: as a benchmark author, I compile ``signals={"cons": sf.Consistency(n=2), "risk":
sf.Sum({"cons": -1.0})}`` and get it back from the url4; a researcher replays the part 6 contract
url4s with no change.
INVARIANT defended: a sum may add a consistency name (the Engine computes the consistency value
before any sum); every url4 below recompiles byte-for-byte; the SDK decodes and writes back an
evidence with both new optional keys (``consistency`` before ``declared``, ``gate`` with
``abstain_band`` after it), in that order.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, read_contract, requires_engine_app
from test_consistency_display import _N, _SAMPLES_CHIP, _chip, _section, _wire
from test_consistency_rebuild import _MEMBERS, _linked, _rebuilt, _recompiled, _spec_of, _url4

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.combine_evidence import CombineEvidence

# The part 6 contract url4s, written out (never a glob). Each one declares `signals`.
_PART_6_URL4 = ("sum_pick_candidate.url4", "gate_band_vote_candidate.url4")


def _sum_pick() -> sf.Fusion:
    return sx.Fanout(
        _MEMBERS, signals={"cons": sf.Consistency(n=2), "risk": sf.Sum({"cons": -1.0})}, name="pick"
    ) >> sx.ArgMin("risk")


def _band_vote() -> sf.Fusion:
    return sx.Fanout(_MEMBERS, signals={"cons": sf.Consistency(n=2)}, name="vote") >> sx.Gate(
        when=sx.signal("cons").mean() >= 0.9,
        then=sx.Vote(),
        abstain_if=sx.signal("cons").mean().between(0.7, 0.8),
    )


def _sum_band_vote() -> sf.Fusion:
    return sx.Fanout(
        _MEMBERS, signals={"cons": sf.Consistency(n=2), "risk": sf.Sum({"cons": 3.0})}, name="vote"
    ) >> sx.Gate(
        when=sx.signal("risk").mean() >= 3.0,
        then=sx.Vote(),
        abstain_if=sx.signal("risk").mean().between(2.0, 2.5),
    )


_RECIPES: dict[str, Callable[[], sf.Fusion]] = {
    "sum-of-consistency-pick": _sum_pick,
    "band-on-mean-consistency": _band_vote,
    "band-on-mean-sum-of-consistency": _sum_band_vote,
}


# --- (a), (b): the SDK compiles, rebuilds and replays a recipe with both ---------------------


@pytest.mark.parametrize("name", list(_RECIPES))
def test_a_recipe_with_consistency_and_a_sum_or_a_band_round_trips(name: str) -> None:
    recipe = _RECIPES[name]()
    url4 = _url4(recipe)

    assert _recompiled(url4) == url4
    rebuilt = _rebuilt(url4)
    assert isinstance(rebuilt, sf.Fusion)
    assert dict(rebuilt.signals or {}) == dict(recipe.signals or {})
    _candidate_from_url4(_linked(url4))  # the replay takes the byte-for-byte recompile too


def test_the_spec_holds_the_consistency_entry_and_the_sum_of_it() -> None:
    signals = _spec_of(_url4(_sum_pick()))["signals"]

    assert list(signals) == ["cons", "risk"]
    assert signals["cons"]["source"] == "consistency"
    assert signals["risk"] == {"source": "sum", "coefficients": {"cons": -1.0}}


def test_a_band_gate_on_a_consistency_mean_is_in_the_spec() -> None:
    gate = _spec_of(_url4(_band_vote()))["gate"]

    assert gate["observe"] == "mean:cons"
    assert gate["abstain_band"] == [0.7, 0.8]


# --- (c): the part 6 url4s take the part 7 recompile trigger and still recompile -------------


@pytest.mark.parametrize("name", _PART_6_URL4)
def test_the_part_6_contract_url4s_recompile_byte_for_byte(name: str) -> None:
    url4 = read_contract(name)

    assert '"signals":{' in url4  # so the part 7 trigger runs the recompile for it
    assert _recompiled(url4) == url4
    assert isinstance(_rebuilt(url4), sf.Fusion)
    _candidate_from_url4(_linked(url4))


# --- (d): the SDK reads and writes both new optional keys, in order ---------------------------


@requires_engine_app
def test_sdk_decodes_an_evidence_with_consistency_and_a_gate_band() -> None:
    # The Engine fixture V vote (consistency_vote), plus a hand-built gate on mean:cons. Fixture V:
    # cons is 0.5, 1.0 and no value, so the mean is 0.75: outside [0.8, 0.9], and 0.75 >= 0.7.
    cases = json.loads(
        (COMBINE_CONTRACT / "consistency_evidence_cases.json").read_text(encoding="utf-8")
    )
    base: dict[str, Any] = cases["consistency_vote"]
    wire: dict[str, Any] = {}
    for key, value in base.items():
        wire[key] = value
        if key == "declared":
            wire["gate"] = {
                "observe": "mean:cons",
                "observed": 0.75,
                "cmp": ">=",
                "threshold": 0.7,
                "passed": True,
                "branch": "majority",
                "otherwise": "abstain",
                "abstain_band": [0.8, 0.9],
            }

    decoded = decode_combine_evidence(wire, "restack evidence")

    assert isinstance(decoded, CombineEvidence)
    assert decoded.consistency is not None
    assert decoded.gate is not None
    assert decoded.gate.abstain_band == (0.8, 0.9)
    assert decoded.to_dict() == wire
    keys = list(decoded.to_dict())
    at = keys.index("consistency")
    assert keys[at : at + 3] == ["consistency", "declared", "gate"]


@requires_engine_app
def test_case_pane_shows_the_samples_chip_and_the_band_chip() -> None:
    # The part 7 samples chip and the part 6 band chip on one step; hand-written from fixture V
    # (4 per member, 0 + 2 + 4 = 6 of 12 failed) and the gate above.
    wire = _wire("consistency_vote")
    wire["gate"] = {
        "observe": "mean:cons",
        "observed": 0.75,
        "cmp": ">=",
        "threshold": 0.7,
        "passed": True,
        "branch": "majority",
        "otherwise": "abstain",
        "abstain_band": [0.8, 0.9],
    }

    section = _section(wire)

    assert _SAMPLES_CHIP.findall(section) == [
        _chip("samples · cons · 4 per member · failed 6 of 12")
    ]
    gate = _chip(
        f"gate · mean:cons &gt;= {_n('0.7')} · band [{_n('0.8')}, {_n('0.9')}]"
        f" · observed {_n('0.75')} · majority"
    )
    assert gate in section


def _n(text: str) -> str:
    return _N.format(title=text, text=text)
