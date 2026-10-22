"""Skip-Gate Fanout members on the SDK: the member form, its refusals and its compiled shape.

FEATURE: E4c (OME-1291) skip-members rows SM#2, #5, #5a, #5b, #15, #19, #21, #23, #24.
STORY: as a researcher, a Fanout member may be a Gate with no otherwise= (it runs only when its
selector picked its label); every other Gate member, a model call over the whole panel and a
sf.Consistency source are refused before any spend; the url4 rebuilds to the same bytes.
"""

from __future__ import annotations

import re

import pytest
from _reducer_fixtures import engine_operators
from test_e4c_gate_fixtures import BUILDERS
from url4 import Expression, RelExpr, Source, build, walk

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.combine_evidence import CombineAnswerRow, CombineEvidence, CombineResult

SEL = sf.Keywords([("math", "integral"), ("code", "python")], multi=True)
_MEMBER_RULE = r"a sf\.Fanout member may be a sf\.Gate only without otherwise= and with a recipe"


def _skip(label: str = "math", then: object = "prov/m") -> sf.Gate:
    return sf.Gate(when=sf.labels(SEL).has(label), then=then)  # type: ignore[arg-type]


def _url4(recipe: object) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4  # type: ignore[arg-type]


def _sources(url4: str) -> dict[str, Source]:
    return {node.name: node for node in walk(build(url4)) if isinstance(node, Source) and node.name}


# --- the member form (SM#2, #5, #23, #24; GU#26 is in test_e4c_guards.py) ----------------------


def test_a_gate_with_otherwise_is_refused_as_a_fanout_member_naming_its_position() -> None:
    # SM#2 (the E4b CHAR "a Gate is refused as a member" now holds for a Gate with otherwise=).
    with pytest.raises(ValueError, match=rf"^sf\.Fanout member 2: {_MEMBER_RULE}"):
        sf.Fanout(["prov/a", sf.Gate(when=sf.labels(SEL).has("math"), then="m", otherwise="b")])


def test_skip_gate_member_is_accepted() -> None:
    fanout = sf.Fanout([_skip("math"), _skip("code", "prov/c")])
    assert len(fanout.members) == 2


@pytest.mark.parametrize(
    "member",
    [
        lambda: sf.Gate(when=sf.labels(SEL).has("math"), then="prov/m", otherwise="abstain"),
        lambda: sf.Gate(when=sf.labels(SEL).has("math"), then="abstain"),
        lambda: sf.Gate(when=sf.label(sf.Keywords([("x", "x")])) == "x", then="fail_closed"),
    ],
    ids=["otherwise", "word_then", "fail_closed_then"],
)
def test_other_gate_members_are_refused(member) -> None:
    # SM#5 / SM-8
    with pytest.raises(ValueError, match=_MEMBER_RULE):
        sf.Fanout(["prov/a", member()])


def test_a_panel_gate_or_a_step_then_cannot_be_a_member() -> None:
    # SM-8: a panel ref Gate is a step, not a recipe; a step in then= needs a panel.
    with pytest.raises((TypeError, ValueError)):
        sf.Fanout(["prov/a", sf.Gate(when=sf.agreement() >= 0.5, then=sf.Vote())])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="a step in then= needs a panel"):
        sf.Gate(when=sf.labels(SEL).has("math"), then=sf.Vote())


def test_skip_gate_then_holds_a_gate_under_the_depth_cap() -> None:
    # SM#23 / SM-20
    inner = sf.Gate(
        when=sf.label(sf.Keywords([("x", "x")])) == "x", then="prov/x", otherwise="prov/y"
    )
    url4 = _url4(sf.Fanout([_skip("math", inner), _skip("code", "prov/c")]) >> sf.Vote())
    assert "gate_3" in _sources(url4)


def test_fanout_over_256_members_is_refused_first() -> None:
    # SM#24 / SM-22: the existing member cap refuses the block before the skip rules.
    members = [f"prov/m{index}" for index in range(256)] + [_skip()]
    with pytest.raises(ValueError, match="256"):
        _ = sf.Fanout(members) >> sf.Vote()


# --- model signal calls and Consistency (SM#5a, #5b) --------------------------------------------


