from __future__ import annotations

import json
from typing import Any

import pytest
from url4 import ResolutionError
from url4.core.context import Context
from url4.dag import ExecutionContext, run
from url4.io.static import RouteHandler, StaticIOLayer

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate


@pytest.mark.parametrize("quorum", [None, True, False, 1.5, "2", "majority"])
def test_fusion_rejects_invalid_quorum_types(quorum: Any) -> None:
    with pytest.raises(TypeError, match="quorum"):
        _ = sx.Fanout(["a", "b"], quorum=quorum) >> sx.Synthesize("synth")


@pytest.mark.parametrize("quorum", [-1, 3])
def test_fusion_rejects_quorum_outside_member_count(quorum: int) -> None:
    with pytest.raises(ValueError, match="member count"):
        _ = sx.Fanout(["a", "b"], quorum=quorum) >> sx.Synthesize("synth")


def test_fusion_policy_is_immutable_and_visible_in_repr() -> None:
    fusion = sx.Fanout([sf.Model("a", optional=True), "b"], quorum=0) >> sx.Synthesize("synth")
    assert "quorum=0" in repr(fusion)
    assert "optional=True" in repr(_fanout(fusion).members[0])
    assert fusion != sx.Fanout(["a", "b"]) >> sx.Synthesize("synth")
    with pytest.raises(AttributeError):
        setattr(_fanout(fusion), "quorum", 1)
    with pytest.raises(TypeError, match="optional"):
        sf.Model("a", optional=1)  # type: ignore[arg-type]


def _fanout(chain: sf.Recipe) -> sx.Fanout:
    """The ``Fanout`` that opens ``chain``: it holds the members and the quorum."""

    assert isinstance(chain, sx.Pipeline)
    fanout = chain.steps[0]
    assert isinstance(fanout, sx.Fanout)
    return fanout


def _context(seen: list[dict], *, a: bool = True, b: bool = True) -> ExecutionContext:
    def synth(context: str, intent: str) -> str:
        seen.append(json.loads(context))
        return "synthesized"

    routes: dict[str, RouteHandler] = {"/synth": synth}
    if a:
        routes["/a"] = lambda c, i: 'A with "quotes", a newline\nand $references'
    if b:
        routes["/b"] = lambda c, i: "B"
    io = StaticIOLayer(routes=routes)
    return ExecutionContext(io=io, scope=Context(bindings={"input": "the question"}))


@pytest.mark.asyncio
async def test_quorum_tolerates_one_failure_and_synthesizes_successful_members() -> None:
    fusion = sx.Fanout(["a", "b", sf.Model("missing", optional=True)], quorum=2) >> sx.Synthesize(
        "synth"
    )
    seen: list[dict] = []
    assert await run(compile_candidate(fusion).url4, ctx=_context(seen)) == "synthesized"
    assert len(seen) == 1
    assert seen[0]["input"] == "the question"
    assert (
        seen[0]["outputs"] == 'member_1: A with "quotes", a newline\nand $references\nmember_2: B'
    )
    assert "$model_" not in seen[0]["outputs"]


@pytest.mark.asyncio
@pytest.mark.parametrize("quorum", [2, "all"])
async def test_unmet_quorum_prevents_synthesis(quorum: Any) -> None:
    fusion = sx.Fanout(["a", sf.Model("missing", optional=True)], quorum=quorum) >> sx.Synthesize(
        "synth"
    )
    seen: list[dict] = []
    with pytest.raises(ResolutionError) as exc:
        await run(compile_candidate(fusion).url4, ctx=_context(seen))
    assert exc.value.code == "quorum_not_met"
    assert seen == []


@pytest.mark.asyncio
async def test_zero_quorum_can_synthesize_without_successful_members() -> None:
    fusion = sx.Fanout([sf.Model("missing", optional=True)], quorum=0) >> sx.Synthesize("synth")
    seen: list[dict] = []
    assert await run(compile_candidate(fusion).url4, ctx=_context(seen)) == "synthesized"
    assert seen == [{"input": "the question", "outputs": ""}]


@pytest.mark.asyncio
async def test_required_member_failure_is_not_tolerated_by_numeric_quorum() -> None:
    fusion = sx.Fanout(["a", "missing"], quorum=1) >> sx.Synthesize("synth")
    seen: list[dict] = []
    with pytest.raises(ResolutionError):
        await run(compile_candidate(fusion).url4, ctx=_context(seen))
    assert seen == []


