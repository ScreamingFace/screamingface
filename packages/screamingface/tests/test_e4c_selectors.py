"""Selectors: sf.RegexClassifier and sf.LLMClassifier label the Case input; sf.label and sf.labels
read them.

FEATURE: E4c (OME-1291) selectors PRD rows SL#1, #2 (CHAR), #14, #15, #16, #18, #19, #20, #22.
STORY: as a researcher who routes questions, I build a selector that the SDK checks before any
spend, the LLMClassifier call compiles to one optional call with a versioned template, one selector
is evaluated once per candidate however many Gates read it, and its call sits at the lowest scope
that holds every Gate that reads it.
"""

from __future__ import annotations

import pytest
from url4 import Expression, Iteration, Node, RelExpr, Source, Text, build, walk

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._regex_rule import check_regex
from screamingface.accounting import _ACCOUNTED_STAGES
from screamingface.branch import BranchCondition, BranchNode
from screamingface.judge import LABEL_TEMPLATE_ID, judge_intent

_LOOKAHEAD = "secret(?=word)"


def _gate(selector, label, then, otherwise, *, observe: str = "label", cmp: str = "eq"):
    return BranchNode(
        condition=BranchCondition(observe, cmp, label, selector), then=then, otherwise=otherwise
    )


def _root(recipe) -> Expression:
    node = build(compile_candidate(recipe).url4)
    assert isinstance(node, Expression)
    return node


def _named(nodes, name: str) -> Source:
    return next(node for node in nodes if isinstance(node, Source) and node.name == name)


def _deep(node: Node):
    for child in walk(node):
        yield child
        if isinstance(child, Iteration) and child.intent:
            yield from _deep(build(f"({child.body})!{child.intent}"))


def _iterate_body(root: Expression, name: str) -> Expression:
    iteration = _named(_deep(root), name).value
    assert isinstance(iteration, Iteration)
    body = build(f"({iteration.body})!{iteration.intent}")
    assert isinstance(body, Expression)
    return body


# --- CHAR -----------------------------------------------------------------------------------------


def test_check_regex_refuses_lookahead_without_echo() -> None:
    # SL#1 (CHAR): the pre-spend check refuses what RE2 refuses, and never quotes the pattern.
    with pytest.raises(ValueError) as caught:
        check_regex({"pattern": _LOOKAHEAD}, "rule")
    assert "lookaround" in str(caught.value)
    assert _LOOKAHEAD not in str(caught.value)


def test_judge_label_template_first_line_is_its_id() -> None:
    # SL#2 (CHAR): the judge templates start with their versioned id (the exemplar of SL-8).
    assert judge_intent("label", "Pick the best.").splitlines()[0].startswith(LABEL_TEMPLATE_ID)


# --- SL#14 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("multi", "max_tokens"), [(False, "16"), (True, "64")])
def test_label_model_compiles_label_template_and_json_input(multi: bool, max_tokens: str) -> None:
    selector = sf.LLMClassifier("prov/clf", labels=["math", "code"], multi=multi)
    condition = (
        BranchCondition("labels", "has", "math", selector)
        if multi
        else BranchCondition("label", "eq", "math", selector)
    )
    root = _root(
        BranchNode(condition=condition, then=sf.Model("prov/a"), otherwise=sf.Model("prov/b"))
    )
    call = _named(root.sources, "selector_1")
    assert isinstance(call.value, RelExpr)
    assert call.value.params == (("binding", "selector_1"), ("max_tokens", max_tokens))
    assert call.value.context == "{input: '$input'}"
    assert ("optional", None) in call.annotations
    intent = call.value.intent
    assert isinstance(intent, Text)
    first = intent.value.replace("\u2028", "\n").splitlines()[0]
    assert first == f"label-template@1 multi={'true' if multi else 'false'}"
    assert "Allowed labels, in order: math, code" in intent.value


# --- SL#15, #18 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rules",
    [
        [],
        [(f"l{index}", "x") for index in range(33)],
        [("Math", "x")],
        [("math", "x"), ("math", "y")],
        [("math", _LOOKAHEAD)],
    ],
    ids=["empty", "33_rules", "bad_label", "repeated_label", "lookahead"],
)
def test_keywords_constructor_refuses_bad_rules_without_echo(rules) -> None:
    with pytest.raises((ValueError, TypeError)) as caught:
        sf.RegexClassifier(rules)
    assert _LOOKAHEAD not in str(caught.value)


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        ("prov/clf", {"labels": []}),
        ("prov/clf", {"labels": [f"l{index}" for index in range(33)]}),
        ("prov/clf", {"labels": ["math", "math"]}),
        ("prov/clf", {"labels": ["Math"]}),
        (sf.Model("prov/clf", optional=True), {"labels": ["math"]}),
        (sf.Model("prov/clf", name="mine"), {"labels": ["math"]}),
        ("prov/clf", {"labels": ["math"], "prompt": "x" * 16_385}),
    ],
    ids=["no_labels", "33_labels", "repeated", "ill_formed", "optional", "named", "long_prompt"],
)
def test_label_model_constructor_refuses_bad_options(model, kwargs) -> None:
    with pytest.raises(ValueError):
        sf.LLMClassifier(model, **kwargs)