@pytest.mark.parametrize(
    "close",
    [
        lambda fanout: fanout >> sf.Judge("prov/j", rubric="r") >> sf.Vote(weights="score:judge"),
        lambda fanout: fanout >> sf.JudgePick("prov/j", rubric="r"),
        lambda fanout: (
            fanout
            >> sf.Gate(
                when=sf.agreement() >= 0.5,
                then=sf.Vote(),
                otherwise=sf.JudgePick("prov/j", rubric="r"),
            )
        ),
    ],
    ids=["block_judge", "judge_pick", "gate_judge_fallback"],
)
def test_model_signal_calls_are_refused_with_skip_gate_members(close) -> None:
    with pytest.raises(ValueError, match="not supported with skip-Gate members"):
        close(sf.Fanout([_skip("math"), _skip("code", "prov/c")]))


def test_consistency_is_refused_with_skip_gate_members() -> None:
    signals = {"agree": sf.Consistency(n=3)}
    with pytest.raises(ValueError, match=r"sf\.Consistency is not supported with skip-Gate"):
        _ = sf.Fanout([_skip("math"), _skip("code", "prov/c")], signals=signals) >> sf.Vote()


# --- the compiled shape (SM#15, #19) ------------------------------------------------------------


def test_keywords_multi_selects_without_a_call() -> None:
    # SM#15 / SM-5: one KEYWORDS source, no selector_N call.
    names = set(_sources(_url4(sf.Fanout([_skip("math"), _skip("code", "prov/c")]) >> sf.Vote())))
    assert "keywords_1" in names
    assert not any(re.fullmatch(r"selector_\d+", name) for name in names)


def test_mixed_plain_and_skip_members_floor_compiles() -> None:
    # SM#19 / SM-18: plain slots stay required, a skip slot is optional under a numeric quorum,
    # the panel takes quorum 0 and the combine context carries the floor.
    url4 = BUILDERS["skip_mixed.url4"]()
    sources = _sources(url4)
    slots = {name: source for name, source in sources.items() if name.startswith("member_")}
    optional = {
        name
        for name, source in slots.items()
        if any(key == "optional" for key, _ in source.annotations)
    }
    assert optional == {"member_3"}
    panel = sources["panel_1"].value
    assert isinstance(panel, Expression)
    assert dict(panel.params)["quorum"] == "0"
    combine = sources["synthesis_1"].value
    assert isinstance(combine, RelExpr)
    assert "floor: 2" in (combine.context or "")
    assert "selection: {member_3: '$gate_1_decide'}" in (combine.context or "")


@pytest.mark.parametrize("name", [name for name in sorted(BUILDERS) if name.startswith("skip_")])
def test_skip_fixtures_round_trip_through_to_python(name: str) -> None:
    url4 = BUILDERS[name]()
    namespace: dict[str, object] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own rebuilt code
    assert _url4(namespace["candidate"]) == url4


# --- the evidence decode (SM#21) ----------------------------------------------------------------


def _skipped_evidence() -> CombineEvidence:
    return CombineEvidence(
        kind="answer",
        reducer="vote",
        operators=["last_line@1", "text@1", "mode@1", "first_holder@1"],
        members=[
            CombineAnswerRow(
                member_id="member_1", raw="A", value="a", status="answered", reason=None, signals={}
            ),
            CombineAnswerRow(
                member_id="member_2",
                raw=None,
                value=None,
                status="excluded",
                reason="not_selected",
                signals={},
            ),
        ],
        chosen=["member_1"],
        built=False,
        tie=False,
        result=CombineResult(member_id="member_1", value="a", status="answered", reason=None),
        dropped=0,
        finish_reason="stop",
        agreement=1.0,
        skipped=["member_2"],
    )


def test_sdk_decodes_skipped_and_writes_it_back() -> None:
    evidence = _skipped_evidence()
    wire = evidence.to_dict()
    assert list(wire)[-1] == "skipped"
    assert wire["skipped"] == ["member_2"]
    decoded = decode_combine_evidence(wire, "Case Operation combine")
    assert decoded is not None
    assert decoded.to_dict() == wire


def test_sdk_refuses_not_selected_without_skipped() -> None:
    wire = _skipped_evidence().to_dict()
    del wire["skipped"]
    with pytest.raises(Exception, match="not_selected goes with a narrow record"):
        decode_combine_evidence(wire, "Case Operation combine")