@pytest.mark.asyncio
async def test_optional_composite_member_failure_is_isolated() -> None:
    fusion = sx.Fanout(
        ["a", sf.Pipeline(["b", "missing"], optional=True)], quorum=1
    ) >> sx.Synthesize("synth")
    seen: list[dict] = []
    assert await run(compile_candidate(fusion).url4, ctx=_context(seen)) == "synthesized"
    assert "member_2" not in seen[0]["outputs"]
    assert "B" not in seen[0]["outputs"]


@pytest.mark.asyncio
async def test_mixed_members_still_require_the_required_member() -> None:
    fusion = sx.Fanout(
        [sf.Model("a", optional=True), sf.Model("b", optional=True), "missing"], quorum=2
    ) >> sx.Synthesize("synth")
    seen: list[dict] = []
    with pytest.raises(ResolutionError):
        await run(compile_candidate(fusion).url4, ctx=_context(seen))
    assert seen == []


@pytest.mark.asyncio
async def test_optional_nested_fusion_is_one_member() -> None:
    inner = sx.Pipeline([sx.Fanout(["b", "missing"]), sx.Synthesize("synth")], optional=True)
    outer = sx.Fanout(["a", inner], quorum=1) >> sx.Synthesize("synth")
    seen: list[dict] = []
    assert await run(compile_candidate(outer).url4, ctx=_context(seen)) == "synthesized"
    assert len(seen) == 1
    assert "member_2" not in seen[0]["outputs"]


@pytest.mark.parametrize(
    "recipe",
    [
        sf.Model("a", optional=True),
        sf.Pipeline(["a", "b"], optional=True),
        sx.Pipeline([sx.Fanout(["a", "b"]), sx.Synthesize("synth")], optional=True),
    ],
)
def test_optional_is_only_valid_in_a_fusion_member_position(recipe: sf.Recipe) -> None:
    with pytest.raises(ValueError, match="Fusion members"):
        compile_candidate(recipe)
    with pytest.raises(ValueError, match="Fusion members"):
        sf.Pipeline([recipe, "final"])
    with pytest.raises(ValueError, match="Fusion members"):
        _ = sx.Fanout(["a"]) >> sx.Synthesize(recipe)


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_optional_requires_a_boolean_on_every_member_kind(value: Any) -> None:
    with pytest.raises(TypeError, match="optional"):
        sf.Model("a", optional=value)
    with pytest.raises(TypeError, match="optional"):
        sf.Pipeline(["a"], optional=value)
    with pytest.raises(TypeError, match="optional"):
        sx.Pipeline([sx.Fanout(["a"]), sx.Synthesize("synth")], optional=value)


def test_optional_members_flag_is_removed() -> None:
    with pytest.raises(TypeError, match="optional_members"):
        sx.Fanout(["a"], optional_members=True)  # type: ignore[call-arg]


@pytest.mark.parametrize("kind", ["model", "pipeline", "fusion"])
def test_fusion_repr_distinguishes_optional_member_policy(kind: str) -> None:
    # WHY: identical printed panels hid whether a member failure stops synthesis.
    def member(optional: bool) -> sf.Recipe:
        if kind == "model":
            return sf.Model("a", optional=optional)
        if kind == "pipeline":
            return sf.Pipeline(["a", "b"], optional=optional)
        return sx.Pipeline([sx.Fanout(["a", "b"]), sx.Synthesize("inner")], optional=optional)

    optional_member = member(True)
    required_member = member(False)
    tolerant = sx.Fanout([optional_member, "c"], quorum=1) >> sx.Synthesize("s")
    required = sx.Fanout([required_member, "c"], quorum=1) >> sx.Synthesize("s")
    # WHY: a plain model member prints as its route; any other member prints its repr.
    shown = repr(required_member.name) if kind == "model" else repr(required_member)
    assert repr(tolerant) != repr(required)
    assert repr(tolerant) == f"Fanout([{optional_member!r}, 'c'], quorum=1) >> Synthesize('s')"
    assert repr(required) == f"Fanout([{shown}, 'c'], quorum=1) >> Synthesize('s')"
