"""The chat recipe check: the model value rule, the final positions and the refusals.

The spec is prd/tool-calls.md §3.1 (final positions) and prd/chat-completion.md CC-S1, CC-S13 and
CC-S14 (the model value rule and the refused recipes), with plan decision D4 (a gateway model id).
The table tests read every recipe of the SDK surface corpus and of the Gate contract corpus.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from typing import Any

import pytest
from _chat_corpus import REPO, corpus

from screamingface_engine.benchmarks.operation_outputs import parsed_iterate_body
from screamingface_engine.chat.recipe import (
    _FINAL_BINDING,
    FinalPosition,
    RecipeRefusal,
    check_recipe,
    is_recipe_value,
    one_model_recipe,
)
from url4.core.nodes import Expression, Iteration, Source, Text, walk
from url4.core.parser import build

_NO_DESCRIPTOR = "lowering:pair-synthesize-evaluation"
_OUTCOMES = frozenset({"abstain", "fail_closed", "skip"})
_SDK_BINDINGS = REPO / "packages/screamingface/src/screamingface/_operation_bindings.py"
_SDK_MOVED = "FINAL_BINDING moved in the SDK; update this bind"
_PROMPT = (
    "Answer the request accurately and completely. "
    "Follow every instruction and formatting constraint in the request."
)
_D1_MODEL_1 = f"model_1:0.0:/prov/alpha?binding=model_1&q=($input)!'{_PROMPT}'"

_CORPUS = corpus()


def _descriptor(text: str) -> dict[str, Any]:
    """The recipe tree of the `_sf_recipe` descriptor, which the oracle reads."""

    root = build(text)
    assert isinstance(root, Expression)
    for source in root.sources:
        if isinstance(source, Source) and source.name == "_sf_recipe":
            assert isinstance(source.value, Text)
            return json.loads(source.value.value)["recipe"]
    raise AssertionError("the recipe has no _sf_recipe descriptor")


def _oracle(node: dict[str, Any] | str) -> list[tuple[str, str | None]]:
    """The final positions that the SDK descriptor says the recipe has."""

    positions: list[tuple[str, str | None]]
    if isinstance(node, str):
        positions = [("not_model", None)] if node == "step" else [("outcome", None)]
    elif node["kind"] == "pipeline":
        positions = _oracle(node["stages"][-1])
    elif node["kind"] == "gate":
        positions = _oracle(node["then"]) + _oracle(node["otherwise"])
    elif node["kind"] == "fusion" and node["synthesizer"]["kind"] == "reducer":
        positions = [("not_model", None)]
    else:
        positions = [("model", node["binding"])]
    return positions


def _project(position: FinalPosition) -> tuple[str, str | None]:
    if position.kind == "model":
        return ("model", position.binding)
    if position.kind in {"reducer", "step"}:
        return ("not_model", None)
    return (position.kind, None)


def _refusal(text: str, *, with_tools: bool) -> RecipeRefusal:
    with pytest.raises(RecipeRefusal) as caught:
        check_recipe(text, with_tools=with_tools)
    return caught.value


def test_corpus_has_every_recipe() -> None:
    # INVARIANT: the parametrized table test below covers every corpus entry, so no fixed count
    # is pinned; both corpora must contribute.
    assert any(name.endswith(".url4") for name in _CORPUS)
    assert any(not name.endswith(".url4") for name in _CORPUS)
    assert _NO_DESCRIPTOR in _CORPUS


@pytest.mark.parametrize("name", sorted(_CORPUS), ids=sorted(_CORPUS))
def test_final_positions_of_model_fusion_pipeline_gate_cascade_are_found(name: str) -> None:
    """TC-1: the check finds the final positions that the SDK descriptor names."""

    text = _CORPUS[name]
    if name == _NO_DESCRIPTOR:
        # WHY: a benchmark-linked expression has no final form that the check knows.
        assert _refusal(text, with_tools=False).code == "recipe_invalid"
        return
    expected = _oracle(_descriptor(text))
    checked = check_recipe(text, with_tools=False)
    assert Counter(_project(p) for p in checked.positions) == Counter(expected), name
    if ("not_model", None) in expected:
        assert _refusal(text, with_tools=True).code == "final_step_not_model"
    else:
        check_recipe(text, with_tools=True)


def test_reducer_final_with_tools_is_refused() -> None:
    """TC-2: a recipe that ends in a vote is refused with tools and runs without them."""

    text = _CORPUS["surface_parity:S1"]
    assert _refusal(text, with_tools=True).code == "final_step_not_model"
    assert check_recipe(text, with_tools=False).positions == (
        FinalPosition("reducer", "synthesis_1", (), None),
    )


@pytest.mark.parametrize("name", ["vote_body_gate.url4", "d1_keyword_router.url4"])
def test_gate_with_one_reducer_branch_with_tools_is_refused(name: str) -> None:
    """TC-3: a Gate with one branch that ends in a reducer is refused with tools."""

    text = _CORPUS[name]
    assert _refusal(text, with_tools=True).code == "final_step_not_model"
    check_recipe(text, with_tools=False)


def test_unclassified_final_form_with_tools_is_refused() -> None:
    """TC-4: a final form that the check cannot classify fails closed with tools."""

    select = "(synthesis_1:0.0:/ensemble/select/v1/keywords($input)!'{}')!'$synthesis_1'"
    assert _refusal(select, with_tools=True).code == "recipe_not_supported"
    assert check_recipe(select, with_tools=False).positions == (
        FinalPosition("unknown", "synthesis_1", (), None),
    )

    router = _CORPUS["keyword_router.url4"]
    mystery = router.replace('"then":"recipe"', '"then":"mystery"')
    assert mystery != router
    assert _refusal(mystery, with_tools=True).code == "recipe_not_supported"

    writer = "(writer_1:0.0:/prov/a($input)!'x')!'$writer_1'"
    assert _refusal(writer, with_tools=True).code == "recipe_invalid"
    assert _refusal(writer, with_tools=False).code == "recipe_invalid"

    broken = "(model_1:0.0:/prov/a b($input)!'x')!'$model_1'"
    assert _refusal(broken, with_tools=False).code == "recipe_invalid"


def _dangling_roots() -> list[str]:
    """Recipes whose root intent names a binding that no root source has (CC-S13)."""

    router = _CORPUS["keyword_router.url4"]
    assert router.endswith("!'$gate_1_block'")
    no_block = router[: -len("$gate_1_block'")] + "$gate_9_block'"
    return [
        "(model_1:0.0:/p/a($input)!'x')!'$model_9'",
        "(model_1:0.0:/p/a($input)!'x')!$model_9",
        "(synthesis_1:0.0:/ensemble/select/v1/keywords($input)!'{}')!'$synthesis_2'",
        "(model_1:0.0:/p/a($input)!'x')!'$gate_1_block'",
        "(model_1:0.0:/p/a($input)!'x')!'$loop_candidate'",
        no_block,
    ]


@pytest.mark.parametrize("with_tools", [True, False])
def test_root_that_names_a_missing_binding_is_invalid(with_tools: bool) -> None:
    """CC-S13: a root intent that names no source of the recipe is a broken form, tools or not."""

    for text in _dangling_roots():
        assert build(text) is not None
        assert _refusal(text, with_tools=with_tools).code == "recipe_invalid", text


def _final_route_recipes() -> list[str]:
    word_abstain = _CORPUS["word_abstain.url4"]
    in_body = word_abstain.replace("/prov/general?", "/ensemble/chat/v1/final/prov/general?")
    assert in_body != word_abstain
    return [
        "(model_1:0.0:/ensemble/chat/v1/final/prov/a($input)!'x')!'$model_1'",
        "(model_1:0.0:/ensemble/chat/v1/turn($input)!'x')!'$model_1'",
        in_body,
    ]


@pytest.mark.parametrize("with_tools", [True, False])
def test_recipe_naming_final_route_prefix_is_refused_at_any_depth(with_tools: bool) -> None:
    """TC-29: a client recipe must not name the chat route prefix, Gate bodies included."""

    for text in _final_route_recipes():
        assert _refusal(text, with_tools=with_tools).code == "recipe_not_supported"


def test_cascade_with_tools_is_refused_and_cascade_then_model_is_allowed() -> None:
    """TC-33: a Cascade with tools is refused with the `>> model` hint; a final model is allowed."""

    for name in ("cascade_three.url4", "d4_cope_cascade.url4"):
        refusal = _refusal(_CORPUS[name], with_tools=True)
        assert refusal.code == "final_step_not_model"
        assert ">> model" in refusal.message
    checked = check_recipe(_CORPUS["cascade_then_writer.url4"], with_tools=True)
    assert checked.positions == (FinalPosition("model", "model_4", (), "/prov/writer"),)


@pytest.mark.parametrize("with_tools", [True, False])
def test_corrective_loop_is_refused_with_and_without_tools(with_tools: bool) -> None:
    """CC-S14: a corrective loop needs a Benchmark, so the chat route refuses it."""

    loop = "(loop_candidate:0.0:(model_1:0.0:/prov/a($input)!'x')!'$model_1')!'$loop_candidate'"
    assert _refusal(loop, with_tools=with_tools).code == "recipe_not_supported"


def _loop_in_a_branch_body() -> str:
    """d1_keyword_router with a corrective loop around model_1 inside the gate_1_then body."""

    router = _CORPUS["d1_keyword_router.url4"]
    assert router.count(_D1_MODEL_1) == 1
    text = router.replace(_D1_MODEL_1, f"loop_candidate:0.0:({_D1_MODEL_1})!'$model_1'")
    root = build(text)
    assert isinstance(root, Expression)
    block = next(s for s in root.sources if isinstance(s, Source) and s.name == "gate_1_block")
    assert isinstance(block.value, Expression)
    then = next(s for s in block.value.sources if isinstance(s, Source) and s.name == "gate_1_then")
    assert isinstance(then.value, Iteration)
    body = parsed_iterate_body(then.value)
    assert body is not None
    assert any(isinstance(n, Source) and n.name == "loop_candidate" for n in walk(body))
    return text


def _loops_at_depth() -> list[str]:
    inner = (
        "(loop_candidate:0.0:(model_1:0.0:/p/a($input)!'x')!'$model_1', "
        "model_2:0.0:/p/b($loop_candidate)!'y')!'$model_2'"
    )
    return [inner, _loop_in_a_branch_body()]


@pytest.mark.parametrize("with_tools", [False, True])
def test_corrective_loop_at_any_depth_is_refused(with_tools: bool) -> None:
    """CC-S14: a recipe that has a corrective loop is refused, Gate branch bodies included."""

    for text in _loops_at_depth():
        assert _refusal(text, with_tools=with_tools).code == "recipe_not_supported"


def _sdk_assignments() -> dict[str, ast.expr]:
    """The module-level `NAME = value` assignments of the SDK binding module."""

    found: dict[str, ast.expr] = {}
    for node in ast.parse(_SDK_BINDINGS.read_text()).body:
        target = (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        )
        if isinstance(node, ast.Assign) and isinstance(target, ast.Name):
            found[target.id] = node.value
    return found


def _sdk_strings(assignments: dict[str, ast.expr]) -> dict[str, str]:
    return {
        name: value.value
        for name, value in assignments.items()
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }


def _compiled_template(value: ast.expr | None) -> ast.JoinedStr:
    """The f-string of a `re.compile(f"...")` call."""

    call = value if isinstance(value, ast.Call) else None
    func = call.func if call is not None else None
    is_compile = isinstance(func, ast.Attribute) and func.attr == "compile"
    template = call.args[0] if call is not None and is_compile and len(call.args) == 1 else None
    assert isinstance(template, ast.JoinedStr), _SDK_MOVED
    return template


def _joined(template: ast.JoinedStr, strings: dict[str, str]) -> str:
    """The pattern text of an f-string whose fields name module-level string constants."""

    parts: list[str] = []
    for part in template.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            parts.append(part.value)
        elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            assert part.value.id in strings, _SDK_MOVED
            parts.append(strings[part.value.id])
        else:
            raise AssertionError(_SDK_MOVED)
    return "".join(parts)


def test_final_binding_is_in_lock_step_with_the_sdk() -> None:
    """The check knows the same final forms as FINAL_BINDING of the SDK binding module."""

    assignments = _sdk_assignments()
    template = _compiled_template(assignments.get("FINAL_BINDING"))
    sdk_pattern = _joined(template, _sdk_strings(assignments))
    assert sdk_pattern == "\\$(" + _FINAL_BINDING.pattern + ")"


def test_model_value_starts_with_a_paren_after_white_space() -> None:
    """CC-S1: a value that starts with "(" after white space is a URL4; else a model id."""

    assert is_recipe_value("(x)")
    assert is_recipe_value("  \n(x)")
    assert not is_recipe_value("openai/gpt-4o")
    assert not is_recipe_value("")


def test_gateway_model_id_becomes_one_model_recipe() -> None:
    """D4: a gateway model id runs as a one-model recipe on its route."""

    assert one_model_recipe("openai/gpt-4o") == "(model_1:0.0:/openai/gpt-4o($input)!'')!'$model_1'"
    assert "/ollama/llama3~8b(" in one_model_recipe("ollama/llama3:8b")
    checked = check_recipe(one_model_recipe("openai/gpt-4o"), with_tools=True)
    assert checked.positions == (FinalPosition("model", "model_1", (), "/openai/gpt-4o"),)


@pytest.mark.parametrize("model_id", ["", "a b", "x~y", "/a", "a//b", "a'b"])
def test_invalid_model_id_is_refused_by_the_recipe_builder(model_id: str) -> None:
    """D4: a model id that is not a clean route path never becomes a recipe."""

    with pytest.raises(ValueError):
        one_model_recipe(model_id)
