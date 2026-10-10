"""`OME-508` — mandatory ``intent-op intent`` on expression groups and iteration bodies.

# FEATURE: the grammar's expression production — "(" source-list ")" intent-op
# intent — always carries an intent; the engine now rejects the intent-less
# forms it used to accept (owner ruling, 2026-07-20).
#
# INVARIANT: enforcement lives at the parse/render/builder BOUNDARY. The AST's
# `Expression(intent=None)` remains the internal carrier for paren-collections
# and AST-path compilation, so the DAG machinery is untouched.
"""

from __future__ import annotations

import asyncio

import pytest

from url4.core.builders import expr, iterate
from url4.core.errors import ParseError, RenderError
from url4.core.nodes import Expression, Iteration, Text
from url4.core.parser import build
from url4.core.render import render
from url4.io.static import StaticIOLayer

# --- bare groups are rejected at every parse entry ----------------------------------


@pytest.mark.parametrize("text", ["(a, b, c)", "(https://x)", "('only text')"])
def test_top_level_bare_group_is_rejected(text: str) -> None:
    with pytest.raises(ParseError, match="intent"):
        build(text)


def test_nested_bare_group_is_rejected() -> None:
    # local-expr in value position is the same production — intent mandatory.
    with pytest.raises(ParseError, match="intent"):
        build("(a, (b, c), d)!'combine'")


def test_bare_group_as_binding_value_is_rejected() -> None:
    with pytest.raises(ParseError, match="intent"):
        build("(x=(a, b))!'use $x'")


def test_dag_text_path_rejects_a_bare_group() -> None:
    # run() decodes through the same envelope as build() — the DAG text path
    # must reject what the eager parse rejects.
    from url4.dag import run

    with pytest.raises(ParseError, match="intent"):
        asyncio.run(run("(a, b, c)", StaticIOLayer()))


# --- iteration bodies require the per-row intent (owner: fully strict) --------------


def test_map_only_iteration_is_rejected() -> None:
    # iteration-expr = collection-ref "*" expression — the expression after "*"
    # carries a mandatory intent, so `src*(body)` with no trailing ! is illegal.
    with pytest.raises(ParseError, match="intent"):
        build("(a, b)*('row: $item')")


def test_reducer_without_per_row_intent_is_rejected() -> None:
    # The cross-row shape must carry the per-row intent too:
    # (src*(body)!peri)!reducer — never (src*(body))!reducer.
    with pytest.raises(ParseError, match="intent"):
        build("((a, b)*('row: $item'))!'summarize all'")


def test_iteration_with_per_row_intent_still_parses() -> None:
    node = build("(a, b)*('row: $item')!'per row'")
    assert isinstance(node, Iteration)
    assert node.intent == "'per row'"


def test_coexisting_per_row_intent_and_reducer_still_parse() -> None:
    node = build("((a, b)*('row: $item')!'per row')!'summarize all'")
    assert isinstance(node, Iteration)
    assert node.intent == "'per row'"
    assert node.reducer == "'summarize all'"


# --- exempt positions keep parsing ---------------------------------------------------


def test_intent_bearing_group_still_parses() -> None:
    node = build("(a, b)!'combine'")
    assert isinstance(node, Expression)
    assert node.intent is not None


def test_broadcast_group_still_parses() -> None:
    node = build("(a, b)!*'each'")
    assert isinstance(node, Expression)
    assert node.broadcast is True


def test_paren_collection_is_still_legal_without_an_intent() -> None:
    # paren-collection — "(" elements ")" followed by "*(" — is its own
    # production, disambiguated by lookahead; it never carries an intent.
    node = build("(a, b)*('row: $item')!'per row'")
    assert isinstance(node, Iteration)
    assert isinstance(node.collection, Expression)
    assert node.collection.intent is None


def test_structured_weight_and_budget_parens_are_unaffected() -> None:
    from url4.core.grammar import parse

    assert parse("name:(medical:0.9,legal:0.5):src=https://x") is not None
    assert parse("name:budget=(scope:(domain:5)):src=https://x") is not None


def test_fragment_roots_stay_accepted() -> None:
    # Owner decision 2: a lone non-parenthesized source is an API convenience,
    # not a paren group.
    assert build("https://x") is not None
    assert build("a=https://x") is not None


def test_empty_source_list_with_intent_still_parses() -> None:
    # The reduce sub-request wire shape `q=()!<input>` must keep working.
    assert build("()!'reduce this'") is not None


# --- execution of still-legal forms is unchanged -------------------------------------


def test_all_binding_interpolation_still_executes() -> None:
    # `OME-534`: the name-only source both interpolates into the intent AND
    # contributes to the packed context as a labeled line.
    from url4.dag import run

    result = asyncio.run(run("(x='value')!'got $x'", StaticIOLayer()))
    assert result == "got value\n\nx: value"


def test_processor_expression_form_still_resolves_via_bindings() -> None:
    # The strict-legal Form-3 processor expression: all-binding sources make
    # the intent pure interpolation, so the expression evaluates without
    # needing a processor of its own.
    from url4.dag import run

    io = StaticIOLayer(
        routes={
            "/claude": lambda context, intent: f"claude:{intent}",
            "/gpt4": lambda context, intent: f"gpt4:{intent}",
        }
    )
    result = asyncio.run(
        run("(/claude(a)!x, /gpt4(b)!y)!combine", io, processor="(p:0:'/gpt4')!'$p'")
    )
    assert result.startswith("gpt4:")


# --- builders and render enforce the same rule ---------------------------------------


def test_expr_builder_requires_an_intent() -> None:
    with pytest.raises(ValueError, match="intent"):
        expr("a", "b")


def test_iterate_builder_requires_an_intent() -> None:
    with pytest.raises(ValueError, match="intent"):
        iterate(["a", "b"], "'row: $item'")


def test_render_rejects_an_intent_less_expression() -> None:
    with pytest.raises(RenderError, match="intent"):
        render(Expression(sources=(Text("a"), Text("b"))))


def test_render_rejects_an_intent_less_iteration() -> None:
    with pytest.raises(RenderError, match="intent"):
        render(Iteration(collection=Text("'a'"), body="'row: $item'"))


def test_render_collection_rejects_broadcast_and_params() -> None:
    # A paren-collection is the ONE surface position for an intent-less
    # Expression — but it carries no broadcast flag or params, so a hand-built
    # collection smuggling either has no faithful text.
    bad = Iteration(
        collection=Expression(sources=(Text("a"),), params=(("quorum", "2"),)),
        body="'row: $item'",
        intent="'p'",
    )
    with pytest.raises(RenderError, match="paren-collection"):
        render(bad)


def test_render_of_legal_forms_still_round_trips() -> None:
    # render is canonicalizing (bare text is quoted), so compare parse trees.
    node = build("(a, b)!'combine'")
    assert build(render(node)) == node
