"""sf.Consistency: how often a member gives the same answer again (E4b part 7, consistency@N).

FEATURE: ``sf.Fusion(members, signals={"cons": sf.Consistency(n=5)}, ...)`` asks each member n
more times with distinct seeds at the stated temperature (ans:Q3).
STORY: as a benchmark author, I pick the member answer that its model gives most often again.
INVARIANT defended: n is an int from 1 to 32 and the temperature a finite number >= 0, default
1.0 (P2); a Fusion declares at most one sf.Consistency, each member is one sf.Model, at most 1024
extra calls, and no member seed equals a sample seed of the Fusion (P4, P5; erd CN-I1..CN-I5).
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

import screamingface as sf
from screamingface.signal_sources import consistency_seed

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
# The F1 match of consistency-api CA-3 (a Pick has no extract: last_line@1 and text@1).
_F1_MATCH: dict[str, object] = {
    "extract": {"args": {}, "op": "last_line@1"},
    "normalize": {"args": {}, "op": "text@1"},
}
_SNAPSHOT = Path(__file__).resolve().parent / "public_surface_snapshot.json"
_DS_I3 = (
    "Fusion signals= needs a reducer synthesizer such as sf.Vote, sf.Median, sf.Mean, "
    "sf.Pick, sf.Rank or sf.Filter: a model synthesizer has no combine step to record them"
)


def _pick() -> sf.Pick:
    return sf.Pick(by_signal=sf.signal("cons"))


# --- CA#2: the source holds n and the temperature (CA-1, CA-E1) --------------------------------


def test_consistency_holds_n_and_the_temperature() -> None:
    five = sf.Consistency(n=5)

    assert five.n == 5
    assert five.temperature == 1.0
    assert type(five.temperature) is float
    assert repr(five) == "Consistency(n=5, temperature=1.0)"
    assert five._python() == "sf.Consistency(n=5, temperature=1.0)"
    assert five.source == "consistency"
    assert isinstance(five, sf.Consistency)
    assert five._spec() == {"source": "consistency", "n": 5, "temperature": 1.0}
    assert list(five._spec()) == ["source", "n", "temperature"]
    entry = five._entry(_F1_MATCH)
    assert entry == {"source": "consistency", "n": 5, "temperature": 1.0, "match": _F1_MATCH}
    assert list(entry) == ["source", "n", "temperature", "match"]
    assert entry["match"] is not _F1_MATCH  # a copy: the caller's mapping is not shared
    assert five._entry(MappingProxyType({"extract": None, "normalize": None}))["match"] == {
        "extract": None,
        "normalize": None,
    }
    assert "match" not in five._spec()  # _entry did not change the source
    zero = sf.Consistency(3, temperature=0)
    assert type(zero.temperature) is float
    assert json.dumps(zero._spec()) == '{"source": "consistency", "n": 3, "temperature": 0.0}'
    assert repr(sf.Consistency(1, temperature=-0.0)) == "Consistency(n=1, temperature=0.0)"
    assert repr(sf.Consistency(32, temperature=0.7)) == "Consistency(n=32, temperature=0.7)"
    assert sf.Consistency(5) == sf.Consistency(n=5, temperature=1)
    assert hash(sf.Consistency(5)) == hash(sf.Consistency(n=5, temperature=1.0))
    assert sf.Consistency(5) != sf.Consistency(5, temperature=0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        five.n = 6  # type: ignore[misc]


_N_TEXT = "sf.Consistency n must be an int from 1 to 32, not {!r}"
_T_TEXT = "sf.Consistency temperature must be a finite number of at least 0, not {!r}"
_HUGE = 10**400  # beyond the float range


@pytest.mark.parametrize(
    ("n", "temperature", "message"),
    [
        pytest.param(0, 1.0, _N_TEXT.format(0), id="n-0"),
        pytest.param(33, 1.0, _N_TEXT.format(33), id="n-33"),
        pytest.param(-1, 1.0, _N_TEXT.format(-1), id="n-negative"),
        pytest.param(True, 1.0, _N_TEXT.format(True), id="n-bool"),
        pytest.param(2.5, 1.0, _N_TEXT.format(2.5), id="n-float"),
        pytest.param(3.0, 1.0, _N_TEXT.format(3.0), id="n-integral-float"),
        pytest.param("3", 1.0, _N_TEXT.format("3"), id="n-text"),
        pytest.param(None, 1.0, _N_TEXT.format(None), id="n-none"),
        pytest.param(3, -0.1, _T_TEXT.format(-0.1), id="t-negative"),
        pytest.param(3, float("nan"), _T_TEXT.format(float("nan")), id="t-nan"),
        pytest.param(3, float("inf"), _T_TEXT.format(float("inf")), id="t-inf"),
        pytest.param(3, True, _T_TEXT.format(True), id="t-bool"),
        pytest.param(3, "1", _T_TEXT.format("1"), id="t-text"),
        pytest.param(3, None, _T_TEXT.format(None), id="t-none"),
        pytest.param(3, _HUGE, _T_TEXT.format(_HUGE), id="t-huge-int"),
        pytest.param(0, -1.0, _N_TEXT.format(0), id="n-checked-first"),
    ],
)
def test_consistency_refuses_bad_values(n: Any, temperature: Any, message: str) -> None:
    with pytest.raises(ValueError) as caught:
        sf.Consistency(n, temperature=temperature)
    assert str(caught.value) == message


def test_consistency_seed_gives_the_erd_seeds() -> None:
    # erd §2 hand-computed oracles: s(k, j) for k, j in 1..3.
    assert [consistency_seed(k, j) for k in (1, 2, 3) for j in (1, 2, 3)] == [
        2063835758,
        10968804,
        1079774124,
        966517312,
        107840383,
        1732381022,
        1073252422,
        137802004,
        992611152,
    ]
    seeds = {consistency_seed(k, j) for k in range(1, 257) for j in range(1, 33)}
    assert len(seeds) == 256 * 32  # all different (P5)
    assert min(seeds) == 134114  # never a default sf.samples() seed 0..255
    assert all(0 <= seed < 2**31 for seed in seeds)


# --- CA#3: a Fusion refuses a bad declaration before any call (CA-E2) ---------------------------

_NESTED = sf.Fusion(["prov/x", "prov/y"], name="inner", synthesizer=sf.Vote())
_CHAIN = sf.Pipeline(["prov/x", "prov/y"], name="chain")
_THIRTY_THREE = [f"prov/m{index}" for index in range(1, 34)]


@pytest.mark.parametrize(
    ("members", "signals", "synthesizer", "message"),
    [
        pytest.param(
            _MEMBERS,
            {"cons": sf.Consistency(n=2), "again": sf.Consistency(n=3)},
            _pick(),
            "a Fusion declares at most one sf.Consistency source: every member gets one set "
            "of samples",
            id="two-consistency",
        ),
        pytest.param(
            ["prov/alpha", _NESTED, "prov/gamma"],
            {"cons": sf.Consistency(n=2)},
            _pick(),
            "sf.Consistency needs each Fusion member to be one sf.Model call; member 2 "
            "('inner') is a nested Fusion or Pipeline",
            id="member-2-fusion",
        ),
        pytest.param(
            [_CHAIN, "prov/beta"],
            {"cons": sf.Consistency(n=2)},
            _pick(),
            "sf.Consistency needs each Fusion member to be one sf.Model call; member 1 "
            "('chain') is a nested Fusion or Pipeline",
            id="member-1-pipeline",
        ),
        pytest.param(
            _THIRTY_THREE,
            {"cons": sf.Consistency(n=32)},
            _pick(),
            "sf.Consistency(n=32) on 33 members makes 1056 extra calls; the limit is 1024 per "
            "Fusion",
            id="over-1024-calls",
        ),
        pytest.param(
            [sf.Model("prov/alpha", params={"seed": 2063835758}), "prov/beta", "prov/gamma"],
            {"cons": sf.Consistency(n=1)},
            _pick(),
            "member 1 ('alpha') sets seed=2063835758, which is the seed of consistency sample 1 "
            "of member 1; choose another seed",
            id="member-1-own-sample-seed",
        ),
        pytest.param(
            ["prov/alpha", sf.Model("prov/beta", params={"seed": 2063835758}), "prov/gamma"],
            {"cons": sf.Consistency(n=1)},
            _pick(),
            "member 2 ('beta') sets seed=2063835758, which is the seed of consistency sample 1 "
            "of member 1; choose another seed",
            id="member-2-other-member-seed",
        ),
        pytest.param(
            ["prov/alpha", "prov/beta", sf.Model("prov/gamma", params={"seed": "137802004"})],
            {"cons": sf.Consistency(n=3)},
            _pick(),
            "member 3 ('gamma') sets seed=137802004, which is the seed of consistency sample 2 "
            "of member 3; choose another seed",
            id="member-3-seed-as-text",
        ),
        pytest.param(
            _MEMBERS,
            {"cons": sf.Consistency(n=2)},
            "prov/judge",
            _DS_I3,
            id="model-synthesizer",
        ),
    ],
)
def test_fusion_refuses_a_bad_consistency_declaration_before_any_call(
    members: list[Any], signals: dict[str, Any], synthesizer: Any, message: str
) -> None:
    with pytest.raises(ValueError) as caught:
        sf.Fusion(members, signals=signals, synthesizer=synthesizer)
    assert str(caught.value) == message


def test_fusion_accepts_a_consistency_declaration_at_the_limits() -> None:
    at_cap = sf.Fusion(
        [f"prov/m{index}" for index in range(1, 33)],
        signals={"cons": sf.Consistency(n=32)},
        synthesizer=_pick(),
    )
    assert at_cap.signals == {"cons": sf.Consistency(n=32)}
    assert "signals={'cons': Consistency(n=32, temperature=1.0)}" in repr(at_cap)
    seeded = sf.Fusion(
        [
            *sf.samples("prov/alpha", 3),  # seeds 0, 1, 2 are never sample seeds
            sf.Model("prov/beta", params={"seed": 107840383}),  # s(2, 2), but n=1
            sf.Model("prov/gamma", params={"seed": True}),  # a bool is never a seed
            sf.Model("prov/delta", params={"seed": 2063835758.0}),  # the url4 text differs
        ],
        signals={"cons": sf.Consistency(n=1), "conf": sf.Verbalized(r"Confidence: ([0-9]+)")},
        synthesizer=_pick(),
    )
    assert list(seeded.signals or {}) == ["conf", "cons"]


# --- CA#14: the public surface has sf.Consistency (PIN) ----------------------------------------


def test_public_surface_has_sf_consistency() -> None:
    assert "Consistency" in sf.__all__
    signature = str(inspect.signature(sf.Consistency.__init__))
    assert signature == "(self, n: 'int', *, temperature: 'float' = 1.0) -> 'None'"
    assert [field.name for field in dataclasses.fields(sf.Consistency)] == ["n", "temperature"]
    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["screamingface"]
    assert "Consistency" in snapshot["__all__"]
    assert snapshot["exports"]["Consistency"] == {
        "kind": "class",
        "members": {
            "__init__": f"method {signature}",
            "n": "field",
            "source": "attribute",
            "temperature": "field",
        },
    }
