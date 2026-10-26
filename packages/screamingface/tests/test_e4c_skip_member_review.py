"""Skip-Gate Fanout members after the E4c code review (OME-1291).

FEATURE: OME-1291 skip-members SM-11, SM-17 and SM-8; budget BU-14; gate GT-12.
STORY: as a researcher, a skip-Gate member behaves the same wherever its Fanout sits: a panel
Gate's second reducer step leaves the members that were not selected out of the vote and checks
the quorum floor, a member's sf.Estimate reaches DECIDE, a member Gate that cannot select is
refused with a message, each member lists only its own selector model, and a mistyped branch word
is refused instead of becoming a model route.
"""

from __future__ import annotations

import re

import pytest
from _reducer_fixtures import engine_operators
from test_e4c_gate_replay import _replayed

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

SEL = sf.Keywords([("math", "integral"), ("code", "python")], multi=True)
_CONTEXT = re.compile(r"binding=(synthesis_\d+)&q=\((\{.*?\})\)!'")


def _skip(label: str, then: object) -> sf.Gate:
    return sf.Gate(when=sf.labels(SEL).has(label), then=then)  # type: ignore[arg-type]


def _combine_contexts(url4: str) -> dict[str, str]:
    return dict(_CONTEXT.findall(url4))


# --- a panel Gate's second reducer step over skip-Gate members (SM-11) ----------------------------


@pytest.mark.parametrize(("quorum", "floor"), [(1, "floor: 1"), ("all", None)])
def test_a_panel_gate_second_step_reads_the_member_selection(quorum: object, floor: str | None):
    recipe = sf.Fanout([_skip("math", "prov/a"), "prov/b", "prov/c"], quorum=quorum) >> sf.Gate(  # type: ignore[arg-type]
        when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise=sf.Median()
    )

    contexts = _combine_contexts(compile_candidate(recipe, operators=engine_operators()).url4)

    assert sorted(contexts) == ["synthesis_1", "synthesis_2"]
    for context in contexts.values():
        assert "panel: '$panel_1'" in context
        assert re.search(r"selection: \{member_1: '\$gate_\d+_decide'\}", context)
        assert (floor in context) if floor else ("floor" not in context)


# --- a skip member's sf.Estimate (SM-17, BU-14) ---------------------------------------------------


def test_a_skip_member_estimate_reaches_its_decide_spec() -> None:
    member = sf.Gate(when=sf.labels(SEL).has("math"), then=sf.Estimate("prov/big", usd=0.05))
    recipe = sf.Budget(sf.Fanout([member, "prov/small"]) >> sf.Vote(), usd=0.1)

    url4 = compile_candidate(recipe, operators=engine_operators()).url4

    assert '"estimate":{"otherwise":null,"then":{"usd":0.05}}' in url4


# --- a member Gate that cannot select (SM-8) ------------------------------------------------------


def test_a_budget_condition_skip_member_is_refused_with_a_message() -> None:
    member = sf.Gate(when=sf.budget.remaining() >= 0.01, then="prov/big")

    with pytest.raises(
        ValueError, match=r"^sf\.Fanout member 1: a skip-Gate member reads sf\.label"
    ):
        sf.Fanout([member, "prov/small"])


# --- each member lists only its own selector model ------------------------------------------------


def test_each_skip_member_lists_only_the_selector_models_it_reads() -> None:
    first = sf.LabelModel("prov/cheap", labels=["math", "other"])
    second = sf.LabelModel("prov/cheap2", labels=["code", "other"])
    recipe = (
        sf.Fanout(
            [
                sf.Gate(when=sf.label(first) == "math", then="prov/a"),
                sf.Gate(when=sf.label(second) == "code", then="prov/b"),
                "prov/c",
            ]
        )
        >> sf.Vote()
    )

    compiled = compile_candidate(recipe, operators=engine_operators())

    assert [member.models for member in compiled.members] == [
        ("prov/a", "prov/cheap"),
        ("prov/b", "prov/cheap2"),
        ("prov/c",),
    ]
    assert compiled.url4.count('"role":"selector"') == 2
    replayed = _replayed(compiled.url4)
    assert replayed.models == compiled.models
    assert replayed.members == compiled.members


def test_a_selector_shared_by_two_members_is_listed_once() -> None:
    shared = sf.LabelModel("prov/cheap", labels=["math", "code"])
    recipe = (
        sf.Fanout(
            [
                sf.Gate(when=sf.label(shared) == "math", then="prov/a"),
                sf.Gate(when=sf.label(shared) == "code", then="prov/b"),
            ]
        )
        >> sf.Vote()
    )

    compiled = compile_candidate(recipe, operators=engine_operators())

    assert compiled.url4.count('"role":"selector"') == 1
    assert [member.models for member in compiled.members] == [("prov/a", "prov/cheap"), ("prov/b",)]
    assert _replayed(compiled.url4).members == compiled.members


# --- a mistyped branch word (GT-12) ---------------------------------------------------------------


@pytest.mark.parametrize("word", ["fail-closed", "Fail_Closed", "failclosed", "ABSTAIN", "Skip"])
@pytest.mark.parametrize("branch", ["then", "otherwise"])
def test_a_mistyped_branch_word_is_refused(word: str, branch: str) -> None:
    kwargs = {"then": "prov/a", branch: word}

    with pytest.raises(TypeError, match=rf"^sf\.Gate {branch}= takes a step, a recipe"):
        sf.Gate(when=sf.labels(SEL).has("math"), **kwargs)  # type: ignore[arg-type]


def test_a_route_that_only_contains_a_word_stays_a_route() -> None:
    gate = sf.Gate(when=sf.labels(SEL).has("math"), then="prov/abstain-v2")

    assert gate.then == sf.Model("prov/abstain-v2")
