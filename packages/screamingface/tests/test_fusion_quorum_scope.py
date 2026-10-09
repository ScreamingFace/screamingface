"""Composed quorum Recipes dispatch resolved upstream answers, never bindings."""

import json
from typing import Literal

import pytest
from url4 import ResolutionError
from url4.core.context import Context
from url4.dag import ExecutionContext, run
from url4.io.static import RouteHandler, StaticIOLayer

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate


@pytest.mark.asyncio
@pytest.mark.parametrize("quorum", [1, 2, "all"])
async def test_pipeline_quorum_members_receive_the_previous_answer(
    quorum: int | Literal["all"],
) -> None:
    calls: list[tuple[str, str]] = []

    def draft(context: str, intent: str) -> str:
        calls.append(("draft", context))
        return "DRAFT"

    def member(context: str, intent: str) -> str:
        calls.append(("member", context))
        return "ANSWER"

    def synth(context: str, intent: str) -> str:
        assert json.loads(context)["input"] == "DRAFT"
        return "FINAL"

    recipe = sf.Pipeline(
        [
            "draft",
            sf.Fusion(["a", sf.Model("b", optional=True)], synthesizer="synth", quorum=quorum),
        ]
    )
    ctx = ExecutionContext(
        io=StaticIOLayer(routes={"/draft": draft, "/a": member, "/b": member, "/synth": synth}),
        scope=Context(bindings={"input": "QUESTION"}),
    )
    assert await run(compile_candidate(recipe).url4, ctx=ctx) == "FINAL"
    assert calls == [("draft", "QUESTION"), ("member", "DRAFT"), ("member", "DRAFT")]


@pytest.mark.asyncio
async def test_quorum_fusion_synthesizer_receives_resolved_outer_panel() -> None:
    seen: list[dict] = []

    def inner_member(context: str, intent: str) -> str:
        seen.append(json.loads(context))
        return "B"

    recipe = sf.Fusion(
        ["a"],
        synthesizer=sf.Fusion([sf.Model("b", optional=True)], synthesizer="inner", quorum=1),
        quorum=1,
    )
    routes: dict[str, RouteHandler] = {
        "/a": lambda c, i: "A",
        "/b": inner_member,
        "/inner": lambda c, i: "FINAL",
    }
    ctx = ExecutionContext(io=StaticIOLayer(routes=routes), scope=Context(bindings={"input": "Q"}))
    assert await run(compile_candidate(recipe).url4, ctx=ctx) == "FINAL"
    assert seen == [{"input": "Q", "outputs": "member_1: A"}]


@pytest.mark.asyncio
async def test_captured_pipeline_input_does_not_satisfy_member_quorum() -> None:
    seen: list[str] = []

    def member(context: str, intent: str) -> str:
        assert context == "DRAFT"
        return "A"

    def synth(context: str, intent: str) -> str:
        seen.append(context)
        return "FINAL"

    recipe = sf.Pipeline(
        [
            "draft",
            sf.Fusion(["a", sf.Model("missing", optional=True)], synthesizer="synth", quorum=2),
        ]
    )
    routes: dict[str, RouteHandler] = {
        "/draft": lambda c, i: "DRAFT",
        "/a": member,
        "/synth": synth,
    }
    ctx = ExecutionContext(io=StaticIOLayer(routes=routes), scope=Context(bindings={"input": "Q"}))
    with pytest.raises(ResolutionError, match="quorum"):
        await run(compile_candidate(recipe).url4, ctx=ctx)
    assert seen == []
