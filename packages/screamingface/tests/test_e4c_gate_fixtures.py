"""Drift guard for the SDK-compiled sf.Gate url4 fixtures the Engine runs offline (E4c, C9).

FEATURE: OME-1291 plan unit 5 — the Engine world runs ``gate_contract/*.url4`` verbatim on a fake
gateway (``apps/screamingface-engine/tests/unit/test_e4c_gate_runs.py``). This file keeps each
fixture byte-identical to what the SDK compiles today. ``BUILDERS`` maps each file to its builder.
STORY: as a maintainer, a change to the compiled Gate shape fails here, not in a silent Engine run.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_e4c_gate_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface.branch import BranchCondition, BranchNode
from screamingface.fusion import FusionNode

GATE_CONTRACT = ENGINE_APP / "tests" / "unit" / "data" / "gate_contract"

TOPIC = sf.RegexClassifier([("math", r"(?i)\bintegral\b"), ("code", r"(?i)\bpython\b")])
JAIL = sf.RegexClassifier([("jailbreak", r"(?i)ignore (all|any|previous) instructions")])
CLF = sf.LLMClassifier("prov/clf", labels=["safe", "unsafe", "medical"])


def _label_gate(selector, label: str, then, otherwise, cmp: str = "eq") -> BranchNode:
    return BranchNode(
        condition=BranchCondition("label", cmp, label, selector), then=then, otherwise=otherwise
    )


def keyword_router() -> BranchNode:
    """A 3-way router: math, else code, else general (nested binary Gates, ans:Q12)."""
    code = _label_gate(TOPIC, "code", sf.Model("prov/coder"), sf.Model("prov/general"))
    return _label_gate(TOPIC, "math", sf.Model("prov/math"), code)


def guard_tree() -> BranchNode:
    """A regex guard, a classifier guard and a classifier floor before the router (guards §1)."""
    floor = _label_gate(CLF, "medical", sf.Model("prov/med"), keyword_router())
    unsafe = _label_gate(CLF, "unsafe", "fail_closed", floor)
    return _label_gate(JAIL, "jailbreak", "fail_closed", unsafe)


def word_abstain() -> BranchNode:
    """The word abstain at the root: a code question declines, anything else is answered."""
    return _label_gate(TOPIC, "code", "abstain", sf.Model("prov/general"))


def stage_gate():
    """A Gate as a later Pipeline stage: its branches answer the previous stage's answer."""
    return sf.Model("prov/prep") >> keyword_router() >> "prov/after"


def outer_body_holds_a_gate() -> BranchNode:
    """BC-24: the outer otherwise body is a model call, then an inner Gate (a later stage)."""
    inner = _label_gate(TOPIC, "code", sf.Model("prov/coder"), sf.Model("prov/general"))
    body = sf.Model("prov/prep") >> inner
    return _label_gate(TOPIC, "math", sf.Model("prov/math"), body)


def sibling_gates() -> FusionNode:
    """BC-20: two Gates side by side in one Case, joined by a writer."""
    first = _label_gate(TOPIC, "math", sf.Model("prov/math"), sf.Model("prov/general"))
    second = _label_gate(TOPIC, "code", sf.Model("prov/coder"), sf.Model("prov/general2"))
    return FusionNode(members=[first, second], synthesizer=sf.Model("prov/writer"))


_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
_CONF = {"conf": sf.Verbalized("Confidence: ([0-9]+)")}


def lazy_judge() -> object:
    """Lazy fallback (LF-1, LF-2): the label judge runs only when the agreement is below 0.7."""
    return sf.Fanout(_MEMBERS, name="vote") >> sf.Gate(
        when=sf.agreement() >= 0.7,
        then=sf.Vote(),
        otherwise=sf.JudgePick("prov/judge", rubric="Pick the best answer."),
    )


def lazy_writer() -> object:
    """Lazy fallback (LF-3): the writer runs only when the mean confidence is below 70."""
    return sf.Fanout(_MEMBERS, signals=_CONF, name="vote") >> sf.Gate(
        when=sf.signal("conf").mean() >= 70,
        then=sf.Vote(),
        otherwise=sf.Synthesize("prov/writer"),
        abstain_if=sf.signal("conf").mean().between(40, 60),
    )


