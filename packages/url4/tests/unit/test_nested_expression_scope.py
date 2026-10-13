"""Nested AST groups retain the same enclosing values as lazy text groups."""

import pytest

from url4 import build
from url4.core.context import Context
from url4.dag import ExecutionContext, run
from url4.io.static import StaticIOLayer


@pytest.mark.asyncio
@pytest.mark.parametrize("as_ast", [False, True], ids=["text", "ast"])
@pytest.mark.parametrize("disposition", ["required", "optional"])
async def test_nested_panel_captures_upstream_once(as_ast: bool, disposition: str) -> None:
    # INVARIANT: scope capture must not turn shared upstream input into another
    # quorum member or re-execute its model call in each isolated subtree.
    calls: list[tuple[str, str]] = []

    def draft(context: str, intent: str) -> str:
        calls.append(("draft", context))
        return "DRAFT"

    def member(context: str, intent: str) -> str:
        calls.append(("member", context))
        return "ANSWER"

    expression = (
        "(upstream:0:/draft($input)!'draft', "
        "panel:0:(a:1:(leaf_a:0:/member($upstream)!'answer')!'$leaf_a';"
        f"{disposition}, "
        "b:1:(leaf_b:0:/member($upstream)!'answer')!'$leaf_b';required)"
        "!'';quorum=2)!'$panel'"
    )
    ctx = ExecutionContext(
        io=StaticIOLayer(routes={"/draft": draft, "/member": member}),
        scope=Context(bindings={"input": "QUESTION"}),
    )
    result = await run(build(expression) if as_ast else expression, ctx=ctx)
    assert result == "a: ANSWER\nb: ANSWER"
    assert calls == [("draft", "QUESTION"), ("member", "DRAFT"), ("member", "DRAFT")]


@pytest.mark.asyncio
@pytest.mark.parametrize("as_ast", [False, True], ids=["text", "ast"])
async def test_nested_group_intent_uses_outer_values_and_local_shadowing(as_ast: bool) -> None:
    expression = (
        "(upstream:0:'OUTER', local:0:'BEFORE', "
        "nested:0:(local:0:'INNER')!'$upstream/$local')!'$nested'"
    )
    assert await run(build(expression) if as_ast else expression, StaticIOLayer()) == "OUTER/INNER"
