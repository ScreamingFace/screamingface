"""Round-trip laws for url4 render/build (regression safety net, F4 audit).

Ported from ``evidence/F4-language/tests/test_roundtrip.py``. Only the two laws that
hold on the current code are kept as normal property tests:

L1  ∀n. render(n) succeeds  ⟹ build(render(n)) == wrap(n)
L2i ∀s. t = render(build(s)) succeeds ⟹ render(build(t)) == t   (render∘build idempotent)
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings

from url4 import build, render
from url4.core.errors import ParseError, RenderError
from url4.core.nodes import Expression, Iteration

from ._grammar_strategies import asts, grammar_text

# The laws filter with assume(), so the filter_too_much health check is suppressed.
LAW_SETTINGS = settings(
    max_examples=200, deadline=None, suppress_health_check=[HealthCheck.filter_too_much]
)


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


@LAW_SETTINGS
@given(asts)
def test_L1_checked_render_roundtrips(n):
    s = try_render(n)
    assume(s is not None)
    assert s is not None
    assert build(s) == wrap(n)


@LAW_SETTINGS
@given(grammar_text)
def test_L2i_render_build_idempotent(s):
    t = try_build(s)
    assume(t is not None)
    r = try_render(t)
    assume(r is not None)
    assert r is not None
    assert render(build(r)) == r
