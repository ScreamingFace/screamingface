"""Code-pointer intents run as RDS calls (url4 2.0, Spec A §1.1, Spec B §6).

Spec: ``docs/spec/2026-10-10-url4-rds-code-pointer/`` (overview R1–R5, contracts C1–C10,
PRD §3 scenarios). This module starts with CH11 — the PRD §2 probe table, one test per row,
pinned on url4 1.5.1 before any delta. A row marked *flips* changes in the commit that
changes the behavior; the PR body lists it.

FEATURE: code-pointer intents (RDS mode).
"""

from __future__ import annotations

import json
import random
from typing import cast

import pytest
from conftest import RecordingIOLayer

from url4 import (
    CodeCall,
    CodeHandler,
    CodeInput,
    NamedJob,
    StaticIOLayer,
    Url4Node,
    expr,
)
from url4 import text as literal_text
from url4.core.errors import ErrorCode, ParseError, Url4Error
from url4.core.parser import build
from url4.core.render import render
from url4.dag import compile_expression, run
from url4.io.http import HttpIOLayer
from url4.observe import NodeStarted
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

_MEMBERS = "member_1:/a(x)!'P', member_2:/b(x)!'P'"


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


def _recorder(code_calls: list[CodeCall]):
    def handler(call: CodeCall) -> str:
        code_calls.append(call)
        return "COMBINED"

    return handler


def _recording_process(calls: list[tuple[str, str | None]]):
    async def process(sources: str, intent: str | None, scope: object) -> str:
        calls.append((sources, intent))
        return f"PROCESSED[{intent}|{sources}]"

    return process


# --- CH11: the PRD §2 probe table (pinned on 1.5.1; FLIPPED rows show 2.0) ----------------


