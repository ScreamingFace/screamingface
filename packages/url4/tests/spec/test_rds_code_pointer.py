"""Code-pointer intents run as RDS calls (url4 2.0, Spec A §1.1, Spec B §6).

Spec: ``docs/spec/2026-10-10-url4-rds-code-pointer/`` (overview R1–R5, contracts C1–C10,
PRD §3 scenarios). This module starts with CH11 — the PRD §2 probe table, one test per row,
pinned on url4 1.5.1 before any delta. A row marked *flips* changes in the commit that
changes the behavior; the PR body lists it.

FEATURE: code-pointer intents (RDS mode).
"""

from __future__ import annotations

import pytest
from conftest import RecordingIOLayer

from url4 import StaticIOLayer, Url4Node
from url4.core.errors import ErrorCode, Url4Error
from url4.dag import run
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

_MEMBERS = "member_1:/a($input)!'P', member_2:/b($input)!'P'"


def _members_node(calls: list[tuple[str, str, str]]) -> Url4Node:
    node = Url4Node("t", outbound=StaticIOLayer({}))

    @node.endpoint("/a")
    def member_a(req: Request) -> str:
        calls.append(("/a", req.context, req.intent))
        return "A says 4"

    @node.endpoint("/b")
    def member_b(req: Request) -> str:
        calls.append(("/b", req.context, req.intent))
        return "B says 5"

    return node


def _recording_process(calls: list[tuple[str, str | None]]):
    async def process(sources: str, intent: str | None, scope: object) -> str:
        calls.append((sources, intent))
        return f"PROCESSED[{intent}|{sources}]"

    return process


# --- CH11: the PRD §2 probe table on url4 1.5.1 ---------------------------------------


async def test_ch11_row1_uri_intent_at_an_endpoint_is_fetched_without_q() -> None:
    # flips (P2): the code mount runs once instead.
    calls: list[tuple[str, str, str]] = []
    node = _members_node(calls)

    @node.endpoint("/ensemble/combine/v1")
    def combine(req: Request) -> str:  # never reached: the intent is fetched with no q=
        return "C"

    with pytest.raises(Url4Error) as info:
        await node.evaluate(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote")
    assert info.value.code == ErrorCode.MISSING_INTENT


async def test_ch11_row1_uri_intent_with_nothing_mounted_is_endpoint_not_found() -> None:
    # flips (P2): intent_error, and the members never run.
    node = _members_node([])
    with pytest.raises(Url4Error) as info:
        await node.evaluate(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote")
    assert info.value.code == ErrorCode.ENDPOINT_NOT_FOUND


async def test_ch11_row2_at_sign_in_the_intent_query_is_refused_as_param_value() -> None:
    # flips (P2): the query is a `query-tail`, where `@` is allowed (C7).
    node = _members_node([])
    with pytest.raises(Url4Error) as info:
        await node.evaluate(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote&extract=last_number@1")
    assert info.value.code == ErrorCode.MALFORMED_SOURCE


async def test_ch11_row3_data_route_intent_becomes_the_reducer_instruction() -> None:
    # flips (P2): `/instr` is a data route, not code → intent_error.
    calls: list[tuple[str, str, str]] = []
    node = _members_node(calls)
    node.data("/instr", "INSTRUCTION TEXT")
    result = await node._run_text("(m1:/a(x)!'P', m2:/b(x)!'P')!/instr")
    assert result == "A says 4"  # the default processor route is the first endpoint, /a
    reducer_input = [c for c in calls if c[1] == ""][0][2]
    assert reducer_input.endswith("[Instruction]\nINSTRUCTION TEXT")


async def test_ch11_row4_weight_zero_member_is_missing_from_the_reducer_input() -> None:
    # flips (P2): under RDS a weight-0.0 source is delivered (B §5.3.10.3).
    calls: list[tuple[str, str, str]] = []
    node = _members_node(calls)
    node.data("/instr", "INSTRUCTION TEXT")
    await node._run_text("(m1:/a(x)!'P', m2:0.0:/b(x)!'P')!/instr")
    reducer_input = [c for c in calls if c[1] == ""][0][2]
    assert "m1:\nA says 4" in reducer_input
    assert "B says 5" not in reducer_input


async def test_ch11_row5_data_route_intent_is_the_process_hook_prompt() -> None:
    # flips (P2): a relative URI intent runs code; no `process` call.
    calls: list[tuple[str, str | None]] = []
    io = StaticIOLayer({"/instr": "INSTRUCTION TEXT"})
    result = await run("(x='hello', y='world')!/instr", io, process=_recording_process(calls))
    assert calls == [("x: hello\ny: world", "INSTRUCTION TEXT")]
    assert result == "PROCESSED[INSTRUCTION TEXT|x: hello\ny: world]"


async def test_ch11_row6_iteration_reducer_path_is_the_prompt_itself() -> None:
    # flips (P2): `/reduce` is a code mount and gets the rows as one list input.
    calls: list[tuple[str, str | None]] = []
    io = StaticIOLayer({"/rows": '["r1","r2"]'})
    await run("(/rows*()!'R $item')!/reduce", io, process=_recording_process(calls))
    assert calls[-1][1] == "/reduce"
    assert calls[-1][0] == '["PROCESSED[R r1|]", "PROCESSED[R r2|]"]'


async def test_ch11_row7_relative_expression_intent_is_a_data_read() -> None:
    # flips (P1): the intent is a relative expression and is evaluated (H7).
    io = RecordingIOLayer({}, {"/w": lambda context, intent: f"W<{context}|{intent}>"})
    result = await run("((x='hi')!'S')!/w?q=($1)!'Write'", io)
    assert io.fetches == ["/w?q=($1)!'Write'"]  # one raw fetch: `$1` was never substituted
    assert result.startswith("W<$1|'Write'>")


async def test_ch11_row8_absolute_uri_intent_is_fetched_as_the_prompt() -> None:
    # stays (D2, owner decision Q1): every absolute URI keeps the 1.5.1 meaning.
    calls: list[tuple[str, str | None]] = []
    io = StaticIOLayer({"https://a/score.py": "SCORE"})
    result = await run("(x='1')!https://a/score.py", io, process=_recording_process(calls))
    assert calls == [("x: 1", "SCORE")]
    assert result == "PROCESSED[SCORE|x: 1]"


async def test_ch11_row9_canonical_expression_with_protocol_params_is_a_data_read() -> None:
    # flips (P1): `/claude?t=90&q=(y)!'go'` is a relative expression (C1 detection row 4).
    calls: list[tuple[str, str | None]] = []
    io = StaticIOLayer({"/claude?t=90&q=(y)!'go'": "DATA"})
    result = await run("(x='1')!/claude?t=90&q=(y)!'go'", io, process=_recording_process(calls))
    assert calls == [("x: 1", "DATA")]
    assert result == "PROCESSED[DATA|x: 1]"


async def test_ch11_row10_forwarded_code_pointer_intent_is_resolved_by_the_caller() -> None:
    # flips (P2, C9): the request to /p carries `q=(ctx)!/code` verbatim.
    io = RecordingIOLayer({"/code": "CODE TEXT"}, {"/p": lambda context, intent: "P"})
    await run("(s=/p(ctx)!/code)!'$s'", io)
    assert io.fetches[:2] == ["/code", "/p?q=(ctx)!CODE%20TEXT"]
