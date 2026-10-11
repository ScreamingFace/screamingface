"""Minimal counterexamples from the F4 audit, pinned as the DESIRED property.

Each test asserts what should hold; `xfail(strict=True)` records that it fails today, so
the pin turns into an XPASS failure the moment a fix lands (then drop the marker).
Run: pytest -q tests/test_findings_pins.py
"""

from __future__ import annotations

import asyncio
import warnings

import pytest
from test_lowering_equiv import EchoIO, observe

from url4 import build, render, src, text
from url4.core.errors import ParseError, RenderError
from url4.core.nodes import Binding, Expression, SelfRef

warnings.simplefilter("ignore", DeprecationWarning)
X = pytest.mark.xfail(strict=True)


# F1 — non-ParseError crash on malformed text (grammar.py:223, `_is_value_shaped("")`)
@X
@pytest.mark.parametrize("s", ["a:", "0:", "(x, a:)!go", "a:0.5:"])
def test_F1_build_raises_only_parse_error(s):
    with pytest.raises(ParseError):
        build(s)


# F2 — top-level/nested-thunk `*(` read as iteration over an EMPTY collection, not expansion
@X
def test_F2_leading_star_group_is_expansion_like_in_a_group():
    top = build("*(https://a, https://b)!go")
    nested = build("(x, *(https://a, https://b)!go)!r").sources[1]
    assert top == Expression(sources=(nested,))


# F3 — text path vs AST path disagree on `/p(x)!a!b` (and grammar reads a third way)
@X
def test_F3_call_chain_paths_agree():
    assert observe("/p(x)!a!b") == observe(build("/p(x)!a!b"))


# F4 — `;broadcast` on a nested expression: grammar keeps it as a param, envelope folds it
@X
def test_F4_nested_broadcast_flag_paths_agree():
    s = "(()!'h';broadcast)!'t'"
    assert observe(s) == observe(build(s))


# F5 — `src=(group)!i` binds a name on the text path only (_GROUP_BINDING_RE vs grammar)
@X
def test_F5_src_prefix_group_paths_agree():
    s = "(src=(https://a.io)!'i', $src)!'k'"
    assert observe(s) == observe(build(s))


# F6 — render is not total on build's image
@X
@pytest.mark.parametrize("s", ["(https://a.io)!sum\nit", "(a)!go;note='a b'", "@", "/p?a=(1)", "()!()!@;broadcast"])
def test_F6_render_total_on_build_image(s):
    render(build(s))


# F7 — render(check=False) silently misreads builder output (front doors skip verify)
@X
@pytest.mark.parametrize(
    "node",
    [src("https://x.io", mode="a!b"), src("https://x.io", annotations=[("expand", None)]), Binding("src", SelfRef(), "=")],
)
def test_F7_unchecked_render_is_faithful_or_loud(node):
    s = render(node, check=False)
    try:
        t = build(s)
    except ParseError:
        return  # loud: _blaming_render re-attributes it
    assert t == Expression(sources=(node,))


# F8 — builders.py INVARIANT "every node a builder returns is accepted by render"
@X
@pytest.mark.parametrize("mk", [lambda: text("a\nb"), lambda: src("https://x", name="a", weight=float("inf"))])
def test_F8_builder_output_renders(mk):
    render(mk())


# F9 — canonical-form call at top level is rejected though the sugar form is accepted
@X
def test_F9_top_level_canonical_call_parses():
    assert build("/p?t=90&q=(x)!go") is not None