async def test_ch11_row1_code_mount_runs_once_with_the_members() -> None:
    # FLIPPED (P2, H1): the code mount runs once; the members run; no processor route.
    calls: list[tuple[str, str, str]] = []
    code_calls: list[CodeCall] = []
    node = _members_node(calls)
    node.code("/ensemble/combine/v1")(_recorder(code_calls))
    result = await node._run_text(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote")
    assert result == "COMBINED"
    assert [call.inputs for call in code_calls] == [
        (
            CodeInput(1, "member_1", "A says 4", None),
            CodeInput(2, "member_2", "B says 5", None),
        )
    ]
    assert code_calls[0].params == {"reducer": "vote"}
    assert sorted(c[0] for c in calls) == ["/a", "/b"]  # no reduce request to an endpoint


async def test_ch11_row1_unmounted_pointer_fails_before_the_members_run() -> None:
    # FLIPPED (P2, E1): intent_error, and the members never run (R4 preflight).
    calls: list[tuple[str, str, str]] = []
    node = _members_node(calls)
    with pytest.raises(Url4Error) as info:
        await node.evaluate(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote")
    assert info.value.code == ErrorCode.INTENT_ERROR
    assert calls == []


async def test_ch11_row2_at_sign_in_the_pointer_query_is_a_param() -> None:
    # FLIPPED (P2, C7): the pointer query is a `query-tail`, where `@` is allowed.
    code_calls: list[CodeCall] = []
    node = _members_node([])
    node.code("/ensemble/combine/v1")(_recorder(code_calls))
    await node._run_text(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote&extract=last_number@1")
    assert code_calls[0].params == {"reducer": "vote", "extract": "last_number@1"}


async def test_ch11_row3_data_route_intent_is_not_code() -> None:
    # FLIPPED (P2, E2): `/instr` is a data route, not a code mount → intent_error.
    calls: list[tuple[str, str, str]] = []
    node = _members_node(calls)
    node.data("/instr", "INSTRUCTION TEXT")
    with pytest.raises(Url4Error) as info:
        await node._run_text("(m1:/a(x)!'P', m2:/b(x)!'P')!/instr")
    assert info.value.code == ErrorCode.INTENT_ERROR
    assert calls == []


async def test_ch11_row4_weight_zero_member_is_delivered() -> None:
    # FLIPPED (P2, H3): under RDS a weight-0.0 source is delivered with its weight.
    code_calls: list[CodeCall] = []
    node = _members_node([])
    node.code("/combine")(_recorder(code_calls))
    await node._run_text("(m1:/a(x)!'P', m2:0.0:/b(x)!'P')!/combine")
    assert code_calls[0].input("m2") == CodeInput(2, "m2", "B says 5", 0.0)


async def test_ch11_row5_relative_uri_intent_runs_code_not_the_process_hook() -> None:
    # FLIPPED (P2, R1): a relative URI intent runs code; no `process` call.
    calls: list[tuple[str, str | None]] = []
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({"/instr": "INSTRUCTION TEXT"}, code={"/instr": _recorder(code_calls)})
    result = await run("(x='hello', y='world')!/instr", io, process=_recording_process(calls))
    assert result == "COMBINED"
    assert calls == []
    assert code_calls[0].inputs == (
        CodeInput(1, "x", "hello", None),
        CodeInput(2, "y", "world", None),
    )


async def test_ch11_row6_iteration_reducer_code_gets_the_rows_as_one_list() -> None:
    # FLIPPED (P2, D7): `/reduce` is a code mount; the rows arrive as ONE list input.
    calls: list[tuple[str, str | None]] = []
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({"/rows": '["r1","r2"]'}, code={"/reduce": _recorder(code_calls)})
    result = await run("(/rows*()!'R $item')!/reduce", io, process=_recording_process(calls))
    assert result == "COMBINED"
    assert code_calls[0].inputs == (
        CodeInput(1, None, ["PROCESSED[R r1|]", "PROCESSED[R r2|]"], None),
    )
    assert all(intent != "/reduce" for _sources, intent in calls)


async def test_ch11_row7_relative_expression_intent_is_evaluated() -> None:
    # FLIPPED (P1, H7): the intent is a relative expression. `/w` is called once, with the
    # group's `$1` substituted, and its answer is the prompt of the outer group.
    calls: list[tuple[str, str | None]] = []
    io = RecordingIOLayer({}, {"/w": lambda context, intent: f"W<{context}|{intent}>"})
    result = await run("((x='hi')!'S')!/w?q=($1)!'Write'", io, process=_recording_process(calls))
    # url4 2.0 (A5): a forwarded prompt travels quoted.
    assert io.fetches == ["/w?q=(PROCESSED[S|x:%20hi])!%27Write%27"]
    assert calls[-1][1] == "W<PROCESSED[S|x: hi]|Write>"
    assert result.startswith("PROCESSED[W<PROCESSED[S|x: hi]|Write>|")


async def test_ch11_row8_absolute_uri_intent_is_fetched_as_the_prompt() -> None:
    # stays (D2, owner decision Q1): every absolute URI keeps the 1.5.1 meaning.
    calls: list[tuple[str, str | None]] = []
    io = StaticIOLayer({"https://a/score.py": "SCORE"})
    result = await run("(x='1')!https://a/score.py", io, process=_recording_process(calls))
    assert calls == [("x: 1", "SCORE")]
    assert result == "PROCESSED[SCORE|x: 1]"


async def test_ch11_row9_canonical_expression_with_protocol_params_is_evaluated() -> None:
    # FLIPPED (P1, H7): `/claude?t=90&q=(y)!'go'` is a relative expression (C1 detection
    # row 4); its protocol params travel before `q=`.
    calls: list[tuple[str, str | None]] = []
    io = RecordingIOLayer({}, {"/claude": lambda context, intent: f"C<{context}|{intent}>"})
    result = await run("(x='1')!/claude?t=90&q=(y)!'go'", io, process=_recording_process(calls))
    # url4 2.0 (A5): a forwarded prompt travels quoted (`go` was written quoted: a prompt).
    assert io.fetches == ["/claude?t=90&q=(y)!%27go%27"]
    assert calls == [("x: 1", "C<y|go>")]
    assert result == "PROCESSED[C<y|go>|x: 1]"


async def test_ch11_row10_forwarded_code_pointer_intent_is_verbatim() -> None:
    # FLIPPED (P2, D12, C9): the request to /p carries `q=(ctx)!/code` verbatim; the
    # caller never fetches /code.
    io = RecordingIOLayer({"/code": "CODE TEXT"}, {"/p": lambda context, intent: "P"})
    await run("(s=/p(ctx)!/code)!'$s'", io)
    assert io.fetches[0] == "/p?q=(ctx)!/code"
    assert "/code" not in io.fetches


# --- shared helpers for the H, E and D scenarios ----------------------------------------------


class _CountingIO(StaticIOLayer):
    """A code-capable StaticIOLayer that records every fetched target."""

    def __init__(self, fetch_map: dict[str, str], code: dict[str, CodeHandler]) -> None:
        super().__init__(fetch_map, code=code)
        self.targets: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.targets.append(target)
        return await super().fetch(target, relative=relative)


class _EventRecorder:
    """Collects every observation event, in emission order (as in test_usage_sink)."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def on_event(self, event: object) -> None:
        self.events.append(event)


async def _echo_process(sources: str, intent: str | None, scope: object) -> str:
    return intent or ""


# --- H: happy path -----------------------------------------------------------------------------


async def test_h1_one_call_no_model_no_processor() -> None:
    # H1 (R2, R3, R4): one code call; the members run; no model; no processor route.
    calls: list[tuple[str, str, str]] = []
    code_calls: list[CodeCall] = []
    process_calls: list[tuple[str, str | None]] = []
    node = _members_node(calls)
    node.code("/ensemble/combine/v1")(_recorder(code_calls))
    result = await run(
        f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote",
        node,
        process=_recording_process(process_calls),
    )
    assert result == "COMBINED"
    assert process_calls == []
    assert sorted(c[0] for c in calls) == ["/a", "/b"]
    assert len(code_calls) == 1
    assert code_calls[0].inputs == (
        CodeInput(1, "member_1", "A says 4", None),
        CodeInput(2, "member_2", "B says 5", None),
    )
    assert dict(code_calls[0].params) == {"reducer": "vote"}


async def test_h2_byte_exact_values_through_a_real_node() -> None:
    # H2 (R3): each CodeInput.value is the served text, byte for byte, and a str.
    alphabet = "\n\"'%&()\\é中{}[]:,=?/ \tabcXYZ019+@$#"
    rng = random.Random(20261010)
    texts = ['{"k": [1, "two\\n", null]}', "100%&(x)=\\y\nz"]
    for _ in range(20):
        texts.append("".join(rng.choice(alphabet) for _ in range(rng.randint(1, 24))))
    node = Url4Node("t", outbound=StaticIOLayer({}))
    for index, text in enumerate(texts):
        node.data(f"/d{index}", text)
    code_calls: list[CodeCall] = []
    node.code("/combine")(_recorder(code_calls))
    sources = ", ".join(f"s{index}=/d{index}" for index in range(len(texts)))
    await node._run_text(f"({sources})!/combine")
    values = [item.value for item in code_calls[0].inputs]
    assert values == texts
    assert all(isinstance(value, str) for value in values)


async def test_h3_weight_zero_source_is_delivered_with_its_weight() -> None:
    # H3 (R3, payload_bind_reweigh): a weight-0.0 source is delivered with weight 0.0.
    code_calls: list[CodeCall] = []
    node = _members_node([])
    node.code("/combine")(_recorder(code_calls))
    await node._run_text(r"(member_1:/a(x)!'P', pattern:0.0:'ANSWER: \\d+')!/combine")
    assert code_calls[0].input("pattern") == CodeInput(2, "pattern", "ANSWER: \\d+", 0.0)


async def test_h4_params_keep_at_plus_and_bare_flags() -> None:
    # H4 (C7): @ and + stay in the param values; a bare flag is the empty string.
    code_calls: list[CodeCall] = []
    node = _members_node([])
    node.code("/combine")(_recorder(code_calls))
    await node._run_text("(x='1')!/combine?reducer=vote&extract=last_number@1&sep=a+b&dry")
    assert dict(code_calls[0].params) == {
        "reducer": "vote",
        "extract": "last_number@1",
        "sep": "a+b",
        "dry": "",
    }


async def test_h5_calls_plus_a_weight_zero_quoted_source_make_one_call() -> None:
    # H5 (R2, C5): members that are calls plus a quoted weight-0.0 source: one code call.
    calls: list[tuple[str, str, str]] = []
    code_calls: list[CodeCall] = []
    node = _members_node(calls)
    node.code("/combine")(_recorder(code_calls))
    await node._run_text("(member_1:/a(x)!'P', member_2:/b(x)!'P', lit:0.0:'literal')!/combine")
    assert len(code_calls) == 1
    assert code_calls[0].inputs == (
        CodeInput(1, "member_1", "A says 4", None),
        CodeInput(2, "member_2", "B says 5", None),
        CodeInput(3, "lit", "literal", 0.0),
    )


async def test_h6_quoted_intent_stays_the_fan_out_reduce() -> None:
    # H6 (R1): a quoted intent keeps the 1.5.1 fan-out reduce; no code call.
    calls: list[tuple[str, str, str]] = []
    code_calls: list[CodeCall] = []
    node = _members_node(calls)
    node.code("/combine")(_recorder(code_calls))
    await node._run_text("(m1:/a(x)!'P', m2:/b(x)!'P')!'Pick best'")
    assert code_calls == []
    # The 1.5.1 reduce sends the composed text, with the intent after [Instruction], to /a.
    assert any(path == "/a" and "[Instruction]\nPick best" in intent for path, _, intent in calls)


async def test_h8_positional_access_to_free_text_and_data() -> None:
    # H8 (R3): positions 1-3; names member_1, None, None; $2 reads by position.
    code_calls: list[CodeCall] = []
    node = _members_node([])
    node.data("/doc", "DOC TEXT")
    node.code("/combine")(_recorder(code_calls))
    await node._run_text("(member_1:/a(x)!'P', 'free text', /doc)!/combine")
    call = code_calls[0]
    assert call.inputs == (
        CodeInput(1, "member_1", "A says 4", None),
        CodeInput(2, None, "free text", None),
        CodeInput(3, None, "DOC TEXT", None),
    )
    assert call.input("$2").value == "free text"


# --- E: error paths ----------------------------------------------------------------------------


async def test_e1_unmounted_pointer_fails_before_any_source_runs() -> None:
    # E1 (R4, evalGroup_unmounted): intent_error before /a runs; an optional wrapper drops it.
    calls: list[tuple[str, str, str]] = []
    code_calls: list[CodeCall] = []
    node = _members_node(calls)
    node.code("/combine")(_recorder(code_calls))
    with pytest.raises(Url4Error) as info:
        await node.evaluate(f"({_MEMBERS})!/nope")
    assert info.value.code == ErrorCode.INTENT_ERROR
    assert info.value.permanent is True
    assert calls == []
    result = await node._run_text("((m1:/a(x)!'P')!/nope;optional, good='2')!/combine;quorum=1")
    assert result == "COMBINED"
    assert code_calls[0].inputs == (CodeInput(2, "good", "2", None),)
    assert calls == []


async def test_e2_endpoint_and_data_route_are_not_code() -> None:
    # E2 (C2, C8): an endpoint path or a data route used as the intent is intent_error.
    calls: list[tuple[str, str, str]] = []
    node = _members_node(calls)
    node.data("/instr", "INSTRUCTION TEXT")
    with pytest.raises(Url4Error) as endpoint:
        await node._run_text("(m1:/b(x)!'P', m2:/b(x)!'P')!/a")
    assert endpoint.value.code == ErrorCode.INTENT_ERROR
    with pytest.raises(Url4Error) as data:
        await node._run_text("(m1:/a(x)!'P', m2:/b(x)!'P')!/instr")
    assert data.value.code == ErrorCode.INTENT_ERROR


async def test_e3_handler_failures_are_permanent_intent_errors() -> None:
    # E3 (C8, C §13.6): a raise or a non-str return is intent_error, permanent.
    def raises_value_error(call: CodeCall) -> str:
        raise ValueError("bad input")

    def raises_custom(call: CodeCall) -> str:
        raise Url4Error("x", code="x.custom", permanent=False)

    def returns_number(call: CodeCall) -> int:
        return 7

    io = StaticIOLayer(
        {},
        code={
            "/boom": raises_value_error,
            "/custom": raises_custom,
            "/number": cast(CodeHandler, returns_number),
        },
    )
    for expression in ("(x='1')!/boom", "(x='1')!/number"):
        with pytest.raises(Url4Error) as info:
            await run(expression, io)
        assert info.value.code == ErrorCode.INTENT_ERROR
        assert info.value.permanent is True
    with pytest.raises(Url4Error) as custom:
        await run("(x='1')!/custom", io)
    assert custom.value.code == ErrorCode.INTENT_ERROR
    assert custom.value.permanent is True
    assert "x.custom" in str(custom.value)


async def test_e4_required_source_failure_wins_over_quorum() -> None:
    # E4 (R2, gate_eq_false_of_required_failed): a failed required source fails the group.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({}, code={"/combine": _recorder(code_calls)})
    with pytest.raises(Url4Error) as info:
        await run("(x='1', m2:/missing)!/combine;quorum=1", io)
    assert info.value.code == ErrorCode.RESOLUTION_FAILED
    assert code_calls == []


async def test_e5_two_failed_optional_members_fail_quorum() -> None:
    # E5 (R2, C4): two optional members fail under quorum=1: quorum_not_met, no call.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({}, code={"/combine": _recorder(code_calls)})
    with pytest.raises(Url4Error) as info:
        await run("(m1:/nope1;optional, m2:/nope2;optional)!/combine;quorum=1", io)
    assert info.value.code == ErrorCode.QUORUM_NOT_MET
    assert code_calls == []


async def test_e6_absolute_uri_intents_are_prompts_never_code() -> None:
    # E6 (R1, Q1, D2, v1_act_eq_invokeLocal_iff): an absolute URI intent is fetched as the prompt.
    code_calls: list[CodeCall] = []
    recorder = _recorder(code_calls)
    io = _CountingIO(
        {"https://a/instr": "PROMPT A", "url4://n/instr": "PROMPT N"},
        {"/instr": recorder, "https://a/instr": recorder, "url4://n/instr": recorder},
    )
    process_calls: list[tuple[str, str | None]] = []
    await run("(x='1')!https://a/instr", io, process=_recording_process(process_calls))
    await run("(x='1')!url4://n/instr", io, process=_recording_process(process_calls))
    assert process_calls == [("x: 1", "PROMPT A"), ("x: 1", "PROMPT N")]
    assert "https://a/instr" in io.targets
    assert "url4://n/instr" in io.targets
    assert code_calls == []


async def test_e7_no_code_port_is_unsupported_mode_and_optional_drops_it() -> None:
    # E7 (C2, C8): a relative code pointer on an IO with no code port is unsupported_mode.
    with pytest.raises(Url4Error) as info:
        await run("(x='1')!/instr", HttpIOLayer("http://127.0.0.1:1"))
    assert info.value.code == ErrorCode.UNSUPPORTED_MODE
    process_calls: list[tuple[str, str | None]] = []
    result = await run(
        "((a='1')!/code;optional, b='2')!'$b';quorum=1",
        HttpIOLayer("http://127.0.0.1:1"),
        process=_recording_process(process_calls),
    )
    assert result == "PROCESSED[2|b: 2]"
    assert process_calls == [("b: 2", "2")]


async def test_e8_query_outside_query_tail_is_malformed_at_compile() -> None:
    # E8 (C7): a comma, a percent sign or a duplicate key in a pointer query is malformed_source.
    for expression in ("(x='1')!/p?x=1,2", "(x='1')!/p?x=%40", "(x='1')!/p?a=1&a=2"):
        with pytest.raises(ParseError) as info:
            compile_expression(expression)
        assert info.value.code == ErrorCode.MALFORMED_SOURCE


async def test_e9_eval_path_protocol_param_keeps_param_value() -> None:
    # E9 (C7, CH7): the eval-path protocol param still refuses @ (param-value).
    node = Url4Node("t", outbound=StaticIOLayer({}))
    with pytest.raises(Url4Error) as info:
        await node.fetch("/v1?tone=a@b&q=(x='1')!'go'", relative=True)
    assert info.value.code == ErrorCode.MALFORMED_SOURCE


async def test_e10_strict_field_paths_in_rds_and_lenient_in_llm() -> None:
    # E10 (C6, B §5.3.4.1): a missing field in an RDS iteration body is malformed_source.
    code_calls: list[CodeCall] = []
    node = Url4Node("t", outbound=StaticIOLayer({}))
    node.data("/rows", '[{"a":1},{"a":2}]')
    node.code("/score")(_recorder(code_calls))
    result = await node.evaluate("/rows*(answer=$item.missing)!/score")
    rows = json.loads(result.text)
    assert len(rows) == 2
    for row in rows:
        assert row["error"]["code"] == ErrorCode.MALFORMED_SOURCE
    assert code_calls == []
    io = StaticIOLayer({"/rows": '[{"a":1},{"a":2}]'})
    prompt = await run("/rows*()!'Q: $item.missing'", io, process=_echo_process)
    assert json.loads(prompt) == ["Q: ", "Q: "]


# --- D: derived scenarios ----------------------------------------------------------------------


async def test_d1_failed_optional_source_is_absent_and_positions_keep() -> None:
    # D1 (Lean find?_pos_bind): a failed optional source gives no input; position 2 stays 2.
    code_calls: list[CodeCall] = []
    node = Url4Node("t", outbound=StaticIOLayer({}))

    @node.endpoint("/b")
    def member_b(req: Request) -> str:
        return "B says 5"

    node.code("/combine")(_recorder(code_calls))
    await node._run_text("(m1:/a(x)!'P';optional, m2:/b(x)!'P')!/combine;quorum=1")
    assert code_calls[0].inputs == (CodeInput(2, "m2", "B says 5", None),)


async def test_d2_weight_zero_stays_instrumental_in_llm_mode() -> None:
    # D2 (CH3): a weight-0.0 source in an LLM group is interpolated, not merged into sources.
    process_calls: list[tuple[str, str | None]] = []
    io = StaticIOLayer({"/hidden": "HIDDEN"})
    await run("(q:0.0:/hidden, 'lit')!'REDUCE $q'", io, process=_recording_process(process_calls))
    assert process_calls == [("lit", "REDUCE HIDDEN")]


async def test_d3_collections_are_lists_and_fetched_bodies_are_str() -> None:
    # D3 (C3): iteration, broadcast and $ref-to-collection sources are lists; a body is str.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer(
        {"/rows": '["r1","r2"]', "/body": '["a","b"]'},
        code={"/combine": _recorder(code_calls), "/score": _recorder(code_calls)},
    )
    await run(
        "(r=/rows*()!'R $item', bc=(x='1', y='2')!*/score, again=$r, body=/body)!/combine",
        io,
        process=_echo_process,
    )
    outer = [call for call in code_calls if call.pointer == "/combine"]
    assert len(outer) == 1
    assert isinstance(outer[0].input("r").value, list)
    assert isinstance(outer[0].input("bc").value, list)
    assert isinstance(outer[0].input("again").value, list)
    assert outer[0].input("body").value == '["a","b"]'


async def test_d4_struct_object_value_is_a_dict() -> None:
    # D4 (C3): a struct-object source is delivered as a dict.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({}, code={"/combine": _recorder(code_calls)})
    await run("(cfg={k: 'v', n: 3})!/combine", io)
    assert code_calls[0].input("cfg").value == {"k": "v", "n": 3}


async def test_d5_expansion_names_weights_and_positions() -> None:
    # D5 (C3, resolvedCount_expandWith_expand): a named expansion splits its weight; renumbered.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({"/rows": '["a", "b", "c"]'}, code={"/combine": _recorder(code_calls)})
    await run("(*rows:0.6:/rows, 'x')!/combine", io)
    inputs = code_calls[0].inputs
    assert [item.position for item in inputs] == [1, 2, 3, 4]
    assert [item.name for item in inputs] == ["rows[0]", "rows[1]", "rows[2]", None]
    assert [item.value for item in inputs[:3]] == ["a", "b", "c"]
    assert [item.weight for item in inputs[:3]] == pytest.approx([0.2, 0.2, 0.2])
    assert inputs[3].value == "x"
    await run("(/rows;expand, /rows;expand)!/combine", io)
    both = code_calls[1]
    with pytest.raises(ValueError):
        both.input("src[0]")
    assert both.input(1).value == "a"


async def test_d6_broadcast_skips_a_failed_optional_and_keeps_positions() -> None:
    # D6 (length_calls_broadcast): one call per resolved source; the B §6.1.4 array keeps positions.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({}, code={"/score": _recorder(code_calls)})
    result = await run("(a='1', b:/fails(x)!'P';optional, c='3')!*/score", io)
    assert [call.inputs for call in code_calls] == [
        (CodeInput(1, "a", "1", None),),
        (CodeInput(3, "c", "3", None),),
    ]
    items = json.loads(result)
    assert [item["source_position"] for item in items] == [1, 3]
    assert [item["result"] for item in items] == ["COMBINED", "COMBINED"]


async def test_d6_broadcast_pointer_with_a_reference_gets_current_then_named() -> None:
    # D6 (B §6.1.2 rules 3-4, C4): each call gets the current source first, then the $ref source.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({}, code={"/score/k": _recorder(code_calls)})
    await run("(cfg='k', a='1', c='3')!*/score/$cfg", io)
    assert len(code_calls) == 3
    assert {call.inputs for call in code_calls} == {
        (CodeInput(2, "a", "1", None), CodeInput(1, "cfg", "k", None)),
        (CodeInput(3, "c", "3", None), CodeInput(1, "cfg", "k", None)),
        (CodeInput(1, "cfg", "k", None),),
    }


async def test_d7_iteration_gives_one_call_per_element() -> None:
    # D7 (C5): an iteration body that is a code pointer runs once per element.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({"/rows": '[{"a":1},{"a":2}]'}, code={"/score": _recorder(code_calls)})
    await run("/rows*(answer=$item.a)!/score", io)
    assert [call.input("answer").value for call in code_calls] == ["1", "2"]


async def test_d7_iteration_reducer_gets_the_rows_as_one_list() -> None:
    # D7 (C5, CH6): a reducer code pointer gets the rows as one list input.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({"/rows": '["r1","r2"]'}, code={"/reduce": _recorder(code_calls)})
    await run("(/rows*()!'R $item')!/reduce", io, process=_echo_process)
    assert len(code_calls) == 1
    assert code_calls[0].inputs[0].value == ["R r1", "R r2"]


async def test_d7_relative_iteration_reducer_with_a_remote_source_is_unchanged() -> None:
    # D7 (A4, CH6): the computed reducer over an absolute iteration is unchanged; no code call.
    code_calls: list[CodeCall] = []

    def reducer(context: str, intent: str) -> str:
        return "REDUCED"

    io = StaticIOLayer(
        {"https://rows": '["r1","r2"]'},
        routes={"/reduce": reducer},
        code={"/reduce": _recorder(code_calls)},
    )
    result = await run("(https://rows*()!'R $item')!/reduce()!'agg'", io)
    assert result == "REDUCED"
    assert code_calls == []


async def test_d8_vacuous_quorum_runs_the_code_with_no_inputs() -> None:
    # D8 (gate_all_of_all_optional, C4): all sources optional and failed under quorum=all runs.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({}, code={"/combine": _recorder(code_calls)})
    await run("(m1:/nope1;optional, m2:/nope2;optional)!/combine", io)
    assert code_calls[0].inputs == ()


async def test_d9_majority_quorum_counts_resolved_sources() -> None:
    # D9 (C4): majority of 5 sources is 3; 3 resolved runs, 2 resolved is quorum_not_met.
    code_calls: list[CodeCall] = []
    io = StaticIOLayer({}, code={"/combine": _recorder(code_calls)})
    await run(
        "(a='1', b='2', c='3', d:/nope1;optional, e:/nope2;optional)!/combine;quorum=majority",
        io,
    )
    assert len(code_calls[0].inputs) == 3
    with pytest.raises(Url4Error) as info:
        await run(
            "(a='1', b='2', c:/nope1;optional, d:/nope2;optional, e:/nope3;optional)"
            "!/combine;quorum=majority",
            io,
        )
    assert info.value.code == ErrorCode.QUORUM_NOT_MET


async def test_d10_processor_id_is_used_only_by_the_llm_group() -> None:
    # D10 (C5, processor= does not touch RDS): an RDS group never reaches the processor route.
    code_calls: list[CodeCall] = []
    hits: list[str] = []

    def gpt4(context: str, intent: str) -> str:
        hits.append("/gpt4")
        return f"gpt4:{intent}"

    def claude(context: str, intent: str) -> str:
        hits.append("/claude")
        return "claude"

    io = StaticIOLayer(
        {},
        routes={"/gpt4": gpt4, "/claude": claude},
        code={"/combine": _recorder(code_calls)},
    )
    assert await run("(x='1')!/combine", io, processor="unknown-id") == "COMBINED"
    assert len(code_calls) == 1
    # The LLM group (sub) is a fan-out reduce to the processor; the RDS sibling (r) is one call.
    result = await run(
        "(r=(x='1')!/combine, sub=(m1:/claude(y)!'P', m2:/claude(z)!'P')!'Final')!'Outer'",
        io,
        processor="gpt4",
    )
    assert len(code_calls) == 2
    assert "r: COMBINED" in result
    assert "sub: gpt4:" in result
    assert hits.count("/gpt4") == 1
    assert hits.count("/claude") == 2


async def test_d11_eval_path_runs_the_nodes_own_code_once() -> None:
    # D11 (R5): a GET on the eval path runs the node's own code mount once.
    code_calls: list[CodeCall] = []
    node = Url4Node("t", outbound=StaticIOLayer({}))
    node.code("/combine")(_recorder(code_calls))
    await node.fetch("/v1?q=(a='1', b='2')!/combine", relative=True)
    assert len(code_calls) == 1
    assert code_calls[0].inputs == (
        CodeInput(1, "a", "1", None),
        CodeInput(2, "b", "2", None),
    )


async def test_d12_forwarded_relative_code_pointer_travels_verbatim() -> None:
    # D12 (C9): the request to /p carries the pointer verbatim; the caller never fetches /code.
    io = RecordingIOLayer({}, {"/p": lambda context, intent: "P"})
    await run("(s=/p(ctx)!/code)!'$s'", io)
    assert io.fetches[0] == "/p?q=(ctx)!/code"
    assert not any(target.startswith("/code") for target in io.fetches)


async def test_d12_forwarded_remote_code_pointer_travels_verbatim() -> None:
    # D12 (C9): a remote call's request carries the pointer verbatim.
    io = RecordingIOLayer({})
    await run("(s=url4://n/v1(ctx)!/code)!'$s'", io, process=_echo_process)
    assert len(io.fetches) == 1
    assert io.fetches[0].startswith("url4://n/v1")
    assert "q=(ctx)!/code" in io.fetches[0]


async def test_d12_forwarded_quoted_intent_travels_quoted() -> None:
    # FLIPPED (row 28, A5 fixed in 2.0, C9): a forwarded prompt keeps its quotes on the
    # wire, and the endpoint still receives the unquoted prompt.
    seen: list[str] = []
    io = RecordingIOLayer({}, {"/p": lambda context, intent: seen.append(intent) or "P"})
    await run("(s=/p(ctx)!'Answer')!'$s'", io)
    assert io.fetches[0] == "/p?q=(ctx)!%27Answer%27"
    assert seen[0] == "Answer"  # (the outer group then reduces through /p, the only route)


async def test_d13_dollar_in_the_pointer_is_interpolated_or_refused() -> None:
    # D13 (C1, C6): $ in a pointer reads the group's own sources; a bad reference fails.
    code_calls: list[CodeCall] = []
    node = _members_node([])
    node.code("/score/v2")(_recorder(code_calls))
    await node._run_text("(v='2', m:/a(x)!'P')!/score/v$v")
    assert code_calls[0].pointer == "/score/v2"
    with pytest.raises(Url4Error) as missing:
        await node.evaluate("(m:/a(x)!'P')!/score/$missing")
    assert missing.value.code == ErrorCode.UNBOUND_REFERENCE
    with pytest.raises(Url4Error) as strict:
        await node.evaluate("(cfg={k: 'v'}, m:/a(x)!'P')!/score/$cfg.missing")
    assert strict.value.code == ErrorCode.MALFORMED_SOURCE


# --- Row 24 (observability) and Row 25 (E2E) ---------------------------------------------------


async def test_row24_rds_run_emits_a_code_call_node_started() -> None:
    # Row 24 (Observability, §4): an RDS group is observed as a CodeCallNode.
    code_calls: list[CodeCall] = []
    recorder = _EventRecorder()
    io = StaticIOLayer({}, code={"/combine": _recorder(code_calls)})
    await run("(x='1')!/combine", io, observer=recorder)
    kinds = [event.node_kind for event in recorder.events if isinstance(event, NodeStarted)]
    assert "CodeCallNode" in kinds


async def test_e4a_vote_three_models_feed_the_stub_byte_exact() -> None:
    # Row 25 (E2E, E4a): the three member texts reach the combine stub byte for byte.
    texts = [
        "Step 1: 2 plus 2\nANSWER: 4",
        'I say "four"\n\\ 100% & (sure)\nANSWER: 4',
        "ANSWER: 5\ntè 中文",
    ]
    node = Url4Node("t", outbound=StaticIOLayer({}))

    @node.endpoint("/m1")
    def model_one(req: Request) -> str:
        return texts[0]

    @node.endpoint("/m2")
    def model_two(req: Request) -> str:
        return texts[1]

    @node.endpoint("/m3")
    def model_three(req: Request) -> str:
        return texts[2]

    code_calls: list[CodeCall] = []
    node.code("/ensemble/combine/v1")(_recorder(code_calls))
    result = await node.evaluate(
        r"(member_1:/m1($input)!'P', member_2:/m2($input)!'P', member_3:/m3($input)!'P', "
        r"pattern:0.0:'ANSWER: \\d+')!/ensemble/combine/v1?reducer=vote&extract=last_number@1",
        env={"input": "2+2?"},
    )
    assert result.text == "COMBINED"
    assert len(code_calls) == 1
    call = code_calls[0]
    assert call.input("member_1").value == texts[0]
    assert call.input("member_2").value == texts[1]
    assert call.input("member_3").value == texts[2]
    assert call.input("pattern") == CodeInput(4, "pattern", "ANSWER: \\d+", 0.0)
    assert dict(call.params) == {"reducer": "vote", "extract": "last_number@1"}


# --- design-review follow-ups (M1–M5, L2, T1–T3) ----------------------------------------


def _typing_recorder(seen: list[list[tuple[str | None, object]]]) -> CodeHandler:
    def handler(call: CodeCall) -> str:
        seen.append([(item.name, item.value) for item in call.inputs])
        return "ok"

    return handler


async def test_handler_transient_intent_error_becomes_permanent() -> None:
    # M1 / T1 (C §13.6): intent_error is PERMANENT, whatever the handler's error says.
    def handler(call: CodeCall) -> str:
        raise Url4Error("busy", code=ErrorCode.INTENT_ERROR, permanent=False)

    with pytest.raises(Url4Error) as info:
        await run("(a='1')!/c", StaticIOLayer(code={"/c": handler}))
    assert info.value.code == ErrorCode.INTENT_ERROR
    assert info.value.permanent is True


async def test_unsupported_mode_starts_no_source() -> None:
    # T2 (R4, E7): an IO with no code port fails the group before its fetched source runs.
    io = RecordingIOLayer({"https://a": "A"})
    with pytest.raises(Url4Error) as info:
        await run("(x:https://a)!/c", io)
    assert info.value.code == ErrorCode.UNSUPPORTED_MODE
    assert io.fetches == []


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        # A nested code broadcast is a collection on BOTH compilation paths (M2).
        (
            "((a='1',b='2')!*/c,'y')!/c",
            [
                (
                    None,
                    [
                        {"source_position": 1, "source_name": "a", "result": "ok"},
                        {"source_position": 2, "source_name": "b", "result": "ok"},
                    ],
                ),
                (None, "y"),
            ],
        ),
        # `$N` and `$name` to an earlier struct sibling take its type (M2, C3).
        (
            "(cfg={k: 'v'}, a=$1, b=$cfg)!/c",
            [("cfg", {"k": "v"}), ("a", {"k": "v"}), ("b", {"k": "v"})],
        ),
    ],
)
async def test_value_kind_is_the_same_on_the_text_and_ast_paths(
    expr: str, expected: list[tuple[str | None, object]]
) -> None:
    # INVARIANT (C3): the value type comes from the source's form, read alike by
    # `run(text)` and `run(build(text))` (T3).
    seen: list[list[tuple[str | None, object]]] = []
    io = StaticIOLayer(code={"/c": _typing_recorder(seen)})
    await run(expr, io)
    await run(build(expr), io)
    assert seen[-1] == expected
    assert [inputs for inputs in seen if len(inputs) == len(expected)] == [expected, expected]


async def test_reference_to_a_failed_optional_sibling_is_unbound() -> None:
    # M3 (B §6.3, C8): in an RDS scope a reference is mechanically required.
    io = StaticIOLayer(code={"/c": _recorder([])})
    with pytest.raises(Url4Error) as info:
        await run("(a:/nope;optional, b=$a)!/c", io)
    assert info.value.code == ErrorCode.UNBOUND_REFERENCE


async def test_reference_to_a_failed_optional_sibling_stays_verbatim_in_llm_mode() -> None:
    # The LLM twin of M3 is unchanged (1.5.1 lenient): the reference stays as text.
    result = await run("(a:/nope;optional, b=$a)!'$b'", StaticIOLayer({}))
    assert result.startswith("$a")


async def test_iteration_rows_reach_code_as_exact_strings() -> None:
    # M4 / T3 (C3, D3): a row that LOOKS like JSON is still the row's result text.
    seen: list[list[tuple[str | None, object]]] = []
    io = StaticIOLayer({"/rows": '["r1","r2"]'}, code={"/c": _typing_recorder(seen)})
    await run("(/rows*()!'[1, 2]')!/c", io)
    assert seen == [[(None, ["[1, 2]", "[1, 2]"])]]


async def test_current_in_an_aggregate_pointer_is_unbound() -> None:
    # L2: `$current` exists only per broadcast source (B §6.1.2).
    io = StaticIOLayer(code={"/c/1": _recorder([])})
    with pytest.raises(Url4Error) as info:
        await run("(a='1')!/c/$current", io)
    assert info.value.code == ErrorCode.UNBOUND_REFERENCE


async def test_index_in_an_iteration_body_pointer_is_the_row_index() -> None:
    # L2: `$index` names the row inside a map, as `$item` does.
    calls: list[CodeCall] = []
    io = StaticIOLayer(
        {"/rows": '["a","b"]'}, code={"/c/0": _recorder(calls), "/c/1": _recorder(calls)}
    )
    await run("/rows*(v=$item)!/c/$index", io)
    assert sorted(call.pointer for call in calls) == ["/c/0", "/c/1"]


async def test_majority_quorum_is_refused_for_an_llm_group() -> None:
    # M5: one quorum parser; `majority` gates code groups only.
    with pytest.raises(ParseError) as info:
        compile_expression("(a='1', b='2')!'go';quorum=majority")
    assert "code-pointer intent" in str(info.value)


# --- C6: the nearest enclosing group decides strictness (row 31) -------------------------


@pytest.mark.parametrize("parse", [False, True])
async def test_prompt_group_nested_in_a_code_group_is_lenient(parse: bool) -> None:
    # C6: the nested prompt group is the NEAREST group of `$c.missing`, so it substitutes
    # leniently (empty), on both compilation paths.
    calls: list[CodeCall] = []
    expr = "(cfg={k: 'v'}, s=(c=$cfg)!'S[$c.missing]')!/c"
    io = StaticIOLayer(code={"/c": _recorder(calls)})
    await run(build(expr) if parse else expr, io)
    value = calls[0].input("s").value
    assert isinstance(value, str)
    assert value.startswith("S[]")


async def test_a_direct_source_of_a_code_group_is_strict() -> None:
    # C6: the code group is the nearest group of `$cfg.missing` → malformed_source.
    io = StaticIOLayer(code={"/c": _recorder([])})
    with pytest.raises(Url4Error) as info:
        await run("(cfg={k: 'v'}, t='$cfg.missing')!/c", io)
    assert info.value.code == ErrorCode.MALFORMED_SOURCE


async def test_a_code_group_nested_in_a_prompt_group_is_strict() -> None:
    # C6, the other way round: strictness follows the inner code group.
    io = StaticIOLayer(code={"/c": _recorder([])})
    with pytest.raises(Url4Error) as info:
        await run("(cfg={k: 'v'}, r=(t='$cfg.missing')!/c)!'$r'", io)
    assert info.value.code == ErrorCode.MALFORMED_SOURCE


# --- P3: named jobs (row 26, owner decisions Q6, Q10) ------------------------------------


async def test_named_job_runs_the_code_mounted_by_name() -> None:
    # Row 26 (B §6 "named job"): a one-word bare intent runs the name-keyed code mount.
    calls: list[CodeCall] = []
    io = StaticIOLayer(code={"score_v1": _recorder(calls)})
    assert await run("(a='1')!score_v1", io) == "COMBINED"
    assert calls[0].pointer == "score_v1"
    assert dict(calls[0].params) == {}
    assert calls[0].inputs == (CodeInput(1, "a", "1", None),)


async def test_named_job_without_a_mount_is_intent_error() -> None:
    with pytest.raises(Url4Error) as info:
        await run("(a='1')!score_v1", StaticIOLayer(code={"/score_v1": _recorder([])}))
    assert info.value.code == ErrorCode.INTENT_ERROR  # the path key is not the name key (Q6)


async def test_a_path_pointer_does_not_find_a_name_key() -> None:
    with pytest.raises(Url4Error) as info:
        await run("(a='1')!/score_v1", StaticIOLayer(code={"score_v1": _recorder([])}))
    assert info.value.code == ErrorCode.INTENT_ERROR


@pytest.mark.parametrize("expr", ["(a='1')!'go'", "(a='1')!summarize this"])
async def test_quoted_and_multi_word_intents_stay_prompts(expr: str) -> None:
    # Row 26: only one bare-value token is a named job; quoted text and prose are prompts.
    calls: list[CodeCall] = []
    io = StaticIOLayer(code={"go": _recorder(calls), "summarize": _recorder(calls)})
    result = await run(expr, io)
    assert calls == []
    assert result.endswith("a: 1")


async def test_named_job_renders_back_bare() -> None:
    assert render(build("(a)!go")) == "('a')!go"
    assert render(build("(a)!'go'")) == "('a')!'go'"


async def test_named_job_group_is_strict() -> None:
    # C6 / row 31: a named job runs code, so its group is an RDS scope.
    with pytest.raises(Url4Error) as info:
        await run(
            "(cfg={k: 'v'}, t='$cfg.missing')!score_v1",
            StaticIOLayer(code={"score_v1": _recorder([])}),
        )
    assert info.value.code == ErrorCode.MALFORMED_SOURCE


async def test_named_job_as_broadcast_and_iteration_reducer() -> None:
    calls: list[CodeCall] = []
    io = StaticIOLayer({"/rows": '["r1","r2"]'}, code={"agg": _recorder(calls)})
    rows = json.loads(await run("(a='1', b='2')!*agg", io))
    assert [row["source_name"] for row in rows] == ["a", "b"]
    await run("(/rows*()!'R $item')!agg", io)
    assert calls[-1].inputs[0].value == ["R r1", "R r2"]


async def test_forwarded_named_job_travels_verbatim() -> None:
    # C9: a named job of a forwarded call goes unquoted, for the receiving node to run.
    io = RecordingIOLayer({}, {"/p": lambda context, intent: "P"})
    await run("(s=/p(ctx)!score_v1)!'$s'", io)
    assert io.fetches[0] == "/p?q=(ctx)!score_v1"


async def test_builder_string_intent_is_url4_syntax() -> None:
    # A builder string intent is parsed like text: one word is a named job.
    assert expr("a", intent="go").intent == NamedJob("go")
    assert expr("a", intent=literal_text("go")).intent != NamedJob("go")


# --- A5 fixed: forwarded prompts keep their quotes (row 28) -------------------------------


class _RemoteNodes:
    """An IO that serves `url4://n/...` by the node `n` itself, in-process."""

    def __init__(self, nodes: dict[str, Url4Node]) -> None:
        self.nodes = nodes
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        authority, _, rest = target.removeprefix("url4://").partition("/")
        return await self.nodes[authority].fetch("/" + rest, relative=True)


async def test_a_forwarded_one_word_prompt_stays_a_prompt_on_the_remote_eval_path() -> None:
    # Row 28: `!'go'` reaches node n's eval path quoted, so n reads a prompt, not a
    # named job (n has no `go` mount; a named-job reading would be intent_error).
    remote = Url4Node("n", outbound=StaticIOLayer({}))
    io = _RemoteNodes({"n": remote})
    result = await run("(s=url4://n/v1(x='1')!'go')!'$s'", io)
    assert io.fetches[0] == "url4://n/v1?q=(x=%271%27)!%27go%27"
    # The remote node merged `go` as a PROMPT (default process: intent, then sources).
    assert result == "go\n\nx: 1\n\ns: go\n\nx: 1"


async def test_a_forwarded_prompt_with_a_newline_travels_unquoted() -> None:
    # Row 28 limit: `quoted-char` has no control character, so this prompt goes raw.
    seen: list[str] = []
    io = RecordingIOLayer(
        {"/nl": "two\nlines"}, {"/p": lambda context, intent: seen.append(intent) or "P"}
    )
    await run("(t=/nl, s=/p(ctx)!'$t')!'$s'", io)
    assert "/p?q=(ctx)!two%0Alines" in io.fetches
    assert seen[0] == "two\nlines"
