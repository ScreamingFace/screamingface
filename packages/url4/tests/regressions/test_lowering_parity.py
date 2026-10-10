"""Audit B1, B4, B5, B7 — the text path and the parse-tree path read one expression one way.

`run(text)` lowers the surface text lazily; `run(build(text))` lowers the eager
parse tree. Both must classify every source the way the grammar does (Spec B §8),
so both runs give one result, or both refuse the text. Report:
docs/spec/2026-10-09-url4-audit/report.md §4.B (B1, B4, B5, B7).
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from url4 import build, render
from url4.core._call_head import is_call_head
from url4.core.errors import ParseError
from url4.core.grammar import parse
from url4.core.nodes import Expression, RelExpr, RemoteExpr, Text
from url4.dag import run
from url4.io.static import StaticIOLayer

FETCHES = {"https://a.io": "AIO", "https://x/a": "A", "https://x/b": "B"}


def _io() -> StaticIOLayer:
    return StaticIOLayer(fetch_map=FETCHES, routes={"/p": lambda c, i: f"P[{c}|{i}]"})


def _both(text: str) -> tuple[str, str]:
    """The text-path result and the parse-tree-path result of one expression."""
    lazy = asyncio.run(run(text, _io()))
    eager = asyncio.run(run(build(text), _io()))
    return lazy, eager


# --- B7: a canonical-form call is a call at top level (Spec B §8 rules 7a/7c) ------------


@pytest.mark.parametrize(
    ("canonical", "sugar"),
    [
        ("/p?q=(x)!go", "/p(x)!go"),
        ("/p?t=90&q=(x)!go", "/p(x)!go"),
    ],
)
def test_B7_top_level_canonical_call_is_the_sugar_call(canonical: str, sugar: str) -> None:
    tree = build(canonical)
    assert isinstance(tree, Expression) and tree.intent is None
    (call,) = tree.sources
    assert isinstance(call, RelExpr)
    assert (call.path, call.context, call.intent) == ("/p", "x", Text("go"))
    assert _both(canonical) == _both(sugar) == ("P[x|go]", "P[x|go]")


def _only_source(text: str) -> object:
    tree = build(text)
    assert isinstance(tree, Expression)
    (source,) = tree.sources
    return source


def test_B7_canonical_call_keeps_its_query_params() -> None:
    call = _only_source("/p?t=90&q=(x)!go")
    assert isinstance(call, RelExpr)
    assert call.params == (("t", "90"),)


def test_B7_remote_canonical_call_is_a_call() -> None:
    call = _only_source("url4://h.io/p?q=(x)!go")
    assert isinstance(call, RemoteExpr)
    assert (call.authority, call.path, call.intent) == ("h.io", "/p", Text("go"))


class _RecordingIO:
    """Records every fetch target; answers each one with a fixed body."""

    def __init__(self) -> None:
        self.targets: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.targets.append(target)
        return "OUT"


@pytest.mark.parametrize(
    ("text", "sent"),
    [
        ("/p?t=90&q=(x)!go", "/p?t=90&q=(x)!go"),
        ("url4://h.io/p?t=1&q=(x)!go", "url4://h.io/p?t=1&q=(x)!go"),
    ],
)
def test_B7_canonical_params_reach_the_request(text: str, sent: str) -> None:
    for target in (text, build(text)):
        io = _RecordingIO()
        assert asyncio.run(run(target, io=io)) == "OUT"
        assert io.targets == [sent]


def test_B7_remote_canonical_call_keeps_its_query_params() -> None:
    call = _only_source("url4://h.io/p?t=1&q=(x)!go")
    assert isinstance(call, RemoteExpr)
    assert call.params == (("t", "1"),)


@pytest.mark.parametrize(
    ("text", "processor"),
    [
        ("/p?processor=(a)&q=(x)!go", "(a)"),
        ("/p?processor=(/x?a=1&q=(y)!z)&q=(x)!go", "(/x?a=1&q=(y)!z)"),
    ],
)
def test_B7_a_parenthesized_param_does_not_take_the_calls_bang(text: str, processor: str) -> None:
    # The depth-0 group that closes right before the '!' is the q=( context, not
    # the first group: the call keeps its intent and its processor= value.
    call = _only_source(text)
    assert isinstance(call, RelExpr)
    assert (call.context, call.intent, call.params) == (
        "x",
        Text("go"),
        (("processor", processor),),
    )


def test_B7_the_q_expression_is_the_last_query_param() -> None:
    # Spec B §8: `query-string = *( query-param "&" ) "q=" expression-body` — q= is
    # last, so text after the intent is part of the intent, not another param.
    call = _only_source("/p?q=(x)!go&t=1")
    assert isinstance(call, RelExpr)
    assert (call.intent, call.params) == (Text("go&t=1"), ())


_HEAD = st.lists(
    st.sampled_from(
        [
            "/",
            "p",
            "a",
            ".",
            "?",
            "q=",
            "t=1",
            "&",
            "(a)",
            "url4://",
            "h.io",
            ":",
            "x",
            "processor=",
        ]
    ),
    max_size=8,
).map("".join)


@settings(max_examples=400, deadline=None)
@given(head=_HEAD)
def test_B7_is_call_head_agrees_with_the_grammar(head: str) -> None:
    # One owner decides "is this a call head"; the grammar must read the same
    # text as a call exactly when the splitter's question says so.
    try:
        node = parse(head + "(x)!go")
    except ParseError:
        node = None
    is_call = isinstance(node, (RelExpr, RemoteExpr))
    if is_call_head(head):
        assert node is None or (is_call and node.context == "x" and node.intent == Text("go"))
    else:
        assert not is_call


def test_B7_a_query_without_q_is_still_a_data_uri() -> None:
    # Spec B §8 rule 16: no `q=(` in the query → the rewind rule, a relative URI.
    tree = build("/api?limit=10!go")
    assert isinstance(tree, Expression) and tree.intent == Text("go")


@pytest.mark.parametrize(
    "outer",
    [
        "(/p?t=90&q=(x)!go)!r",
        # The engine's judge-call shape: query params, a quote and U+2028 in
        # the context and the intent (draco/variant.py renders it with check=False).
        "(/openrouter/m?web_search=false&max_tokens=5&q=('it\\'s', 'a\u2028b')!'judge\u2028it')!r",
        "(url4://h.io/p?t=1&q=('q')!'i')!r",
    ],
)
def test_B7_render_round_trips_a_canonical_call_with_params(outer: str) -> None:
    call = _only_source(outer)
    assert isinstance(call, (RelExpr, RemoteExpr)) and call.params
    text = render(call, check=False)
    assert parse(text) == call
    assert _only_source(text) == call


# --- B1 / D-1b: a chained intent is a parse error on every path (Spec B §8) ------------
# `bare-value` stops at an unquoted `!`, and nothing may follow an intent but `;` params.
# A call carries its own intent, so `/p(x)!a!b` has no reading: wrap the call in a
# group, `(/p(x)!a)!b`, to process its result.

CHAINED = [
    "/p(x)!a!b",
    "/p(x)!go!r",
    "/p?q=(x)!go!r",
    "/p(x)!'a'!'b'",
    "/p(x)!a;t=5!b",
    "/p?q=(x)!a!b",
    "url4://h.io/p(x)!a!b",
    "(/p(x)!a!b, 'c')!k",
    "('a')!b!c",
    "https://a.io!b!c",
    "https://a.io*(/p($item)!a)!b!c",
    "(https://a.io*(/p($item)!a)!b)!r!s",
]


@pytest.mark.parametrize("text", CHAINED)
def test_B1_chained_intent_is_a_parse_error_on_build(text: str) -> None:
    with pytest.raises(ParseError):
        build(text)


@pytest.mark.parametrize("text", CHAINED)
def test_B1_chained_intent_is_a_parse_error_on_the_text_path(text: str) -> None:
    with pytest.raises(ParseError):
        asyncio.run(run(text, _io()))


@pytest.mark.parametrize(
    "text", ["/p(x)!go!r", "/p?q=(x)!go!r", "/p?t=1&q=(x)!go!r", "url4://h.io/p(x)!go!r"]
)
def test_B1_chained_call_intent_is_a_parse_error_in_the_grammar(text: str) -> None:
    # The third reading the audit found: grammar.parse took the intent 'go!r'.
    with pytest.raises(ParseError):
        parse(text)


def test_B1_a_grouped_call_is_processed_on_both_paths_alike() -> None:
    lazy, eager = _both("(/p(x)!a)!b")
    assert lazy == eager == "P[|[Response 1]\nP[x|a]\n\n[Instruction]\nb]"


@pytest.mark.parametrize("text", ["('a', 'b')!('c', 'd')!agg", "('a')!'b!c'"])
def test_B1_an_expression_intent_or_a_quoted_bang_is_not_a_chain(text: str) -> None:
    build(text)
    lazy, eager = _both(text)
    assert lazy == eager
