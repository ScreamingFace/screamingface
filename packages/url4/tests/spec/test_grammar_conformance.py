"""Grammar-conformance regressions for `OME-501` — duplicated productions.

# FEATURE: url4 expressions parse identically no matter which entry point reads
# them, and transport-only params never escape the node that received them.
#
# Each bug here is a production implemented or enforced in TWO places where only
# one copy was correct. The tests assert the two copies AGREE — they deliberately
# compare the implementation against its own sibling rather than against a
# hand-written expectation, so they stay honest if the shared rule later changes.
"""

from __future__ import annotations

import asyncio

import pytest

from url4.core.grammar import parse as grammar_parse
from url4.core.grammar import parse_value
from url4.core.nodes import Expression, Iteration, RelExpr, Text
from url4.core.parser import build
from url4.dag import run
from url4.io.static import StaticIOLayer

# --- Bug A: intent-bearing collections survive the envelope decode ------------------

# The six `uri-collection-ref` alternatives (ABNF §5.3). The first three carry
# their OWN mandatory intent — those are the ones `decode_envelope` destroyed by
# splitting on the first depth-0 `!` before scanning for `*(`.
_COLLECTION_SHAPES = [
    pytest.param("(a)!y*('b')!x", id="local-expr"),
    pytest.param("/rel/path(a)!y*('b')!x", id="relative-expr-sugar"),
    pytest.param("url4://node/x(a)!y*('b')!x", id="remote-expr-sugar"),
    pytest.param("'lit'*('b')!x", id="quoted-text"),
    pytest.param("/rel/path*('b')!x", id="relative-uri"),
    pytest.param("https://a.com/list*('b')!x", id="bare-value"),
]


@pytest.mark.parametrize("text", _COLLECTION_SHAPES)
def test_build_yields_an_iteration_for_every_collection_shape(text: str) -> None:
    # INVARIANT: a depth-0 `*(` makes the expression an iteration, whatever the
    # collection is — including a collection carrying its own `!intent`.
    assert isinstance(build(text), Iteration), f"{text!r} lost its iteration structure"


@pytest.mark.parametrize("text", _COLLECTION_SHAPES)
def test_build_agrees_with_the_grammar_on_every_collection_shape(text: str) -> None:
    # WHY: `grammar.parse_value` already scans for `*(` unconditionally and was
    # correct throughout; `build` is the public entry point that disagreed. The
    # two must not drift again.
    eager, direct = build(text), parse_value(text)
    assert isinstance(direct, Iteration)
    assert isinstance(eager, Iteration)
    assert eager.body == direct.body
    assert eager.intent == direct.intent
    assert type(eager.collection) is type(direct.collection)


def test_intent_bearing_collection_keeps_its_own_intent() -> None:
    node = build("(a)!y*('b')!x")
    assert isinstance(node, Iteration)
    # the collection is the local-expr `(a)!y` — its intent belongs to IT
    assert isinstance(node.collection, Expression)
    assert node.collection.intent == Text("y")
    assert node.body == "'b'"
    assert node.intent == "x"


def test_bare_star_without_paren_stays_literal_text() -> None:
    # INVARIANT: `*` is structural ONLY when immediately followed by `(`.
    node = build("abc*def*('x')!y")
    assert isinstance(node, Iteration)
    assert node.collection == Text("abc*def")


def test_empty_parenthesized_collection_still_decodes() -> None:
    node = build("()*('x')!y")
    assert isinstance(node, Iteration)
    assert isinstance(node.collection, Expression)
    assert node.collection.sources == ()


def test_reduce_over_iteration_precedence_unchanged() -> None:
    # REGRESSION: the `*(` here is INSIDE parens, so it is not at depth 0 of the
    # full text — the fix for bug A must not disturb this shape.
    node = build("(https://rows*()!'R $item')!/reduce()")
    assert isinstance(node, Iteration)
    assert node.reducer == "/reduce()"


def test_descriptored_collection_still_routes_to_the_group_parser() -> None:
    # REGRESSION: §5.3.10 — a descriptor names the ITERATION EXPRESSION, so this
    # is a group source, NOT reduce-over-iteration.
    node = build("(scores:0.0:https://data.com/records*(t=$item.answer)!/score())!'Agg $scores'")
    assert isinstance(node, Expression)


# --- Bug B: nested query params split depth-aware -----------------------------------


def test_nested_query_params_split_only_at_depth_zero() -> None:
    # An `&` inside the parenthesized `processor=` value must NOT terminate it.
    # `subrequest.extract_expression_params` already got this right via
    # `_scan.split_top_level`; the grammar path re-implemented it without depth.
    node = grammar_parse("/summarize?processor=(/x?a=1&b=2&q=(y)!z)!route&q=(article)!condense")
    assert isinstance(node, RelExpr)
    assert node.path == "/summarize"
    assert node.context == "article"
    assert node.intent == Text("condense")
    assert dict(node.params) == {"processor": "(/x?a=1&b=2&q=(y)!z)!route"}


def test_plain_nested_query_params_still_decode() -> None:
    node = grammar_parse("/summarize?tone=formal&lang=en&q=(article)!condense")
    assert isinstance(node, RelExpr)
    assert dict(node.params) == {"tone": "formal", "lang": "en"}
    assert node.context == "article"


def test_ampersand_inside_quotes_is_not_a_param_boundary() -> None:
    node = grammar_parse("/summarize?note='a&b'&q=(article)!condense")
    assert isinstance(node, RelExpr)
    assert dict(node.params) == {"note": "'a&b'"}


# --- Bug C: transport-only params never reach an outbound sub-request ---------------


class _RecordingIO:
    """An `IOLayer` that records every fetch target and returns a fixed body."""

    def __init__(self) -> None:
        self.targets: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.targets.append(target)
        return "ok"


def _run_and_capture(expression: str) -> list[str]:
    # WHY: a bare single-source group (no `!intent`) resolves its source and
    # stops — no fan-out reduce, so no processor route is needed. Keeping the
    # expression reduce-free isolates what this test is about: the outbound
    # query string.
    io = _RecordingIO()
    asyncio.run(run(expression, io))
    return io.targets


def test_transport_params_in_expression_text_never_reach_the_wire() -> None:
    # INVARIANT (spec §11.6.3): `resume` and `rid` are transport-only. They are
    # already stripped on the HTTP ingress (`server._reassemble`); an expression
    # authored with them must not smuggle them outbound either.
    targets = _run_and_capture("(r:0:/summarize?resume=1&rid=abc&q=(ctx)!go)!'$r'")
    assert targets, "expected at least one outbound fetch"
    joined = " ".join(targets)
    assert "resume" not in joined
    assert "rid=" not in joined


def test_non_transport_params_still_reach_the_wire() -> None:
    # BOUNDARY: the filter must not over-reach — ordinary protocol params survive.
    targets = _run_and_capture("(r:0:/summarize?tone=formal&q=(ctx)!go)!'$r'")
    joined = " ".join(targets)
    assert "tone=formal" in joined


def test_static_io_route_still_serves_a_relative_expression() -> None:
    # REGRESSION: the shared filter sits in the sub-request codec; the ordinary
    # route path must keep working.
    io = StaticIOLayer(routes={"/echo": lambda context, intent: f"{context}|{intent}"})
    assert asyncio.run(run("(/echo(hi)!there)!outer", io))
