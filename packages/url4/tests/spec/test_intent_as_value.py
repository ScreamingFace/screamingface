"""`OME-502` — `intent = value`, honored.

# FEATURE: an intent may be any value form, not just text — so an intent that IS
# a computation (`!(c,d)!agg`) is compiled and executed, not pasted into a prompt.
#
# WHY this matters beyond AST shape: `dag/compiler.py` dispatches lowering by node
# type. An intent flattened to `Text` lowers to a `TextNode`, so a nested expression
# is never compiled into a subgraph — its sources are never fetched and the literal
# string `"(c,d)!agg"` reaches the model. `test_nested_expression_intent_is_executed`
# is the test that actually pins that; the AST-shape tests below merely localize a
# failure when it regresses.
"""

from __future__ import annotations

import asyncio

import pytest

from url4.core.nodes import (
    Expression,
    IdentityRef,
    Iteration,
    RelUrl,
    SelfRef,
    StructObject,
    Text,
    Url,
)
from url4.core.parser import build
from url4.core.render import render
from url4.dag import run

# --- the defect that actually bites -------------------------------------------------


def test_nested_expression_intent_is_executed_not_prompted() -> None:
    # INVARIANT: an Expression in intent position is a COMPUTATION. Its sources must
    # be resolved through the I/O layer; if it were flattened to Text they would
    # never be fetched at all.
    fetched: list[str] = []

    class _Recorder:
        async def fetch(self, target: str, *, relative: bool) -> str:
            fetched.append(target)
            return "body"

    asyncio.run(run("(https://src)!(https://a, https://b)!agg", _Recorder()))
    assert "https://a" in fetched, "nested-expression intent was never compiled/executed"
    assert "https://b" in fetched


# --- AST classification of the previously-collapsed shapes --------------------------


def _intent_of(text: str):
    node = build(text)
    assert isinstance(node, Expression)
    return node.intent


@pytest.mark.parametrize(
    ("expression", "expected_type"),
    [
        pytest.param("(a,b)!(c,d)!agg", Expression, id="nested-expression"),
        pytest.param("(a,b)!{k:'v'}", StructObject, id="struct-object"),
        pytest.param("(a,b)!@", SelfRef, id="self-ref"),
        pytest.param("(a,b)!@bob", IdentityRef, id="identity-ref"),
    ],
)
def test_collapsed_intent_shapes_now_classify(expression: str, expected_type: type) -> None:
    assert isinstance(_intent_of(expression), expected_type)


def test_nested_expression_intent_keeps_its_structure() -> None:
    intent = _intent_of("(a,b)!(c,d)!agg")
    assert isinstance(intent, Expression)
    assert len(intent.sources) == 2
    assert intent.intent == Text("agg")


# --- preservation: the shapes that already worked must not move ---------------------


@pytest.mark.parametrize(
    ("expression", "expected_type"),
    [
        pytest.param("(a,b)!summarize", Text, id="bare-text"),
        pytest.param("(a,b)!'quoted intent'", Text, id="quoted-text"),
        pytest.param("(a,b)!https://x.com/i", Url, id="scheme-uri"),
        pytest.param("(a,b)!/reduce()", RelUrl, id="reducer-route"),
        pytest.param("(a,b)!/plain/path", RelUrl, id="relative-path"),
        pytest.param("(a,b)!$style", Text, id="variable-ref-stays-text"),
    ],
)
def test_existing_intent_shapes_are_unchanged(expression: str, expected_type: type) -> None:
    # AIDEV-NOTE: `/path` classifies as RelUrl — `!/reduce()` is the fan-out
    # reducer ROUTE form and is load-bearing.
    assert isinstance(_intent_of(expression), expected_type)


# --- round-trip: render must widen in lockstep with the parser ----------------------


@pytest.mark.parametrize(
    "expression",
    [
        "(a,b)!(c,d)!agg",
        "(a,b)!$style",
        "(a,b)!{k:'v'}",
        "(a,b)!@",
        "(a,b)!@bob",
        "(a,b)!summarize",
        "(a,b)!/reduce()",
    ],
)
def test_intent_round_trips_through_render(expression: str) -> None:
    # INVARIANT: render() is the inverse of build(). A widened parser with a
    # narrow renderer would make these expressions unrenderable.
    once = render(build(expression))
    assert build(once) == build(expression)
    assert render(build(once)) == once


# --- regressions the widening must not disturb --------------------------------------


def test_reduce_over_iteration_still_parses() -> None:
    node = build("(https://rows*()!'R $item')!/reduce()")
    assert isinstance(node, Iteration)
    assert node.reducer == "/reduce()"


def test_descriptored_iteration_source_still_parses() -> None:
    node = build("(scores:0.0:https://data.com/records*(t=$item.answer)!/score())!'Agg $scores'")
    assert isinstance(node, Expression)
