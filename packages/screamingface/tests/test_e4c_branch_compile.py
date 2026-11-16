"""The sf.Gate renderer: the gated url4 shape, its names, its checks and its call counts.

FEATURE: E4c (OME-1291) branch-core rows BC#17, #17a, #25, #28, #34, #35 (contracts C1).
STORY: as the compiler, I render every Gate as one named inner expression whose bodies sit in
gated iterates; a body reads only what runs unconditionally around it, DECIDE orders after only
bindings in scope, every call in a body names itself, and the names and counts are stable.
"""

from __future__ import annotations

import re

import pytest
from url4 import Expression, Iteration, Node, RelExpr, Source, Text, build, src, walk

import screamingface as sf
from screamingface._evaluation.branch import _Body, _BranchState, _Gate, _Tree
from screamingface._evaluation.candidate import _CandidateCompiler, compile_candidate
from screamingface.branch import BranchCondition, BranchNode

_KW = sf.RegexClassifier([("math", r"(?i)\bintegral\b"), ("code", "python")])


def _gate(label: str, then, otherwise) -> BranchNode:
    return BranchNode(
        condition=BranchCondition("label", "eq", label, _KW), then=then, otherwise=otherwise
    )


def _nested() -> BranchNode:
    inner = _gate("code", sf.Model("prov/coder"), sf.Model("prov/general"))
    return _gate("math", sf.Model("prov/math"), inner)


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


def _model(name: str, context: str) -> Source:
    source = src(
        RelExpr(path="/prov/m", context=context, intent=Text("Answer")), name=name, weight=0.0
    )
    assert isinstance(source, Source)
    return source


def _bare_gate(input_context: str = "$input") -> tuple[_Gate, _CandidateCompiler]:
    compiler = _CandidateCompiler()
    state = _BranchState(tree=_Tree())
    gate = _Gate(compiler, state, _gate("math", sf.Model("prov/a"), "abstain"), input_context, ())
    return gate, compiler


# --- BC#17 ----------------------------------------------------------------------------------------


def test_a_body_that_reads_an_outer_only_model_source_is_a_compile_error() -> None:
    # D5: model_9 sits outside the body and no unconditional source reads it, so it would run on
    # every Case for one body's sake.
    gate, compiler = _bare_gate()
    compiler._sources.append(_model("model_9", "$input"))
    body = _Body("recipe", sources=(_model("model_2", "$model_9"),), reference="$model_2")
    with pytest.raises(ValueError, match="only that body needs"):
        gate._check_body(body, {"model_9", "input"}, own=())


def test_a_body_may_read_the_gate_input_and_a_hoisted_selector() -> None:
    gate, compiler = _bare_gate("$model_1")
    compiler._sources.append(_model("model_1", "$input"))  # the previous stage: AFTER reads it
    compiler._sources.append(_model("selector_1", "$input"))
    after = _model("gate_1_after", "r1:0.0:$model_1, r2:0.0:$selector_1")
    body = _Body(
        "recipe", sources=(_model("model_2", "$model_1 $selector_1"),), reference="$model_2"
    )
    gate._check_body(body, {"model_1", "selector_1", "input"}, own=(after,))


def test_a_body_that_reads_an_unknown_binding_is_a_compile_error() -> None:
    gate, _ = _bare_gate()
    body = _Body("recipe", sources=(_model("model_2", "$ghost"),), reference="$model_2")
    with pytest.raises(ValueError, match="no enclosing scope defines"):
        gate._check_body(body, {"input"}, own=())


# --- BC#17a ---------------------------------------------------------------------------------------


def test_an_after_reference_out_of_scope_is_a_compile_error() -> None:
    gate, _ = _bare_gate("$member_inner")
    with pytest.raises(ValueError, match="not in scope"):
        gate._after({"input"})


def test_after_uses_only_instrumental_slots() -> None:
    after = _sources(compile_candidate(_nested()).url4)["gate_1_after"].value
    assert isinstance(after, RelExpr)
    slots = (after.context or "").split(", ")
    assert slots and all(
        re.fullmatch(r"r\d+:0\.0:\$[A-Za-z_][A-Za-z0-9_]*", slot) for slot in slots
    )


# --- BC#25 ----------------------------------------------------------------------------------------


def test_operation_ids_are_stable_and_gated_calls_carry_the_binding_param() -> None:
    first, second = compile_candidate(_nested()), compile_candidate(_nested())
    assert first.url4 == second.url4
    assert [op.id for op in first.operations] == [op.id for op in second.operations]

    sources = _sources(first.url4)
    for name in ("gate_1_after", "gate_1_decide", "gate_1_open_then", "gate_1_open_else"):
        assert name in sources
    assert {"gate_1_block", "gate_2_block", "gate_1", "gate_2"} <= sources.keys()
    for join in ("gate_1", "gate_2"):
        value = sources[join].value
        assert isinstance(value, RelExpr)
        assert value.params == (("binding", join),)
    for gated in ("gate_1_then", "gate_1_else", "gate_2_then", "gate_2_else"):
        iteration = sources[gated].value
        assert isinstance(iteration, Iteration)
        body = build(f"({iteration.body})!{iteration.intent}")
        for node in _deep(body):
            if (
                isinstance(node, Source)
                and isinstance(node.value, RelExpr)
                and not node.value.path.startswith("/ensemble/")
            ):
                assert node.value.params[:1] == (("binding", node.name),)


# --- BC#28 ----------------------------------------------------------------------------------------


def test_body_prompts_hold_no_accounting_envelope() -> None:
    sources = _sources(compile_candidate(_nested()).url4)
    for gated in ("gate_1_then", "gate_1_else", "gate_2_then", "gate_2_else"):
        iteration = sources[gated].value
        assert isinstance(iteration, Iteration)
        for node in _deep(build(f"({iteration.body})!{iteration.intent}")):
            if isinstance(node, RelExpr) and not node.path.startswith("/ensemble/"):
                text = f"{node.context} {getattr(node.intent, 'value', '')}"
                for word in ("invocation", "accounting", "tokens"):
                    assert word not in text


# --- BC#34 ----------------------------------------------------------------------------------------


def test_not_run_entry_counts_min_and_max_model_calls() -> None:
    model = sf.Model
    inner = _gate(
        "code",
        model("p/a") >> model("p/b"),
        model("p/c") >> model("p/d") >> model("p/e") >> model("p/f"),
    )
    body = model("p/x") >> model("p/y") >> model("p/z") >> inner
    decide = _sources(compile_candidate(_gate("math", body, model("p/g"))).url4)["gate_1_decide"]
    assert isinstance(decide.value, RelExpr)
    # The gate spec is DECIDE's intent (as a combine spec is a combine call's intent).
    assert isinstance(decide.value.intent, Text)
    assert '"then":{"max":7,"min":5}' in decide.value.intent.value
    assert '"otherwise":{"max":1,"min":1}' in decide.value.intent.value


# --- BC#35 ----------------------------------------------------------------------------------------


def _chain(depth: int) -> BranchNode:
    node: object = sf.Model("prov/leaf")
    for _ in range(depth):
        node = _gate("math", sf.Model("prov/m"), node)
    assert isinstance(node, BranchNode)
    return node


def test_gate_depth_nine_is_refused_at_compile() -> None:
    assert isinstance(build(compile_candidate(_chain(8)).url4), Expression)
    with pytest.raises(ValueError, match="sf.Gate nests at most 8 deep"):
        compile_candidate(_chain(9))
