"""`OME-508` cycle 2 — mandatory intent on relative and remote expressions.

# FEATURE: all four expression-bearing call productions carry `intent-op
# intent`, so a call that dispatches to a processor always says what to do.
#
#   relative-expr-sugar     = "/" path "(" source-list ")" intent-op intent […]
#   relative-expr-canonical = "/" path "?" rel-query-params "q=" expression
#   remote-expr-sugar       = "url4://" authority "/" path "(" … ")" intent-op intent
#   remote-expr-canonical   = "url4://" authority "/" path "?" … "q=" expression
#
# The canonical pair inherit the requirement by taking a full `expression`
# after `q=` (whose own intent cycle 1 made mandatory).
#
# INVARIANT: `relative-uri` is a DIFFERENT production — a plain data fetch
# (`/path`, `/path?a=1`, `/data/$topic`) carries no intent and is untouched.
# The discriminator is exactly what the parser already uses: a `(` context or
# a depth-0 `q=(` makes it expression-bearing.
"""

from __future__ import annotations

import asyncio

import pytest

from url4.core.errors import ParseError, RenderError
from url4.core.grammar import parse
from url4.core.nodes import RelExpr, RelUrl, Text, Url
from url4.core.parser import build
from url4.core.render import render
from url4.io.static import StaticIOLayer

# --- relative expressions ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "(/path(ctx))!'x'",  # sugar, nested
        "(/path?q=(ctx))!'x'",  # canonical, nested
        "(/path?t=1&q=(ctx))!'x'",  # canonical with params
        "(/path())!'x'",  # empty context, no intent
        "(a=/path(ctx))!'x'",  # as a binding value
        "(n:0.5:/path(ctx))!'x'",  # as a descriptored source
    ],
)
def test_relative_call_without_intent_is_rejected(text: str) -> None:
    with pytest.raises(ParseError, match="intent"):
        build(text)


def test_relative_call_at_fragment_root_without_intent_is_rejected() -> None:
    # The fragment-root convenience exempts the ROOT from being a full
    # `(…)!intent` group; it does not exempt a source from its own production.
    with pytest.raises(ParseError, match="intent"):
        build("/path(ctx)")


@pytest.mark.parametrize(
    "text",
    [
        "(/path(ctx)!'i')!'x'",
        "(/path?q=(ctx)!'i')!'x'",
        "(/path?t=1&q=(ctx)!'i')!'x'",
        "(/path()!'i')!'x'",
    ],
)
def test_relative_call_with_intent_still_parses(text: str) -> None:
    assert build(text) is not None


# --- remote expressions --------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "(url4://h/v1(ctx))!'x'",
        "(url4://h/v1?q=(ctx))!'x'",
        "(url4://h/v1?quorum=2&q=(ctx))!'x'",
    ],
)
def test_remote_call_without_intent_is_rejected(text: str) -> None:
    with pytest.raises(ParseError, match="intent"):
        build(text)


@pytest.mark.parametrize(
    "text",
    [
        "(url4://h/v1(ctx)!'i')!'x'",
        "(url4://h/v1?q=(ctx)!'i')!'x'",
    ],
)
def test_remote_call_with_intent_still_parses(text: str) -> None:
    assert build(text) is not None


# --- relative-uri (data fetch) is a different production and is untouched -------------


@pytest.mark.parametrize(
    "text",
    ["/path", "/path?a=1", "/data/$topic", "/api/patient/42", "/api/search?q=hello&limit=10"],
)
def test_relative_uri_data_fetch_needs_no_intent(text: str) -> None:
    # No "(" context and no depth-0 "q=(" → `relative-uri`, not an expression.
    assert isinstance(parse(text), RelUrl)


def test_bare_remote_reference_needs_no_intent() -> None:
    assert isinstance(parse("url4://registry.ai/nodes"), Url)


def test_rewind_rule_still_yields_a_data_uri() -> None:
    # §8 parse rule 16 — a "?" whose query has no `q=(` rewinds to relative-uri.
    assert isinstance(parse("/api/search?limit=10&sort=asc"), RelUrl)


# --- the wire's context-only sub-request is unaffected --------------------------------


def test_context_only_wire_subrequest_still_round_trips() -> None:
    # INVARIANT: `encode_subrequest(path, ctx, intent=None)` builds `/p?q=(ctx)`
    # — a WIRE artifact decoded by `decode_subrequest`, never re-parsed by the
    # grammar. The intent rule must not reach it.
    from url4.wire.subrequest import decode_subrequest, encode_subrequest

    target = encode_subrequest("/p", "hello", None)
    assert target == "/p?q=(hello)"
    assert decode_subrequest(target.partition("?q=")[2]) == ("hello", "")


def test_context_only_dispatch_still_executes() -> None:
    from url4.dag import run

    io = StaticIOLayer(routes={"/echo": lambda context, intent: f"{context}|{intent}"})
    assert asyncio.run(run("(/echo(hi)!there)!'outer'", io))


# --- render enforces the inverse -------------------------------------------------------


def test_render_rejects_an_intent_less_relexpr() -> None:
    with pytest.raises(RenderError, match="intent"):
        render(RelExpr(path="/claude", context="https://x"))


def test_render_rejects_an_intent_less_remoteexpr() -> None:
    from url4.core.nodes import RemoteExpr

    with pytest.raises(RenderError, match="intent"):
        render(RemoteExpr(authority="node.ai", path="/v1", context="https://x"))


def test_render_of_a_call_with_intent_still_round_trips() -> None:
    from url4.core.nodes import Expression

    node = Expression(
        sources=(RelExpr(path="/claude", context="https://x", intent=Text("go")),),
        intent=Text("outer"),
    )
    assert build(render(node)) == node
