"""B3 / D-3: ``render(check=False)`` is faithful or loud (audit 2026-10-09, law L3s).

The front doors (``Client.evaluate``, ``Url4Node.evaluate``) render caller trees
WITHOUT the re-parse check. Before the guards, 26 classes of builder/AST trees
rendered to text that re-parsed as a DIFFERENT expression and ran with no error
(``src("https://x.io", mode="a!b")`` ran as ``mode=a`` with intent ``b``).

Faithful or loud: render raises ``RenderError``, or the text re-parses to the
same tree, or it fails to parse (``ParseError`` — the front door then re-blames
the tree via ``verify``). Never a silent misreading.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings

from url4 import build, render, src
from url4.core.errors import ParseError, RenderError
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    RemoteExpr,
    SelfRef,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)
from url4.io.static import StaticIOLayer
from url4.peer.client import Client
from url4.peer.server import Url4Node

from ._render_strategies import asts


def _wrap(node: Node) -> Node:
    return node if isinstance(node, (Expression, Iteration)) else Expression(sources=(node,))


def _assert_faithful_or_loud(node: Node) -> None:
    try:
        text = render(node, check=False)
    except RenderError:
        return
    try:
        reparsed = build(text)
    except ParseError:
        return
    assert reparsed == _wrap(node), f"{node!r} renders as {text!r}, which runs as {reparsed!r}"


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    database=None,
)
@given(asts)
def test_unchecked_render_is_faithful_or_loud(node: Node) -> None:
    _assert_faithful_or_loud(node)


# One witness per root cause in report §4.B (B3 + B-record, "silent-misreading root causes").
_ROOT_CAUSE_WITNESSES = {
    # `!` in a param, query or annotation value
    "bang_in_annotation_value": src("https://x.io", mode="a!b"),
    "bang_in_exec_flag_value": Source(
        value=IdentityRef("emily"), annotations=(("optional", "x!y"),)
    ),
    "bang_in_query_param": RelExpr("/p", "x", Text("i"), params=(("mode", "x!y"),)),
    "bang_in_remote_query_param": RemoteExpr(
        "node.ai", "/a-b.c~", "a", RelUrl("/r"), params=(("x2", "x!y"),)
    ),
    # binding names not validated
    "src_binding_name": Binding("src", SelfRef(), "="),
    "non_ascii_binding_name": Binding("é", SelfRef(), "="),
    "colon_binding_double_slash": Binding("topic", RelExpr("//", None, Text("i")), ":"),
    # reserved `expand` as an annotation
    "expand_flag_annotation": src("https://x.io", annotations=[("expand", None)]),
    "expand_valued_annotation": Source(
        value=SelfRef(), name="a", annotations=(("expand", "agent"),)
    ),
    # nested intent params hoisted
    "nested_intent_params": Expression(
        (), Expression((StructObject("{k: 'v'}"),), RelUrl("/r"), params=(("quorum", "1"),))
    ),
    # top-level bare Source around an expression loses its wrapper
    "top_source_around_expression": Source(
        value=Expression((Text("a"),), Text("b")), annotations=(("mode", "agent"),)
    ),
    # relative URL / URL intent with `!`, unbalanced `(` or `*(`
    "relurl_intent_bang": RelExpr("/", None, RelUrl("/.-!!=/")),
    "relurl_intent_unbalanced": Expression((), RelUrl("/(!,:"), params=(("mode", None),)),
    "relurl_intent_iteration_star": Expression((Expression((), RelUrl("/*)*(")),), Text("o")),
    "url_intent_comma_nested": Expression((Expression((), Url("https://h.io/,&")),), Text("o")),
    "url_intent_bang_of_top_call": RelExpr("/p", None, Url("https://h.io/!")),
    # relative call with a group intent at top level
    "top_call_group_intent": RelExpr("/p", None, Expression((), Text(""))),
    # intent_atom turns an unparseable intent into Text
    "unparseable_structured_intent": Expression(
        (), Expression((StructObject("{k: 'v'}"), RelUrl("/"), SelfRef()), RelUrl("/"))
    ),
    # identity-reference collection outside the grammar's path-segment class
    "identity_intent_bad_collection": Expression((), IdentityRef("emily", "x#y")),
    "identity_intent_of_call": RelExpr("/p", None, IdentityRef("9", "x#y")),
    # Unicode digits accepted by str.isdigit in VarRef names
    "unicode_digit_varref": VarRef("١"),
    # `*()` read as an iteration
    "broadcast_group_intent": Expression((), Expression((), SelfRef()), broadcast=True),
    # whitespace normalization of the iteration intent
    "iteration_intent_whitespace": Iteration(SelfRef(), "a, b", " go", None),
    "iteration_reducer_whitespace": Iteration(SelfRef(), "a, b", "go", " go"),
}


@pytest.mark.parametrize(
    "node", list(_ROOT_CAUSE_WITNESSES.values()), ids=list(_ROOT_CAUSE_WITNESSES)
)
def test_root_cause_witness_is_faithful_or_loud(node: Node) -> None:
    _assert_faithful_or_loud(node)


def test_colon_binding_with_double_slash_value_round_trips() -> None:
    # `topic://…` would be one bare URI; the `src=` data binding keeps the name.
    node = Expression((Binding("topic", RelExpr("//", None, Text("i")), ":"),), Text("o"))
    assert render(node, check=False) == "(topic:src=//()!'i')!'o'"
    assert build(render(node, check=False)) == node


# Before the guards this tree ran as a plain fetch of https://x.io and returned "X".
_MISREAD_AT_THE_FRONT_DOOR = Binding("src", Url("https://x.io"), "=")


@pytest.mark.asyncio
async def test_node_front_door_refuses_a_tree_it_would_misread() -> None:
    node = Url4Node(outbound=StaticIOLayer(fetch_map={"https://x.io": "X"}))
    with pytest.raises(RenderError):
        await node.evaluate(_MISREAD_AT_THE_FRONT_DOOR)


@pytest.mark.asyncio
async def test_client_front_door_refuses_a_tree_it_would_misread() -> None:
    client = Client(StaticIOLayer(fetch_map={"https://x.io": "X"}))
    with pytest.raises(RenderError):
        await client.evaluate(_MISREAD_AT_THE_FRONT_DOOR)
