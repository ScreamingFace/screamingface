"""The public sf.Gate: one branch construct, an input form that is a recipe, a panel form that
closes a block, words, the rebuild and the refusals.

FEATURE: E4c (OME-1291) gate PRD rows GT#4, #5, #6, #9, #10, #11, #12, #15, #16, #22, #23, #24,
#25, #27, #30, #31, #32; guards GU#19 and the "skip" refusal (GT-12).
STORY: as a researcher, I write ``sf.Gate(when=..., then=..., otherwise=...)`` as a router, a
cascade step or a guard; the branch not taken makes no call, the url4 rebuilds to the same Gate,
and a wrong Gate is refused before any run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from _reducer_fixtures import engine_operators
from url4 import Expression, Iteration, Node, RelExpr, Source, Text, build, walk

import screamingface as sf
import screamingface._surface.gate as gate_module
import screamingface._surface.selectors as selectors_module
from screamingface import url4 as sdk_url4
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.lowering import lower
from screamingface._surface.render import code
from screamingface.branch import BranchNode, DecisionReducer
from screamingface.recipe import _is_supported_recipe, _recipe_kind
from screamingface.reducer import VoteNode

_KW = sf.RegexClassifier([("math", r"(?i)\bintegral\b"), ("code", r"python")])
_PANEL = ["prov/a", "prov/b", "prov/c"]
_LOOP_REFUSAL = (
    "a sf.Gate cannot sit inside a sf.CorrectiveLoop, and a sf.CorrectiveLoop cannot be a "
    "sf.Gate branch"
)


def _input_gate(label: str = "math", then: object = "prov/math", otherwise: object = "prov/g"):
    return sf.Gate(when=sf.label(_KW) == label, then=then, otherwise=otherwise)  # type: ignore[arg-type]


def _three_way() -> sf.Gate:
    return _input_gate(otherwise=_input_gate("code", "prov/coder", "prov/general"))


def _compiled(recipe: object) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4  # type: ignore[arg-type]


def _deep(node: Node):
    for child in walk(node):
        yield child
        if isinstance(child, Iteration) and child.intent:
            yield from _deep(build(f"({child.body})!{child.intent}"))


def _sources(url4: str) -> dict[str, Source]:
    return {
        node.name: node
        for node in _deep(build(url4))
        if isinstance(node, Source) and node.name is not None
    }


# --- the two forms (GT#4, #5, #6) ---------------------------------------------------------------


def test_panel_gate_otherwise_takes_a_recipe() -> None:
    recipe = sf.Fanout(_PANEL) >> sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large"
    )
    compiled = compile_candidate(recipe, operators=engine_operators())
    assert compiled.kind == "gate"
    otherwise = _sources(compiled.url4)["gate_1_else"]
    assert isinstance(otherwise.value, Iteration)
    body = build(f"({otherwise.value.body})!{otherwise.value.intent}")
    assert isinstance(body, Expression)
    calls = [node.value for node in body.sources if isinstance(node, Source)]
    model = next(call for call in calls if isinstance(call, RelExpr))
    assert model.path == "/prov/large"
    assert model.params[0] == ("binding", "model_4")


def test_input_gate_is_a_recipe_at_the_root() -> None:
    gate = _input_gate()
    assert _recipe_kind(gate) == "gate"
    assert _is_supported_recipe(gate)
    panel = sf.Gate(when=sf.agreement() >= 0.8, then=sf.Vote())
    assert not _is_supported_recipe(panel)


def test_gate_compiles_to_decide_open_join() -> None:
    url4 = _compiled(_input_gate())
    root = build(url4)
    assert isinstance(root, Expression)
    assert isinstance(root.intent, Text) and root.intent.value == "$gate_1_block"
    block = next(
        node for node in root.sources if isinstance(node, Source) and node.name == "gate_1_block"
    )
    assert isinstance(block.value, Expression)
    names = [node.name for node in block.value.sources if isinstance(node, Source)]
    assert names == [
        "gate_1_after",
        "gate_1_decide",
        "gate_1_open_then",
        "gate_1_then",
        "gate_1_open_else",
        "gate_1_else",
        "gate_1",
    ]


# --- words (GT#9, #31) ----------------------------------------------------------------------------


def test_words_fail_closed_and_abstain_compile() -> None:
    sources = _sources(_compiled(_input_gate(then=sf.fail(), otherwise="prov/general")))
    assert "gate_1_then" not in sources and "gate_1_open_then" not in sources
    assert "gate_1_else" in sources
    join = sources["gate_1"].value
    assert isinstance(join, RelExpr) and isinstance(join.intent, Text)
    assert json.loads(join.intent.value)["then"] == "fail_closed"


def test_words_in_both_branches_compile() -> None:
    sources = _sources(_compiled(_input_gate(then="abstain", otherwise=sf.fail())))
    assert not any(name.endswith(("_then", "_else")) for name in sources if name.startswith("gate"))
    join = sources["gate_1"].value
    assert isinstance(join, RelExpr) and isinstance(join.intent, Text)
    spec = json.loads(join.intent.value)
    assert (spec["then"], spec["otherwise"]) == ("abstain", "fail_closed")


# --- refusals (GT#10, #11, #12, #16, #32; GU#19; GT-12) -------------------------------------------


def test_step_in_an_input_gate_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^a step in then= needs a panel: put the sf\.Gate after a sf\.Fanout, or give a "
        r"recipe$",
    ):
        _input_gate(then=sf.Vote())


def test_panel_ref_without_a_fanout_is_refused() -> None:
    gate = sf.Gate(when=sf.agreement() >= 0.8, then="prov/a", otherwise="prov/b")
    with pytest.raises(
        ValueError,
        match=r"^a panel condition reads a sf\.Fanout block: put the sf\.Gate after a sf\.Fanout$",
    ):
        _compiled(gate)


def test_gate_with_otherwise_as_a_fanout_member_is_refused() -> None:
    # GT-15 / SM-8: a member Gate takes no otherwise= (skip members); the message names the member.
    with pytest.raises(
        ValueError, match=r"^sf\.Fanout member 2: a sf\.Fanout member may be a sf\.Gate"
    ):
        sf.Fanout(["prov/a", _input_gate(otherwise="abstain")])


def test_agreement_gate_needs_a_vote() -> None:
    with pytest.raises(
        ValueError,
        match=r"^sf\.agreement\(\) needs a sf\.Vote in then= or otherwise=, or no reducer step "
        r"at all$",
    ):
        sf.Gate(when=sf.agreement() >= 0.8, then=sf.Median())


@pytest.mark.parametrize("position", ["when", "then", "otherwise"])
def test_gate_refuses_python_callables_with_the_guard_message(position: str) -> None:
    arguments: dict[str, object] = {"when": sf.label(_KW) == "math", "then": "prov/a"}
    arguments[position] = lambda question: "ignore" in question
    with pytest.raises(TypeError, match=r"a guard cannot run Python code$"):
        sf.Gate(**arguments)  # type: ignore[arg-type]


def test_skip_is_not_a_public_branch_value() -> None:
    with pytest.raises(
        TypeError, match=r"^sf\.Gate then= takes a step, a recipe, sf\.abstain\(\) or sf\.fail\(\)$"
    ):
        _input_gate(then="skip")


def test_gate_and_corrective_loop_nesting_is_refused() -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(_LOOP_REFUSAL)}$"):
        compile_candidate(sf.CorrectiveLoop([_input_gate(), "prov/b"], judge="prov/j"))
    with pytest.raises(ValueError, match=f"^{re.escape(_LOOP_REFUSAL)}$"):
        _input_gate(then=sf.CorrectiveLoop(["prov/a", "prov/b"], judge="prov/j"))


# --- the decision reducer (GT#15) -----------------------------------------------------------------


def _lowered_branch(gate: sf.Gate) -> BranchNode:
    node = lower(sf.Fanout(_PANEL) >> gate)
    assert isinstance(node, BranchNode)
    assert node.panel is not None
    return node


def test_decision_reducer_is_then_else_otherwise_else_implicit_vote() -> None:
    then_step = _lowered_branch(
        sf.Gate(when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large")
    )
    assert then_step.panel is not None
    assert then_step.then is then_step.panel.synthesizer

    otherwise_step = _lowered_branch(
        sf.Gate(when=sf.agreement() >= 0.8, then="prov/large", otherwise=sf.Vote())
    )
    assert otherwise_step.panel is not None
    assert otherwise_step.otherwise is otherwise_step.panel.synthesizer

    implicit = _lowered_branch(
        sf.Gate(when=sf.agreement() >= 0.8, then="prov/large", otherwise="prov/small")
    )
    assert implicit.panel is not None
    decision = implicit.panel.synthesizer
    assert isinstance(decision, DecisionReducer | VoteNode)
    if isinstance(decision, DecisionReducer):
        assert isinstance(decision.step, VoteNode)
    assert implicit.then is not decision and implicit.otherwise is not decision


# --- rebuild (GT#22, #23, #24) --------------------------------------------------------------------


def test_to_python_round_trips_a_three_way_gate() -> None:
    url4 = _compiled(_three_way())
    python = sf.Url4(url4).to_python()
    namespace: dict[str, object] = {}
    exec(python, namespace)  # noqa: S102 - the SDK's own generated code, offline
    assert _compiled(namespace["candidate"]) == url4
    lines = python.splitlines()
    assert sum("sf.Gate(" in line for line in lines) == 2
    outer = next(line for line in lines if line.startswith("candidate = sf.Gate("))
    nested = next(line for line in lines if "otherwise=sf.Gate(" in line)
    assert outer.startswith("candidate")
    assert nested.startswith("    otherwise=sf.Gate(")


def test_rebuild_refuses_a_spec_body_mismatch() -> None:
    url4 = _compiled(_input_gate())
    edited = url4.replace('"otherwise":"recipe"', '"otherwise":"abstain"')
    assert edited != url4
    with pytest.raises(ValueError, match=r"URL4 Candidate"):
        sf.Url4(edited).to_python()


def test_hand_added_gate_key_forces_recompile() -> None:
    assert "gate" in sdk_url4._PROVED_SPEC_KEYS


# --- selectors and layout (GT#25, #27, #30) -------------------------------------------------------


def test_equal_selectors_in_nested_gates_share_one_id() -> None:
    first = sf.RegexClassifier([("math", "integral"), ("code", "python")])
    second = sf.RegexClassifier([("math", "integral"), ("code", "python")])
    inner = sf.Gate(when=sf.label(second) == "code", then="prov/c", otherwise="prov/g")
    url4 = _compiled(sf.Gate(when=sf.label(first) == "math", then="prov/m", otherwise=inner))
    names = _sources(url4)
    assert [name for name in names if name.startswith("keywords_")] == ["keywords_1"]
    assert "sel_1" in url4 and "sel_2" not in url4


def test_eight_level_repr_is_linear_and_one_gate_per_line() -> None:
    value: object = "prov/last"
    for depth in range(8):
        value = _input_gate(then=f"prov/m{depth}", otherwise=value)
    assert repr(value).count("Gate(") == 8
    lines = code(value, "c").splitlines()  # type: ignore[arg-type]
    gate_lines = [line for line in lines if "sf.Gate(" in line]
    assert len(gate_lines) == 8
    assert gate_lines[0].startswith("c = sf.Gate(")
    assert all(line.lstrip().startswith("otherwise=sf.Gate(") for line in gate_lines[1:])
    assert len(lines) <= 8 * 6


@pytest.mark.parametrize("module", [gate_module, selectors_module], ids=["gate", "selectors"])
def test_messages_name_the_new_surface_only(module: object) -> None:
    source = Path(getattr(module, "__file__", "")).read_text(encoding="utf-8")
    assert "an sf." not in source
    assert "until E4c" not in source