def panel_escalates() -> object:
    """A panel gate with a recipe otherwise (GT-2): a large model answers when the panel splits."""
    return sf.Fanout(_MEMBERS, name="vote") >> sf.Gate(
        when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise="prov/large"
    )


_S1 = sf.Fanout(["prov/a", "prov/b"]) >> sf.Vote()
_S2 = sf.Fanout(["prov/c", "prov/d"]) >> sf.Vote()
_LOW = sf.escalate_if(sf.agreement() < 0.8)
_UNANSWERED = sf.escalate_if(sf.unanswered())


def cascade_three() -> object:
    """CA-2 - CA-7, CA-29: two gated tiers, then a large model answers unconditionally.

    The tiers keep the author's Fanout (2026-11-12): a tier that fails fails the Case and a tier
    that abstains makes the Case abstain; only a split vote escalates.
    """
    return sf.Cascade(_S1, _LOW, _S2, _LOW, "prov/large")


def cascade_abstain() -> object:
    """CA-9, CA-20, CA-30, BC-36: the human last tier: every tier gated, then sf.abstain()."""
    return sf.Cascade(_S1, _LOW, _S2, _LOW, sf.abstain())


def cascade_fail_closed() -> object:
    """CA-30: a gated last tier whose line holds follows sf.fail()."""
    return sf.Cascade(_S1, _LOW, _S2, _LOW, sf.fail())


def first_success() -> object:
    """CA-10 (OME-1465 sequential): each tier escalates only when it fails or abstains."""
    return sf.Cascade("prov/a", _UNANSWERED, "prov/b", _UNANSWERED, "prov/c")


def adaptive_sampling() -> object:
    """CA-11 (ans:Q7): two samples; five fresh ones only when the two disagree."""
    return sf.Cascade(
        sf.Fanout(sf.samples("prov/m", 2)) >> sf.Vote(),
        sf.escalate_if(sf.agreement() < 1.0),
        sf.Fanout(sf.samples("prov/m", 5, seeds=range(2, 7))) >> sf.Vote(),
    )


def cascade_then_writer() -> object:
    """CA-26: a cascade as a Pipeline stage; the writer reads its final answer."""
    return sf.Cascade(_S1, _LOW, "prov/large") >> "prov/writer"


def cascade_signal() -> object:
    """2026-11-12: a line on the chosen member's number; a missing number is signal_missing."""
    tier = (
        sf.Fanout(["prov/a", "prov/b"], signals={"conf": sf.Verbalized("Confidence: ([0-9]+)")})
        >> sf.Vote()
    )
    return sf.Cascade(tier, sf.escalate_if(sf.signal("conf").chosen() < 70), "prov/large")


def signal_fail() -> object:
    """2026-11-12 boundary: a Gate with otherwise=sf.fail() keeps the E4b missing-number rule."""
    conf = {"conf": sf.Verbalized("Confidence: ([0-9]+)")}
    return sf.Fanout(["prov/a", "prov/b"], signals=conf) >> sf.Gate(
        when=sf.signal("conf").chosen() >= 70, then=sf.Vote(), otherwise=sf.fail()
    )


def vote_body_gate() -> object:
    """BC-37: an input Gate whose then body ends in a vote that may abstain."""
    return sf.Gate(
        when=sf.label(TOPIC) == "math",
        then=sf.Fanout(["prov/a", "prov/b"]) >> sf.Vote(),
        otherwise="prov/general",
    )


def _url4(build: Callable[[], object]) -> Callable[[], str]:
    return lambda: compile_candidate(build(), operators=engine_operators()).url4  # type: ignore[arg-type]


BUILDERS: dict[str, Callable[[], str]] = {
    "keyword_router.url4": _url4(keyword_router),
    "guard_tree.url4": _url4(guard_tree),
    "word_abstain.url4": _url4(word_abstain),
    "stage_gate.url4": _url4(stage_gate),
    "outer_body_holds_a_gate.url4": _url4(outer_body_holds_a_gate),
    "sibling_gates.url4": _url4(sibling_gates),
    "lazy_judge.url4": _url4(lazy_judge),
    "lazy_writer.url4": _url4(lazy_writer),
    "panel_escalates.url4": _url4(panel_escalates),
    "cascade_three.url4": _url4(cascade_three),
    "cascade_abstain.url4": _url4(cascade_abstain),
    "cascade_fail_closed.url4": _url4(cascade_fail_closed),
    "first_success.url4": _url4(first_success),
    "adaptive_sampling.url4": _url4(adaptive_sampling),
    "cascade_then_writer.url4": _url4(cascade_then_writer),
    "cascade_signal.url4": _url4(cascade_signal),
    "signal_fail.url4": _url4(signal_fail),
    "vote_body_gate.url4": _url4(vote_body_gate),
}


