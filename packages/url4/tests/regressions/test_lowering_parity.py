"""Audit B1, B4, B5, B7 — the text path and the parse-tree path read one expression one way.

`run(text)` lowers the surface text lazily; `run(build(text))` lowers the eager
parse tree. Both must classify every source the way the grammar does (Spec B §8),
so both runs give one result, or both refuse the text. Report:
docs/spec/2026-10-09-url4-audit/report.md §4.B (B1, B4, B5, B7).
"""

from __future__ import annotations

import asyncio

import pytest

from url4 import build, render
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
