"""The SDK front doors blame the caller's TREE, not the text they never wrote.

``Client.evaluate`` and ``Url4Node.evaluate`` render a caller-supplied ``Node`` with
``check=False`` — the round-trip re-parse costs ~15x the render, and every tree the
library itself produces is already pinned by the renderer's property tests. The cost of
skipping it is diagnostic: a tree the grammar cannot faithfully carry (spec §8.1.2) used
to fail downstream as a ``ParseError`` quoting rendered text the caller never saw.

``_blaming_render`` buys the diagnostic back without the happy-path cost: it verifies the
round-trip only once the run has already raised ``ParseError``. These tests pin both
halves — the unfaithful tree is blamed, and a parse failure that is genuinely the run's
is left alone.
"""

from __future__ import annotations

import pytest

from url4.core.errors import ParseError, RenderError
from url4.core.nodes import Expression, Node, RelUrl, Text
from url4.core.parser import build
from url4.io.static import StaticIOLayer
from url4.peer.client import Client, _blaming_render
from url4.peer.server import Url4Node

# A tree the grammar cannot carry: the space in the path renders bare, and the rendered
# text reparses as something else — exactly the §8.1.2 hazard check=True would catch.
UNFAITHFUL: Node = Expression(sources=(RelUrl("/data/my file.json"),), intent=Text("summarize"))


def _world() -> StaticIOLayer:
    return StaticIOLayer(
        {"/data/a.json": "alpha"},
        {"/model": lambda context, intent: f"{intent}:{context}"},
    )


# --- the tree is blamed, through both front doors ------------------------------------


@pytest.mark.asyncio
async def test_client_evaluate_blames_an_unfaithful_tree() -> None:
    client = Client(_world())

    with pytest.raises(RenderError) as caught:
        await client.evaluate(UNFAITHFUL)

    assert caught.value.code == "unrenderable"


@pytest.mark.asyncio
async def test_node_evaluate_blames_an_unfaithful_tree() -> None:
    node = Url4Node(name="probe", data={"/a.json": lambda: "alpha"})

    with pytest.raises(RenderError) as caught:
        await node.evaluate(UNFAITHFUL)

    assert caught.value.code == "unrenderable"


# --- what must NOT be re-attributed --------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_text_still_raises_parse_error() -> None:
    """Text has no tree behind it, so there is nothing to blame — the ParseError stands."""
    node = Url4Node(name="probe", data={"/a.json": lambda: "alpha"})

    with pytest.raises(ParseError):
        await node.evaluate("(unbalanced!'x'")


@pytest.mark.asyncio
async def test_a_parse_failure_from_inside_the_run_is_left_alone() -> None:
    """A faithful tree means the run is at fault; re-attributing it would misdirect."""
    faithful = build("(/data/a.json)!'summarize'")

    async def run() -> str:
        raise ParseError("malformed sub-expression fetched mid-run")

    with pytest.raises(ParseError, match="mid-run"):
        await _blaming_render(faithful, "(/data/a.json)!'summarize'", run())


@pytest.mark.asyncio
async def test_a_text_request_skips_verification_entirely() -> None:
    async def run() -> str:
        raise ParseError("from inside the run")

    with pytest.raises(ParseError, match="from inside the run"):
        await _blaming_render(None, "(/data/a.json)!'summarize'", run())


# --- the happy path is untouched -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_faithful_tree_evaluates_without_verification() -> None:
    client = Client(_world())

    result = await client.evaluate(build("(/data/a.json)!'summarize'"))

    assert "alpha" in result.text
    assert result.request == "(/data/a.json)!'summarize'"


@pytest.mark.asyncio
async def test_blaming_render_returns_the_run_result_unchanged() -> None:
    async def run() -> str:
        return "done"

    assert await _blaming_render(UNFAITHFUL, "irrelevant", run()) == "done"