def ne_guard() -> object:
    """GU-10, GU-21: a guard written with != fires on any label but safe, and on no label."""
    return sf.Gate(when=sf.label(CLF) != "safe", then=sf.fail(), otherwise="prov/ans")


def panel_fail_closed() -> object:
    """GU-18: a panel gate whose otherwise is fail_closed fails after the panel ran."""
    return sf.Fanout(_MEMBERS) >> sf.Gate(
        when=sf.agreement() >= 0.5, then=sf.Vote(), otherwise=sf.fail()
    )


def stage_guard() -> object:
    """GU-19: a guard as a later stage still reads the Case input, not the previous answer."""
    return sf.Model("prov/prep") >> sf.Gate(
        when=sf.label(JAIL) == "jailbreak", then=sf.fail(), otherwise="prov/ans"
    )


# E4c unit 10 (guards): appended builders.
BUILDERS |= {
    "ne_guard.url4": _url4(ne_guard),
    "panel_fail_closed.url4": _url4(panel_fail_closed),
    "stage_guard.url4": _url4(stage_guard),
}


SKILLS = sf.LLMClassifier("prov/sel", labels=["math", "code", "web"], multi=True)
TOPICS = sf.RegexClassifier(
    [("math", r"(?i)\bintegral\b"), ("code", r"(?i)\bpython\b")], multi=True
)
_SKIP_CONF = {"conf": sf.Verbalized("Confidence: ([0-9]+)")}


def _skip(selector: object, label: str, route: str) -> sf.Gate:
    return sf.Gate(when=sf.labels(selector).has(label), then=route)  # type: ignore[arg-type]


def _three_skip_members() -> list[sf.Gate]:
    return [
        _skip(SKILLS, "math", "prov/math"),
        _skip(SKILLS, "code", "prov/code"),
        _skip(SKILLS, "web", "prov/web"),
    ]


def skip_vote() -> object:
    """SM-1 - SM-3, SM-6, SM-10: three skip-Gate members over one multi LLMClassifier; a vote."""
    return sf.Fanout(_three_skip_members()) >> sf.Vote()


def skip_vote_quorum() -> object:
    """SM-7, SM-11: the same block with quorum=1 (optional slots, panel quorum 0, a floor)."""
    return sf.Fanout(_three_skip_members(), quorum=1) >> sf.Vote()


def skip_writer() -> object:
    """SM-4, SM-5, SM-23: a RegexClassifier multi selector, two skip members, a writer."""
    return sf.Fanout(
        [_skip(TOPICS, "math", "prov/math"), _skip(TOPICS, "code", "prov/code")]
    ) >> sf.Synthesize("prov/writer")


def skip_mixed() -> object:
    """SM-18: two plain members and one skip member, quorum=2."""
    return (
        sf.Fanout(["prov/plain_a", "prov/plain_b", _skip(SKILLS, "web", "prov/web")], quorum=2)
        >> sf.Vote()
    )


def skip_rank() -> object:
    """SM-14, SM-17: Rank after skip members ranks only the selected members."""
    return (
        sf.Fanout(_three_skip_members(), signals=_SKIP_CONF)
        >> sf.Rank(k=1, by="conf")
        >> sf.Synthesize("prov/writer")
    )


# E4c unit 11 (skip members): appended builders.
BUILDERS |= {
    "skip_vote.url4": _url4(skip_vote),
    "skip_vote_quorum.url4": _url4(skip_vote_quorum),
    "skip_writer.url4": _url4(skip_writer),
    "skip_mixed.url4": _url4(skip_mixed),
    "skip_rank.url4": _url4(skip_rank),
}


def write_fixture(name: str) -> None:
    GATE_CONTRACT.mkdir(parents=True, exist_ok=True)
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (GATE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_gate_url4_fixtures_match_the_sdk_compile(name: str) -> None:
    fixture = GATE_CONTRACT / name
    assert fixture.exists(), f"gate_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()
