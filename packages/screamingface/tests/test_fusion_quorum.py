from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from url4 import ResolutionError
from url4.core.context import Context
from url4.dag import ExecutionContext, run
from url4.io.static import RouteHandler, StaticIOLayer

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate


@pytest.mark.parametrize("quorum", [None, True, False, 1.5, "2", "majority"])
def test_fusion_rejects_invalid_quorum_types(quorum: Any) -> None:
    with pytest.raises(TypeError, match="quorum"):
        _ = sf.Fanout(["a", "b"], quorum=quorum) >> sf.Synthesize("synth")


@pytest.mark.parametrize("quorum", [-1, 3])
def test_fusion_rejects_quorum_outside_member_count(quorum: int) -> None:
    with pytest.raises(ValueError, match="member count"):
        _ = sf.Fanout(["a", "b"], quorum=quorum) >> sf.Synthesize("synth")


def test_fusion_policy_is_immutable_and_visible_in_repr() -> None:
    fusion = sf.Fanout([sf.Model("a", optional=True), "b"], quorum=0) >> sf.Synthesize("synth")
    assert "quorum=0" in repr(fusion)
    assert "optional=True" in repr(_fanout(fusion).members[0])
    assert fusion != sf.Fanout(["a", "b"]) >> sf.Synthesize("synth")
    with pytest.raises(AttributeError):
        setattr(_fanout(fusion), "quorum", 1)
    with pytest.raises(TypeError, match="optional"):
        sf.Model("a", optional=1)  # type: ignore[arg-type]


def _fanout(chain: sf.Recipe) -> sf.Fanout:
    """The ``Fanout`` that opens ``chain``: it holds the members and the quorum."""

    assert isinstance(chain, sf.Pipeline)
    fanout = chain.steps[0]
    assert isinstance(fanout, sf.Fanout)
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
    fusion = sf.Fanout(["a", "b", sf.Model("missing", optional=True)], quorum=2) >> sf.Synthesize(
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
    fusion = sf.Fanout(["a", sf.Model("missing", optional=True)], quorum=quorum) >> sf.Synthesize(
        "synth"
    )
    seen: list[dict] = []
    with pytest.raises(ResolutionError) as exc:
        await run(compile_candidate(fusion).url4, ctx=_context(seen))
    assert exc.value.code == "quorum_not_met"
    assert seen == []


@pytest.mark.asyncio
async def test_zero_quorum_can_synthesize_without_successful_members() -> None:
    fusion = sf.Fanout([sf.Model("missing", optional=True)], quorum=0) >> sf.Synthesize("synth")
    seen: list[dict] = []
    assert await run(compile_candidate(fusion).url4, ctx=_context(seen)) == "synthesized"
    assert seen == [{"input": "the question", "outputs": ""}]


@pytest.mark.asyncio
async def test_required_member_failure_is_not_tolerated_by_numeric_quorum() -> None:
    fusion = sf.Fanout(["a", "missing"], quorum=1) >> sf.Synthesize("synth")
    seen: list[dict] = []
    with pytest.raises(ResolutionError):
        await run(compile_candidate(fusion).url4, ctx=_context(seen))
    assert seen == []


@pytest.mark.asyncio
async def test_optional_composite_member_failure_is_isolated() -> None:
    fusion = sf.Fanout(
        ["a", sf.Pipeline(["b", "missing"], optional=True)], quorum=1
    ) >> sf.Synthesize("synth")
    seen: list[dict] = []
    assert await run(compile_candidate(fusion).url4, ctx=_context(seen)) == "synthesized"
    assert "member_2" not in seen[0]["outputs"]
    assert "B" not in seen[0]["outputs"]


@pytest.mark.asyncio
async def test_mixed_members_still_require_the_required_member() -> None:
    fusion = sf.Fanout(
        [sf.Model("a", optional=True), sf.Model("b", optional=True), "missing"], quorum=2
    ) >> sf.Synthesize("synth")
    seen: list[dict] = []
    with pytest.raises(ResolutionError):
        await run(compile_candidate(fusion).url4, ctx=_context(seen))
    assert seen == []


@pytest.mark.asyncio
async def test_optional_nested_fusion_is_one_member() -> None:
    inner = sf.Pipeline([sf.Fanout(["b", "missing"]), sf.Synthesize("synth")], optional=True)
    outer = sf.Fanout(["a", inner], quorum=1) >> sf.Synthesize("synth")
    seen: list[dict] = []
    assert await run(compile_candidate(outer).url4, ctx=_context(seen)) == "synthesized"
    assert len(seen) == 1
    assert "member_2" not in seen[0]["outputs"]


@pytest.mark.parametrize(
    "recipe",
    [
        sf.Model("a", optional=True),
        sf.Pipeline(["a", "b"], optional=True),
        sf.Pipeline([sf.Fanout(["a", "b"]), sf.Synthesize("synth")], optional=True),
    ],
)
def test_optional_is_only_valid_in_a_fusion_member_position(recipe: sf.Recipe) -> None:
    with pytest.raises(ValueError, match="sf.Fanout members"):
        compile_candidate(recipe)
    with pytest.raises(ValueError, match="sf.Fanout members"):
        sf.Pipeline([recipe, "final"])
    with pytest.raises(ValueError, match="sf.Fanout members"):
        _ = sf.Fanout(["a"]) >> sf.Synthesize(recipe)


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_optional_requires_a_boolean_on_every_member_kind(value: Any) -> None:
    with pytest.raises(TypeError, match="optional"):
        sf.Model("a", optional=value)
    with pytest.raises(TypeError, match="optional"):
        sf.Pipeline(["a"], optional=value)
    with pytest.raises(TypeError, match="optional"):
        sf.Pipeline([sf.Fanout(["a"]), sf.Synthesize("synth")], optional=value)


def test_optional_members_flag_is_removed() -> None:
    with pytest.raises(TypeError, match="optional_members"):
        sf.Fanout(["a"], optional_members=True)  # type: ignore[call-arg]
    # a block has no member flag at all: the way to make a block optional is its Pipeline
    assert "optional_members" not in inspect.signature(sf.Fanout).parameters
    assert "optional" not in inspect.signature(sf.Fanout).parameters
    assert sf.Pipeline([sf.Fanout(["a"]), sf.Synthesize("synth")], optional=True).optional is True


@pytest.mark.parametrize("kind", ["model", "pipeline", "fusion"])
def test_fusion_repr_distinguishes_optional_member_policy(kind: str) -> None:
    # WHY: identical printed panels hid whether a member failure stops synthesis.
    def member(optional: bool) -> sf.Recipe:
        if kind == "model":
            return sf.Model("a", optional=optional)
        if kind == "pipeline":
            return sf.Pipeline(["a", "b"], optional=optional)
        return sf.Pipeline([sf.Fanout(["a", "b"]), sf.Synthesize("inner")], optional=optional)

    optional_member = member(True)
    required_member = member(False)
    tolerant = sf.Fanout([optional_member, "c"], quorum=1) >> sf.Synthesize("s")
    required = sf.Fanout([required_member, "c"], quorum=1) >> sf.Synthesize("s")
    # WHY: a plain model member prints as its route; any other member prints its repr.
    shown = repr(required_member.name) if kind == "model" else repr(required_member)
    assert repr(tolerant) != repr(required)
    assert repr(tolerant) == f"Fanout([{optional_member!r}, 'c'], quorum=1) >> Synthesize('s')"
    assert repr(required) == f"Fanout([{shown}, 'c'], quorum=1) >> Synthesize('s')"
