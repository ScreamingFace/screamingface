"""sf.Budgeted, sf.Estimate and sf.budget.remaining() on the SDK: the cap, its checks, its url4.

FEATURE: E4c (OME-1291) budget rows BU#3, #12, #18, #19, #20, #24, #26 and the public names.
STORY: as a researcher whose result is a saving, I write one cap at the root of the candidate;
the SDK refuses a cap or an estimate it cannot check before any call, and a replay that saw a
different spend is marked.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest
from _combine_contract import engine_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate


def _url4(recipe: object) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4  # type: ignore[arg-type]


def _choice(when: Any = None) -> sf.Gate:
    return sf.Gate(
        when=sf.budget.remaining() >= 0.02 if when is None else when,
        then=sf.Estimate("prov/big", usd=0.03),
        otherwise="prov/small",
    )


# --- BU#3 (CHAR + keep) ---------------------------------------------------------------------------


def test_signal_budget_remaining_still_refused() -> None:
    # BU-23: budget.remaining is never an Answer signal; only sf.budget.remaining() reads it.
    with pytest.raises(ValueError, match=r"read it with sf\.budget\.remaining\(\)"):
        sf.signal("budget.remaining")


# --- BU#12 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("caps", "annotation"),
    [
        ({"usd": 0.05}, "_sf_budget:0.0:usd=0.05:'budget';budget_mode=advisory"),
        ({"tokens": 100}, "_sf_budget:0.0:tokens=100:'budget';budget_mode=advisory"),
        (
            {"usd": 0.05, "tokens": 100},
            "_sf_budget:0.0:usd=0.05:tokens=100:'budget';budget_mode=advisory",
        ),
    ],
)
def test_budget_compiles_to_candidate_source_annotation(
    caps: dict[str, Any], annotation: str
) -> None:
    # BU-1: one marker source carries the typed budget; every call under it names its binding.
    url4 = _url4(sf.Budgeted(sf.Model("prov/a"), **caps))

    assert url4.count("_sf_budget:") == 1
    assert annotation in url4
    assert "/prov/a?binding=model_1&q=($input)" in url4
    assert _url4(sf.Model("prov/a")) == url4.replace(f", {annotation}", "").replace(
        "?binding=model_1&q=($input)", "($input)"
    )


def test_budget_repr_and_url4_round_trip() -> None:
    recipe = sf.Budgeted(_choice(), usd=0.05)

    assert repr(recipe) == (
        "Budgeted(Gate(when=budget.remaining() >= 0.02, then=Estimate('prov/big', usd=0.03), "
        "otherwise='prov/small'), usd=0.05)"
    )
    namespace: dict[str, object] = {}
    exec(sf.Url4(_url4(recipe)).to_python(), namespace)  # noqa: S102 - the SDK's own code
    assert _url4(namespace["candidate"]) == _url4(recipe)


# --- BU#18 ----------------------------------------------------------------------------------------


_NOT_AT_ROOT: dict[str, Callable[[], object]] = {
    "first stage": lambda: sf.Budgeted("prov/a", usd=1) >> sf.Model("prov/b"),
    "later stage": lambda: sf.Model("prov/b") >> sf.Budgeted("prov/a", usd=1),
    "branch body": lambda: sf.Gate(when=sf.agreement() >= 0.5, then=sf.Budgeted("prov/a", usd=1)),
    "fanout member": lambda: sf.Fanout([sf.Budgeted("prov/a", usd=1), "prov/b"]),
    "nested": lambda: sf.Budgeted(sf.Budgeted("prov/a", usd=1), usd=1),
}


@pytest.mark.parametrize("build", list(_NOT_AT_ROOT.values()), ids=list(_NOT_AT_ROOT))
def test_budget_not_at_root_is_refused(build: Callable[[], object]) -> None:
    # BU-11
    with pytest.raises(ValueError, match="sf.Budgeted wraps the whole candidate: use it once, at"):
        build()


# --- BU#19, #26 -----------------------------------------------------------------------------------


def test_budget_remaining_without_budget_is_refused() -> None:
    # BU-12
    with pytest.raises(ValueError, match=r"needs sf\.Budgeted\(\.\.\.\) on the candidate"):
        _url4(_choice())


def test_budget_remaining_needs_a_unit_with_two_units() -> None:
    # BU-13: with both units the unit is named; with one it is optional.
    with pytest.raises(ValueError, match=r"name the unit: sf\.budget\.remaining\('usd'\)"):
        _url4(sf.Budgeted(_choice(), usd=1, tokens=10))
    named = _choice(sf.budget.remaining("usd") >= 0.02)
    assert "budget.remaining:usd" in _url4(sf.Budgeted(named, usd=1, tokens=10))
    assert "budget.remaining:usd" in _url4(sf.Budgeted(_choice(), usd=1))


@pytest.mark.parametrize("bad", ["eur", "USD", 1])
def test_budget_remaining_takes_only_a_declared_unit_word(bad: object) -> None:
    with pytest.raises(ValueError, match="takes 'usd' or 'tokens'"):
        sf.budget.remaining(bad)  # type: ignore[arg-type]


# --- BU#20 ----------------------------------------------------------------------------------------


_INVALID: dict[str, tuple[Callable[[], object], str]] = {
    "zero cap": (lambda: sf.Budgeted("prov/a", usd=0), "greater than zero"),
    "negative cap": (lambda: sf.Budgeted("prov/a", usd=-1), "finite"),
    "nan cap": (lambda: sf.Budgeted("prov/a", usd=math.nan), "finite"),
    "infinite cap": (
        lambda: sf.Budgeted("prov/a", tokens=math.inf),  # type: ignore[arg-type]
        "finite",
    ),
    "fractional tokens cap": (
        lambda: sf.Budgeted("prov/a", tokens=1.5),  # type: ignore[arg-type]
        "whole number",
    ),
    "no cap": (lambda: sf.Budgeted("prov/a"), "needs a cap: usd=, tokens= or both"),
    "bool cap": (lambda: sf.Budgeted("prov/a", usd=True), "is a number"),
    "no estimate": (lambda: sf.Estimate("prov/a"), "needs usd=, tokens= or both"),
    "negative estimate": (lambda: sf.Estimate("prov/a", usd=-0.01), "finite and not negative"),
    "nan estimate": (lambda: sf.Estimate("prov/a", usd=math.nan), "finite and not negative"),
    "fractional tokens estimate": (
        lambda: sf.Estimate("prov/a", tokens=2.5),  # type: ignore[arg-type]
        "whole number",
    ),
    "estimate on a word": (
        lambda: sf.Estimate("abstain", usd=0.01),
        "sf.Estimate wraps a branch that makes model calls",
    ),
    "estimate on a step": (
        lambda: (
            sf.Fanout(["prov/a", "prov/b"])
            >> sf.Gate(
                when=sf.agreement() >= 0.5,
                then=sf.Estimate(sf.Vote(), usd=0.01),
                otherwise="prov/c",
            )
        ),
        "sf.Estimate wraps a branch that makes model calls",
    ),
    "estimate in an undeclared unit": (
        lambda: _url4(sf.Budgeted(_choice(sf.budget.remaining() >= 1), tokens=10)),
        "sf.Estimate names usd, but sf.Budgeted declares only tokens",
    ),
}


@pytest.mark.parametrize(("build", "message"), list(_INVALID.values()), ids=list(_INVALID))
def test_invalid_caps_and_estimates_are_refused(build: Callable[[], object], message: str) -> None:
    # BU-14, BU-24
    with pytest.raises((TypeError, ValueError), match=message):
        build()


# --- the public names -----------------------------------------------------------------------------


def test_budget_names_are_public() -> None:
    assert sf.Budgeted.__module__ == "screamingface._surface.budget"
    assert callable(sf.budget.remaining)
    assert sf.budget.BUDGET_SCHEMA == "screamingface.budget.v1"
    assert {"Budgeted", "Estimate", "budget"} <= set(sf.__all__)
    assert "Budget" not in sf.__all__  # the E4a record stays sf.budget.Budget
