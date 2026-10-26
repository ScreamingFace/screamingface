"""Drift guard for the SDK-compiled sf.Budgeted url4 fixtures the Engine runs offline (E4c, C9).

FEATURE: OME-1291 plan unit 13 — the Engine world runs ``gate_contract/budget_*.url4`` verbatim on
a fake gateway (``apps/screamingface-engine/tests/unit/test_e4c_budget_runs.py``). This file keeps
each fixture byte-identical to what the SDK compiles today.
STORY: as a maintainer, a change to the compiled budget shape fails here, not in a silent Engine
run.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_e4c_budget_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

GATE_CONTRACT = ENGINE_APP / "tests" / "unit" / "data" / "gate_contract"
_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]


def budget_choice() -> object:
    """BU-6 (OmniRouter): the large model only when 0.02 USD is left; its estimate is 0.03."""
    return sf.Budgeted(
        sf.Gate(
            when=sf.budget.remaining() >= 0.02,
            then=sf.Estimate("prov/big", usd=0.03),
            otherwise="prov/small",
        ),
        usd=0.05,
    )


def budget_refuse_both() -> object:
    """BU-5: a prep stage spends; the wanted branch is refused and the other branch also calls."""
    gate = sf.Gate(
        when=sf.budget.remaining() >= 0.0,
        then=sf.Estimate("prov/big", usd=0.03),
        otherwise="prov/small",
    )
    return sf.Budgeted(sf.Model("prov/prep") >> gate, usd=0.0015)


def budget_cascade() -> object:
    """BU-7, BU-22: a two-stage cascade whose escalation carries an estimate."""
    stage_two = sf.Fanout(
        [sf.Model("prov/c", optional=True), sf.Model("prov/d", optional=True)], quorum=0
    ) >> sf.Gate(when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large")
    stage_one = sf.Fanout(
        [sf.Model("prov/a", optional=True), sf.Model("prov/b", optional=True)], quorum=0
    ) >> sf.Gate(
        when=sf.agreement() >= 0.8,
        then=sf.Vote(),
        otherwise=sf.Estimate(stage_two, usd=0.0025),
    )
    return sf.Budgeted(stage_one, usd=0.01)


def budget_lazy_judge() -> object:
    """BU-18: the E4b judge fallback is an optional call; refused, the majority answers."""
    return sf.Budgeted(
        sf.Fanout(_MEMBERS, name="vote")
        >> sf.Gate(
            when=sf.agreement() >= 0.7,
            then=sf.Vote(),
            otherwise=sf.Estimate(sf.JudgePick("prov/judge", rubric="Pick the best."), usd=0.01),
        ),
        usd=0.005,
    )


def budget_tokens() -> object:
    """BU-2: a tokens-only cap."""
    return sf.Budgeted(
        sf.Gate(
            when=sf.budget.remaining() >= 1,
            then=sf.Estimate("prov/big", tokens=100),
            otherwise="prov/small",
        ),
        tokens=50,
    )


def budget_two_units() -> object:
    """BU-2: both units; a branch is refused when either unit refuses it."""
    return sf.Budgeted(
        sf.Model("prov/prep")
        >> sf.Gate(
            when=sf.budget.remaining("usd") >= 0.0,
            then=sf.Estimate("prov/big", usd=0.001, tokens=100),
            otherwise="abstain",
        ),
        usd=0.05,
        tokens=50,
    )


def budget_skip_members() -> object:
    """BU-19: three selected skip members each check only their own ancestors."""
    sel = sf.Keywords([("a", "a"), ("b", "b"), ("c", "c")], multi=True)
    return sf.Budgeted(
        sf.Fanout(
            [
                sf.Gate(when=sf.labels(sel).has("a"), then=sf.Estimate("prov/a", usd=0.001)),
                sf.Gate(when=sf.labels(sel).has("b"), then=sf.Estimate("prov/b", usd=0.001)),
                sf.Gate(when=sf.labels(sel).has("c"), then=sf.Estimate("prov/c", usd=0.001)),
            ]
        )
        >> sf.Vote(),
        usd=0.0015,
    )


def budget_cascade_tight() -> object:
    """BU-10: the mandatory stage spends more than the cap; it still runs, and the escalation is
    refused."""
    stage_one = sf.Fanout(
        [sf.Model("prov/a", optional=True), sf.Model("prov/b", optional=True)], quorum=0
    ) >> sf.Gate(when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large")
    return sf.Budgeted(stage_one, usd=0.001)


def _url4(build: Callable[[], object]) -> Callable[[], str]:
    return lambda: compile_candidate(build(), operators=engine_operators()).url4  # type: ignore[arg-type]


BUILDERS: dict[str, Callable[[], str]] = {
    "budget_choice.url4": _url4(budget_choice),
    "budget_refuse_both.url4": _url4(budget_refuse_both),
    "budget_cascade.url4": _url4(budget_cascade),
    "budget_lazy_judge.url4": _url4(budget_lazy_judge),
    "budget_tokens.url4": _url4(budget_tokens),
    "budget_two_units.url4": _url4(budget_two_units),
    "budget_skip_members.url4": _url4(budget_skip_members),
    "budget_cascade_tight.url4": _url4(budget_cascade_tight),
}


def write_fixture(name: str) -> None:
    GATE_CONTRACT.mkdir(parents=True, exist_ok=True)
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (GATE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_budget_url4_fixtures_match_the_sdk_compile(name: str) -> None:
    fixture = GATE_CONTRACT / name
    assert fixture.exists(), f"gate_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_budget_fixture_url4_round_trips_through_to_python(name: str) -> None:
    url4 = BUILDERS[name]()
    namespace: dict[str, object] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - the SDK's own generated code
    rebuilt = compile_candidate(namespace["candidate"], operators=engine_operators())  # type: ignore[arg-type]
    assert rebuilt.url4 == url4
