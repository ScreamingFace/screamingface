"""The re-point of final model steps to the chat final-step route (prd/tool-calls.md §3.2).

The re-point selects a source by its binding name and its scope, never by its path. It changes
only the path and the `binding` parameter of each selected source, at any depth of Gate bodies,
and the rendered copy must parse back to the same tree.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from _chat_corpus import corpus

from screamingface_engine.benchmarks.operation_outputs import parsed_iterate_body
from screamingface_engine.chat.recipe import (
    FinalPosition,
    RepointError,
    check_recipe,
    final_positions,
    repoint_final_steps,
)
from url4.core.nodes import Expression, Iteration, Node, RelExpr, Source
from url4.core.parser import build
from url4.core.render import render

_FINAL = "/ensemble/chat/v1/final"

Key = tuple[tuple[str, ...], str]


_CORPUS = corpus()


def _root(text: str) -> Expression:
    root = build(text)
    assert isinstance(root, Expression)
    return root


def _flatten(expr: Expression, scope: tuple[str, ...] = ()) -> dict[Key, Node]:
    """Each source by scope and name; an Iteration body is parsed and flattened too."""

    flat: dict[Key, Node] = {(scope, ""): replace(expr, sources=())}
    for index, source in enumerate(expr.sources):
        name = source.name if isinstance(source, Source) and source.name else f"#{index}"
        value = source.value if isinstance(source, Source) else None
        body = parsed_iterate_body(value) if isinstance(value, Iteration) else None
        if isinstance(source, Source) and isinstance(value, Iteration) and body is not None:
            flat[(scope, name)] = replace(source, value=replace(value, body=""))
            flat.update(_flatten(body, (*scope, name)))
        elif isinstance(source, Source) and isinstance(value, Expression):
            flat[(scope, name)] = replace(source, value=replace(value, sources=()))
            flat.update(_flatten(value, (*scope, name)))
        else:
            flat[(scope, name)] = source
    return flat


def _rel(flat: dict[Key, Node], key: Key) -> RelExpr:
    source = flat[key]
    assert isinstance(source, Source)
    assert isinstance(source.value, RelExpr)
    return source.value


def _assert_only_selected_changed(text: str, out: str, selected: set[Key]) -> None:
    old, new = _flatten(_root(text)), _flatten(_root(out))
    assert old.keys() == new.keys()
    for key in old.keys() - selected:
        assert old[key] == new[key], key
    for key in selected:
        before, after = _rel(old, key), _rel(new, key)
        assert after.path == _FINAL + before.path
        assert replace(after, path=before.path, params=before.params) == before


_D1_INNER = ("gate_1_block", "gate_1_else", "gate_2_block")


def test_repoint_inside_nested_gate_bodies_round_trips() -> None:
    """TC-31: final model steps in nested Gate bodies are re-pointed and round-trip."""

    text = _CORPUS["d1_keyword_router.url4"]
    root = _root(text)
    models = [p for p in final_positions(root) if p.kind == "model"]
    assert {(p.binding, p.scope) for p in models} == {
        ("model_4", (*_D1_INNER, "gate_2_then")),
        ("model_5", (*_D1_INNER, "gate_2_else")),
    }
    out = repoint_final_steps(root, models)
    assert render(build(out)) == out
    assert "binding=model_4" in out
    assert "binding=model_5" in out
    after = {p.binding: p for p in final_positions(_root(out)) if p.kind == "model"}
    assert after["model_4"].route == _FINAL + "/prov/coder"
    assert after["model_5"].route == _FINAL + "/prov/general"
    assert {p.binding: p.scope for p in models} == {k: p.scope for k, p in after.items()}
    _assert_only_selected_changed(text, out, {(p.scope, str(p.binding)) for p in models})


def test_repoint_of_a_gate_in_an_outer_body_round_trips() -> None:
    """TC-31: every final model of a Gate inside an outer body is re-pointed; a stage is not."""

    text = _CORPUS["outer_body_holds_a_gate.url4"]
    root = _root(text)
    models = [p for p in final_positions(root) if p.kind == "model"]
    assert sorted(str(p.binding) for p in models) == ["model_1", "model_3", "model_4"]
    out = repoint_final_steps(root, models)
    assert render(build(out)) == out
    selected = {(p.scope, str(p.binding)) for p in models}
    _assert_only_selected_changed(text, out, selected)
    model_2 = [k for k in _flatten(_root(out)) if k[1] == "model_2"]
    assert model_2
    assert not set(model_2) & selected


def test_member_and_synthesizer_on_one_route_only_synthesizer_is_repointed() -> None:
    """TC-32: selection is by binding name, so a member on the synthesizer route is kept."""

    text = (
        "(model_1:0.0:/prov/a($input)!'Answer.', model_2:0.0:/prov/b($input)!'Answer.', "
        "synthesis_1:0.0:/prov/a?binding=synthesis_1&q=({input: '$input', outputs: "
        "{member_1: '$model_1', member_2: '$model_2'}})!'Synthesize.')!'$synthesis_1'"
    )
    checked = check_recipe(text, with_tools=True)
    assert checked.positions == (FinalPosition("model", "synthesis_1", (), "/prov/a"),)
    flat = _flatten(_root(repoint_final_steps(checked.root, checked.positions)))
    member = _rel(flat, ((), "model_1"))
    assert member.path == "/prov/a"
    assert all(key != "binding" for key, _ in member.params)
    assert _rel(flat, ((), "synthesis_1")).path == _FINAL + "/prov/a"


def test_repoint_adds_binding_param_when_absent() -> None:
    """tool-calls §3.2 step 4: a missing binding parameter is added, an existing one is kept."""

    writer = _root(_CORPUS["cascade_then_writer.url4"])
    assert _rel(_flatten(writer), ((), "model_4")).params == ()
    out = repoint_final_steps(writer, final_positions(writer))
    assert _rel(_flatten(_root(out)), ((), "model_4")).params == (("binding", "model_4"),)

    router = _root(_CORPUS["d1_keyword_router.url4"])
    models = [p for p in final_positions(router) if p.kind == "model"]
    flat = _flatten(_root(repoint_final_steps(router, models)))
    for position in models:
        params = _rel(flat, (position.scope, str(position.binding))).params
        assert [key for key, _ in params].count("binding") == 1


def test_repoint_refuses_a_position_that_is_not_a_model() -> None:
    """tool-calls §3.2: only a model step can move to the final-step route."""

    root = _root(_CORPUS["surface_parity:S1"])
    with pytest.raises(RepointError):
        repoint_final_steps(root, [FinalPosition("reducer", "synthesis_1", (), None)])
