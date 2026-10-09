"""Characterization of the url4 1.5.1 URI-intent probe table (CH11).

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author on 1.5.1, a URI intent `!/path` is read as instruction
# text, and a combine endpoint is not reachable from a group's intent. Each test
# below is one row of the probe table in PRD §2.3, run against the 1.5.1 code.
#
# AIDEV-NOTE: these tests pin 1.5.1 ON PURPOSE. A row marked "flips in Task 4" is
# the behavior that 2.0 removes; that test changes in the same commit as the
# behavior, and the PR body lists it. Do not "fix" a row here to match 2.0.
"""

from __future__ import annotations

import pytest

from url4.core.context import Context
from url4.core.errors import ParseError, ResolutionError
from url4.core.nodes import Expression, Text
from url4.core.parser import build
from url4.core.render import render
from url4.dag import ProcessFn, run
from url4.peer.server import Request, Url4Node


@pytest.fixture()
def wire() -> list[Request]:
    return []


@pytest.fixture()
def hook_calls() -> list[tuple[str, str | None]]:
    return []


@pytest.fixture()
def node(wire: list[Request]) -> Url4Node:
    n = Url4Node("t", default_processor="/claude")

    @n.endpoint("/a")
    async def member_a(request: Request) -> str:
        return "A says 4"

    @n.endpoint("/b")
    async def member_b(request: Request) -> str:
        return "B says 5"

    @n.endpoint("/ensemble/combine/v1")
    async def combine(request: Request) -> str:
        return "COMBINED"

    @n.endpoint("/claude")
    async def claude(request: Request) -> str:
        wire.append(request)
        return "CLAUDE"

    n.data("/instr", "INSTRUCTION TEXT")
    n.data("/rows", '["r1", "r2"]')
    return n


def _recording_process(hook_calls: list[tuple[str, str | None]]) -> ProcessFn:
    async def process(sources: str, intent: str | None, scope: Context) -> str:
        hook_calls.append((sources, intent))
        return f"{intent}\n\n{sources}" if intent and sources else (intent or sources or "")

    return process


_MEMBERS = "member_1:/a($input)!'P', member_2:/b($input)!'P'"


@pytest.mark.asyncio
async def test_char_1_5_1_combine_endpoint_is_not_reachable_from_an_intent(
    node: Url4Node,
) -> None:
    # AIDEV-NOTE: flips in Task 4 (the intent becomes a code-pointer call).
    expr = f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote"
    with pytest.raises(ResolutionError) as err:
        await run(expr, node)
    assert err.value.code == "endpoint_not_found"
    assert "has no endpoint, eval path, or data route at '/ensemble/combine/v1'" in str(err.value)


@pytest.mark.asyncio
async def test_char_1_5_1_at_in_a_reducer_query_is_malformed(node: Url4Node) -> None:
    # AIDEV-NOTE: flips in Task 4 (`@` is a query-tail character in 2.0).
    expr = f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote&extract=last_number@1"
    with pytest.raises(ParseError) as err:
        await run(expr, node)
    assert err.value.code == "malformed_source"
    assert "invalid param value 'last_number@1' for 'extract'" in str(err.value)


@pytest.mark.asyncio
async def test_char_1_5_1_data_route_intent_is_instruction_text(
    node: Url4Node, wire: list[Request]
) -> None:
    await run(f"({_MEMBERS})!/instr", node)
    assert wire[-1].intent == (
        "member_1:\nA says 4\n\nmember_2:\nB says 5\n\n[Instruction]\nINSTRUCTION TEXT"
    )


@pytest.mark.asyncio
async def test_char_1_5_1_weight_zero_member_is_missing_from_reducer_input(
    node: Url4Node, wire: list[Request]
) -> None:
    # AIDEV-NOTE: flips in Task 4 (an RDS call delivers weight-0.0 sources).
    await run("(member_1:/a($input)!'P', member_2:0.0:/b($input)!'P')!/instr", node)
    assert wire[-1].intent == "member_1:\nA says 4\n\n[Instruction]\nINSTRUCTION TEXT"


@pytest.mark.asyncio
async def test_char_1_5_1_named_sources_reach_the_process_hook(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    result = await run(
        "(x='hello', y='world')!/instr", node, process=_recording_process(hook_calls)
    )
    assert result == "INSTRUCTION TEXT\n\nx: hello\ny: world"
    assert hook_calls == [("x: hello\ny: world", "INSTRUCTION TEXT")]


@pytest.mark.asyncio
async def test_char_1_5_1_relative_reducer_path_is_the_prompt(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # AIDEV-NOTE: flips in Task 4 (an iteration reducer `/reduce` becomes one code-pointer call).
    result = await run("(/rows*()!'R $item')!/reduce", node, process=_recording_process(hook_calls))
    assert result == '/reduce\n\n["R r1", "R r2"]'


def test_char_1_5_1_quote_escapes_round_trip_and_a_doubled_quote_is_malformed() -> None:
    node = build("(a,b)!'it\\'s \\\\d+'")
    assert isinstance(node, Expression)
    assert node.intent == Text("it's \\d+")
    assert build(render(node)) == node
    with pytest.raises(ParseError):
        build("(a,b)!'it''s'")
