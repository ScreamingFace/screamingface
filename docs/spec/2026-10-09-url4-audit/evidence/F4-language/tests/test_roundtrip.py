"""Round-trip laws for url4 render/build (F4 audit). Run: pytest -q tests/test_roundtrip.py

L1  ∀n. render(n) succeeds  ⟹ build(render(n)) == wrap(n)          (tautological given verify;
     kept as a regression guard for the check itself)
L2  ∀n. s = render(n) succeeds ⟹ render(build(s)) == s              (canonical text is a fixpoint)
L2' ∀s. build(s) succeeds ⟹ render(build(s)) succeeds               (render total on build's image)
L2i ∀s. t = render(build(s)) succeeds ⟹ render(build(t)) == t       (render∘build idempotent)
L3  ∀n. s = render(n, check=False) returns ⟹ verify(n, s) passes    (unchecked render is faithful)
L3s weaker: build(s) either raises ParseError or equals wrap(n)     (no SILENT misreading — the
     front doors only re-verify on ParseError, peer/client.py:_blaming_render)
F   ∀s. build(s) raises nothing but ParseError                       (crash fuzz)
B   ∀ builder output b. render(b) succeeds                          (builders.py module INVARIANT)
"""

from __future__ import annotations

import warnings

import pytest
from gen import asts, grammar_text, mutated_text
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from url4 import build, render
from url4.core import builders as B
from url4.core.errors import ParseError, RenderError
from url4.core.grammar import intent_atom, parse, parse_value
from url4.core.nodes import Expression, Iteration

warnings.simplefilter("ignore", DeprecationWarning)
S = settings(max_examples=3000, deadline=None, suppress_health_check=list(HealthCheck))


def wrap(n):
    return n if isinstance(n, (Expression, Iteration)) else Expression(sources=(n,))


def try_render(n, check=True):
    try:
        return render(n, check=check)
    except (RenderError, TypeError):
        return None


def try_build(s):
    try:
        return build(s)
    except ParseError:
        return None


@S
@given(asts)
def test_L1_checked_render_roundtrips(n):
    s = try_render(n)
    assume(s is not None)
    assert build(s) == wrap(n)


@S
@given(asts)
def test_L2_canonical_text_is_fixpoint(n):
    s = try_render(n)
    assume(s is not None)
    assert render(build(s)) == s


@S
@given(grammar_text)
@example("(https://a.io)!sum\nit")
@example("(a)!go;note='a b'")
def test_L2prime_render_total_on_build_image(s):
    t = try_build(s)
    assume(t is not None)
    render(t)  # must not raise


@S
@given(grammar_text)
def test_L2i_render_build_idempotent(s):
    t = try_build(s)
    assume(t is not None)
    r = try_render(t)
    assume(r is not None)
    assert render(build(r)) == r


@S
@given(asts)
def test_L3_unchecked_render_faithful(n):
    s = try_render(n, check=False)
    assume(s is not None)
    assert try_build(s) == wrap(n)


@S
@given(asts)
def test_L3s_no_silent_misreading(n):
    s = try_render(n, check=False)
    assume(s is not None)
    t = try_build(s)
    assert t is None or t == wrap(n), f"render(check=False) -> {s!r} reparses to {t!r}"


@S
@given(st.one_of(grammar_text, mutated_text(), st.text(max_size=12)))
def test_F_build_only_raises_parse_error(s):
    for f in (build, parse, parse_value, intent_atom):
        try:
            f(s)
        except ParseError:
            pass


# ------------------------------------------------------------- builder invariant
# (kind, args) pairs; the builder is called INSIDE the test so a builder that rejects its
# input (ValueError/TypeError — its documented contract) is filtered, and only a node the
# builder RETURNED is held to the module INVARIANT "accepted by render".
builder_calls = st.one_of(
    st.tuples(st.just("text"), st.text(max_size=5)),
    st.tuples(st.just("weight"), st.floats(allow_nan=True, allow_infinity=True)),
    st.tuples(st.just("mode"), st.text(max_size=4)),
    st.tuples(st.just("annot"), st.sampled_from(["expand", "t2", "x y", "ok"])),
    st.tuples(st.just("refpath"), st.one_of(st.integers(-2, 2), st.text(max_size=3))),
    st.tuples(st.just("identity"), st.tuples(st.text(max_size=3), st.one_of(st.none(), st.text(max_size=3)))),
    st.tuples(st.just("concurrency"), st.one_of(st.integers(1, 3), st.just(True))),
    st.tuples(st.just("fmt"), st.text(max_size=3)),
    st.tuples(st.just("intent"), st.text(min_size=1, max_size=5)),
    st.tuples(st.just("body"), st.text(max_size=4)),
)
CALL = {
    "text": lambda a: B.text(a),
    "weight": lambda a: B.src("https://x.io", name="a", weight=a),
    "mode": lambda a: B.src("https://x.io", mode=a),
    "annot": lambda a: B.src("https://x.io", annotations=[(a, None)]),
    "refpath": lambda a: B.ref("a", a),
    "identity": lambda a: B.identity(*a),
    "concurrency": lambda a: B.iterate("https://x.io", "$item", intent="go", concurrency=a),
    "fmt": lambda a: B.iterate("https://x.io", "$item", intent="go", fmt_result=a),
    "intent": lambda a: B.expr("https://x.io", intent=a),
    "body": lambda a: B.iterate("https://x.io", a, intent="go"),
}


@S
@given(builder_calls)
def test_B_builder_output_renders(call):
    kind, arg = call
    try:
        n = CALL[kind](arg)
    except (ValueError, TypeError, ParseError):
        assume(False)
        return
    render(n)


@pytest.mark.parametrize("kind", sorted(CALL))
@settings(max_examples=400, deadline=None, suppress_health_check=list(HealthCheck))
@given(data=st.data())
def test_B_per_builder(kind, data):
    arg = data.draw(builder_calls.filter(lambda c: c[0] == kind))[1]
    try:
        n = CALL[kind](arg)
    except (ValueError, TypeError, ParseError):
        assume(False)
        return
    render(n)