# --- SL#19 ----------------------------------------------------------------------------------------


def test_label_refs_refuse_wrong_kind_and_undeclared_label_and_build_ne_and_empty() -> None:
    single = sf.RegexClassifier([("math", "integral"), ("code", "python")])
    multi = sf.RegexClassifier([("math", "integral"), ("code", "python")], multi=True)

    with pytest.raises(TypeError, match=r"sf\.labels\(\)"):
        sf.label(multi)
    with pytest.raises(TypeError, match=r"sf\.label\(\)"):
        sf.labels(single)
    with pytest.raises(ValueError, match="never runs"):
        _ = sf.label(single) == "physics"
    not_math = sf.label(single) != "math"
    assert (not_math.observe, not_math.cmp, not_math.value) == ("label", "ne", "math")
    empty = sf.labels(multi).empty()
    assert (empty.observe, empty.cmp, empty.value) == ("labels", "empty", None)
    assert not hasattr(sf.label(single), "empty")


# --- SL#20 ----------------------------------------------------------------------------------------


def test_equal_selectors_share_one_id() -> None:
    first = sf.RegexClassifier([("math", "integral"), ("code", "python")])
    twin = sf.RegexClassifier([("math", "integral"), ("code", "python")])
    inner = _gate(twin, "code", sf.Model("prov/c"), sf.Model("prov/g"))
    url4 = compile_candidate(_gate(first, "math", sf.Model("prov/m"), inner)).url4
    assert '"observe":"label:sel_1"' in url4
    assert "sel_2" not in url4

    other = sf.RegexClassifier([("math", "derivative"), ("code", "python")])
    inner = _gate(other, "code", sf.Model("prov/c"), sf.Model("prov/g"))
    url4 = compile_candidate(_gate(first, "math", sf.Model("prov/m"), inner)).url4
    assert '"observe":"label:sel_2"' in url4


def test_equal_label_models_compile_to_one_call() -> None:
    first = sf.LLMClassifier("prov/clf", labels=["math", "code"])
    twin = sf.LLMClassifier("prov/clf", labels=["math", "code"])
    inner = _gate(twin, "code", sf.Model("prov/c"), sf.Model("prov/g"))
    root = _root(_gate(first, "math", sf.Model("prov/m"), inner))
    names = {node.name for node in _deep(root) if isinstance(node, Source)}
    assert "selector_1" in names
    assert "selector_2" not in names


# --- SL#22 ----------------------------------------------------------------------------------------


def test_selector_operation_is_accounted_as_synthesis() -> None:
    assert _ACCOUNTED_STAGES["selector"] == "synthesis"
    selector = sf.LLMClassifier("prov/clf", labels=["math"])
    compiled = compile_candidate(_gate(selector, "math", sf.Model("prov/a"), sf.Model("prov/b")))
    assert {op.id: op.kind for op in compiled.operations}["op_selector_1"] == "selector"


# --- SL#16 ----------------------------------------------------------------------------------------


def test_selector_placed_at_lowest_common_scope_both_branches() -> None:
    # (a) Gates in both branches of G read the LLMClassifier; G reads a RegexClassifier: the call
    # sits in G's scope (the candidate top level, G is the root), before G's block.
    kw = sf.RegexClassifier([("math", "integral")])
    clf = sf.LLMClassifier("prov/clf", labels=["safe", "unsafe"])
    left = _gate(clf, "safe", sf.Model("prov/a"), sf.Model("prov/b"))
    right = _gate(clf, "unsafe", sf.Model("prov/c"), sf.Model("prov/d"))
    root = _root(_gate(kw, "math", left, right))
    names = [node.name for node in root.sources if isinstance(node, Source)]
    assert names.index("selector_1") < names.index("gate_1_block")


def test_selector_placed_at_lowest_common_scope_one_branch() -> None:
    # (b) only a Gate inside G's otherwise reads it: the call sits inside that iterate body.
    kw = sf.RegexClassifier([("math", "integral")])
    clf = sf.LLMClassifier("prov/clf", labels=["safe", "unsafe"])
    inner = _gate(clf, "safe", sf.Model("prov/a"), sf.Model("prov/b"))
    root = _root(_gate(kw, "math", sf.Model("prov/m"), inner))
    assert "selector_1" not in [node.name for node in root.sources if isinstance(node, Source)]
    body = _iterate_body(root, "gate_1_else")
    assert "selector_1" in [node.name for node in body.sources if isinstance(node, Source)]
