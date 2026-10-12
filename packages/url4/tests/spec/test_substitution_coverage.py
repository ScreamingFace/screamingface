"""`OME-505` — every Text source binding reaches `substitute_env_vars`.

# FEATURE: `$name` interpolation and the `$$` literal-dollar escape mean the same
# thing wherever a literal lands — a source position, a binding, or a template.
#
# INVARIANT: the `$$` escape (§6.2) is resolved at SUBSTITUTION time, not lexing
# time. That is only coherent if EVERY path a literal `Text` can take to a backend
# passes through substitution; otherwise `$$` would behave differently in a source
# position than in an intent template. `compiler._lower_text` lowers every `Text`
# to a `TextNode` whose `resolve` calls `_substitute`, and `_lower_binding` routes
# its value through the same registry — so the property holds by construction.
#
# AIDEV-NOTE: these are characterization tests. The audit that produced `OME-505`
# could not confirm the BINDING sub-case; it is confirmed here. If a future lowering
# sends some Text down a path that skips `_substitute`, these fail — which is the
# entire point of pinning it.
"""

from __future__ import annotations

import asyncio

import pytest

from url4.dag import run
from url4.io.static import StaticIOLayer

_ECHO_IO = StaticIOLayer(routes={"/echo": lambda context, intent: context})


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        # `OME-508`: every group carries an intent; `OME-534`: the weight-0.0
        # instrumental descriptor keeps these substitution pins processor-free
        # and out of the packed context (name-only forms now contribute).
        pytest.param("(v:0:'$$literal')!'$v'", "$literal", id="bare-text-source"),
        pytest.param("(v:0:'cost: $$5')!'$v'", "cost: $5", id="escape-before-digit"),
        pytest.param("(x:0:'$$lit')!'$x'", "$lit", id="named-binding"),
        pytest.param("(name:0.0:'$$w')!'$name'", "$w", id="colon-bound-descriptor"),
        pytest.param("(v:0:'a $$b c')!'$v'", "a $b c", id="mid-text"),
    ],
)
def test_dollar_escape_collapses_in_every_text_source_position(
    expression: str, expected: str
) -> None:
    assert asyncio.run(run(expression, _ECHO_IO)) == expected


def test_dollar_escape_collapses_inside_a_relative_expression_context() -> None:
    # The sub-case the audit could not confirm: a Text landing in a rel-expr
    # context rather than an intent/path template.
    # `OME-535`: the context is a resolved source-list — quotes are
    # delimiters, so the echoed value is the unquoted, $$-collapsed text.
    assert asyncio.run(run("(r:0:/echo('$$x')!go)!'$r'", _ECHO_IO)) == "$x"
