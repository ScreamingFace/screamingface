"""The URI-intent probe table (CH11), one test per row of PRD §2.3.

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, a URI intent `!/path` is a code pointer that receives the
# group's sources as JSON. The probe rows below were 1.5.1 instruction-text behavior;
# rows 1 to 6 now pin the 2.0 behavior (PRD §7.1, CH11), and their names say so.
"""

from __future__ import annotations

import pytest
from conftest import RecordingIOLayer

from url4.core.context import Context
from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.core.grammar import parse
from url4.core.nodes import Expression, Text
from url4.core.parser import build
from url4.core.render import render
from url4.dag import CodePointerNode, ProcessFn, ProcessNode, compile_expression, run
from url4.dag.node import ExecutionContext
from url4.io.layer import FetchRequest, FetchResult
from url4.observe import NodeStarted, ObservationEvent
from url4.peer.server import Request, Url4Node
from url4.wire.rds import encode_rds_document, encode_rds_target


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
async def test_2_0_combine_endpoint_is_reached_as_a_code_pointer(node: Url4Node) -> None:
    # WHY: url4 2.0 — a relative URI intent is a code-pointer call on this node (PRD row 1, H1).
    expr = f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote"
    assert await run(expr, node) == "COMBINED"


@pytest.mark.asyncio
async def test_2_0_at_in_a_code_pointer_query_is_a_query_tail_character(node: Url4Node) -> None:
    # WHY: url4 2.0 — `@` is a query-tail character of a code pointer (PRD row 2, H4).
    expr = f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote&extract=last_number@1"
    assert await run(expr, node) == "COMBINED"


@pytest.mark.asyncio
async def test_2_0_data_route_intent_is_intent_error(node: Url4Node, wire: list[Request]) -> None:
    # WHY: url4 2.0 — a data route is never code, so it is never read as instructions (E2).
    with pytest.raises(ResolutionError) as err:
        await run(f"({_MEMBERS})!/instr", node)
    assert err.value.code == "intent_error"
    assert wire == []


@pytest.mark.asyncio
async def test_2_0_weight_zero_member_is_delivered_to_the_code_pointer(
    node: Url4Node, wire: list[Request]
) -> None:
    # WHY: url4 2.0 — weight is attribution metadata, so a weight-0.0 source is an input (H3).
    await run("(member_1:/a($input)!'P', member_2:0.0:/b($input)!'P')!/claude", node)
    assert wire[-1].mode == "rds"
    assert wire[-1].inputs == {"member_1": "A says 4", "member_2": "B says 5"}


@pytest.mark.asyncio
async def test_2_0_named_sources_to_a_data_route_are_intent_error(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: url4 2.0 — the process hook is not called for an RDS group (E2, PRD §2.4).
    with pytest.raises(ResolutionError) as err:
        await run("(x='hello', y='world')!/instr", node, process=_recording_process(hook_calls))
    assert err.value.code == "intent_error"
    assert hook_calls == []


@pytest.mark.asyncio
async def test_2_0_relative_reducer_path_is_one_code_pointer_call(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: url4 2.0 — an iteration reducer that is a relative URI is one code-pointer call with
    # the row array as `$1` (PRD row 6 of CH11, D8). The reducer path is no longer a prompt.
    seen: list[Request] = []

    @node.endpoint("/reduce")
    async def reduce(request: Request) -> str:
        seen.append(request)
        return "REDUCED"

    result = await run("(/rows*()!'R $item')!/reduce", node, process=_recording_process(hook_calls))
    assert result == "REDUCED"
    assert [(r.mode, r.inputs) for r in seen] == [("rds", {"$1": ["R r1", "R r2"]})]
    assert all(intent != "/reduce" for _, intent in hook_calls)


def test_char_1_5_1_quote_escapes_round_trip_and_a_doubled_quote_is_malformed() -> None:
    node = build("(a,b)!'it\\'s \\\\d+'")
    assert isinstance(node, Expression)
    assert node.intent == Text("it's \\d+")
    assert build(render(node)) == node
    with pytest.raises(ParseError):
        build("(a,b)!'it''s'")


def _code_node(calls: list[Request]) -> Url4Node:
    """A node whose code pointers record every request they receive (2.0 rows)."""
    n = Url4Node("t", default_processor="/claude")

    @n.endpoint("/a")
    async def member_a(request: Request) -> str:
        return "A says 4"

    @n.endpoint("/b")
    async def member_b(request: Request) -> str:
        return "B says 5"

    @n.endpoint("/combine")
    async def combine(request: Request) -> str:
        calls.append(request)
        return "COMBINED"

    @n.endpoint("/ensemble/combine/v1")
    async def vote(request: Request) -> str:
        calls.append(request)
        return "COMBINED"

    @n.endpoint("/claude")
    async def claude(request: Request) -> str:
        calls.append(request)
        return "CLAUDE"

    n.data("/doc", "DOC")
    n.data("/rows", '["r1", "r2"]')
    n.data("/errbody", '{"error": "boom"}')
    n.data("/instr", "INSTRUCTION TEXT")
    return n


@pytest.fixture()
def calls() -> list[Request]:
    return []


@pytest.fixture()
def code(calls: list[Request]) -> Url4Node:
    return _code_node(calls)


class _Events:
    """Collects every observation event, in emission order."""

    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)


@pytest.mark.parametrize(
    "intent", ["https://code.example/score.py", "http://code.example/x", "s3://bucket/key"]
)
@pytest.mark.asyncio
async def test_a_non_url4_scheme_intent_is_refused_before_any_fetch(intent: str) -> None:
    # WHY: PRD row 3 (E7) — the refusal is at compile, so no source is fetched.
    io = RecordingIOLayer()
    with pytest.raises(ParseError) as err:
        await run(f"(https://a)!{intent}", io)
    assert err.value.code == ErrorCode.UNSUPPORTED_MODE
    assert err.value.permanent is True
    assert io.fetches == []


@pytest.mark.asyncio
async def test_named_sources_are_keyed_by_name_in_source_order(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 6 (H2) — each key is the source name, and the keys keep the source order.
    await run(f"({_MEMBERS})!/combine", code)
    assert list(calls[0].inputs or {}) == ["member_1", "member_2"]


@pytest.mark.asyncio
async def test_an_unnamed_source_is_keyed_by_its_one_based_position(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 6 (D3) — the keys are member_1, $2 and $3 in order.
    await run("(member_1:/a($input)!'P', 'free text', /doc)!/combine", code)
    assert calls[0].inputs == {"member_1": "A says 4", "$2": "free text", "$3": "DOC"}


@pytest.mark.asyncio
async def test_a_weight_zero_source_is_delivered_to_the_code_pointer(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 13 (H3) — the unescaped text of a weight-0.0 source is delivered.
    await run(r"(member_1:/a($input)!'P', extract_pattern:0.0:'ANSWER: \\d+')!/combine", code)
    assert calls[0].inputs == {"member_1": "A says 4", "extract_pattern": "ANSWER: \\d+"}


@pytest.mark.asyncio
async def test_a_failed_optional_source_is_absent_from_the_inputs(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 15 (D1) — no key and no null for a failed ;optional source.
    await run(
        "(member_1:/nope($input)!'P';optional, member_2:/b($input)!'P')!/combine;quorum=1", code
    )
    assert calls[0].inputs == {"member_2": "B says 5"}


def test_duplicate_source_names_are_malformed_for_a_code_pointer() -> None:
    # WHY: PRD row 6 (D12) — one document cannot hold two equal keys, so the group does not compile.
    with pytest.raises(ParseError) as err:
        compile_expression("(a='1', a='2')!/combine")
    assert err.value.code == ErrorCode.MALFORMED_SOURCE
    assert err.value.permanent is True


def test_duplicate_source_names_still_compile_for_a_prompt_intent() -> None:
    # WHY: PRD row 6 (D12) — an LLM-mode group keeps today's behavior.
    compile_expression("(a='1', a='2')!'go'")


@pytest.mark.asyncio
async def test_a_struct_source_arrives_as_a_json_object(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 7 (D5) — a struct-object source is a JSON object.
    await run("(cfg={k: 'v', n: 3})!/combine", code)
    assert calls[0].inputs == {"cfg": {"k": "v", "n": 3}}


@pytest.mark.asyncio
async def test_a_named_iteration_source_arrives_as_a_json_array(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 7 (D4) — an iteration expression is a JSON array of its rows.
    await run("(r=/rows*()!'R $item', 'x')!/combine", code)
    assert calls[0].inputs == {"r": ["R r1", "R r2"], "$2": "x"}


@pytest.mark.asyncio
async def test_a_broadcast_group_source_arrives_as_a_json_array(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 7 (D4) — a broadcast group, held by a lazy binding, keeps its JSON array
    # through spawn.
    await run("(r=(a='1', b='2')!*'x')!/combine", code)
    rows = (calls[0].inputs or {})["r"]
    assert isinstance(rows, list)
    assert [row["source_name"] for row in rows if isinstance(row, dict)] == ["a", "b"]


@pytest.mark.asyncio
async def test_an_unnamed_expansion_gives_one_positional_key_per_element(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 7 (D6) — each element of an unnamed ;expand source has its own $k key.
    await run("(*/rows, 'x')!/combine", code)
    assert calls[0].inputs == {"$1": "r1", "$2": "r2", "$3": "x"}


@pytest.mark.asyncio
async def test_a_named_expansion_arrives_as_one_json_array(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 7 (D4) — a named ;expand source is one array under its name.
    await run("(r=/rows;expand, 'x')!/combine", code)
    assert calls[0].inputs == {"r": ["r1", "r2"], "$3": "x"}


@pytest.mark.asyncio
async def test_a_fetched_body_that_holds_json_text_stays_a_string(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 7 (D4) — collection-ness comes from the expression, never from the content.
    await run("(d=/rows, 'x')!/combine", code)
    assert calls[0].inputs == {"d": '["r1", "r2"]', "$2": "x"}


def test_a_code_pointer_intent_compiles_to_a_code_pointer_node_over_the_group_slots() -> None:
    # WHY: PRD row 9 — the group's slots move into a CodePointerNode (CH9 flips here).
    graph = compile_expression("(a='1', b='2')!/combine")
    assert isinstance(graph.sink, CodePointerNode)
    assert graph.sink.slots == (("a", False), ("b", False))
    assert graph.sink.pointer.path == "/combine"


@pytest.mark.asyncio
async def test_a_group_calls_its_code_pointer_exactly_once(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 12 (H1) — the code pointer runs once and its return value is the group's value.
    result = await run(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote", code)
    assert result == "COMBINED"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_the_code_pointer_receives_the_named_inputs_and_query_params(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 12 (H1) — the handler sees mode "rds", the named inputs, the params and
    # intent "".
    await run(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote", code)
    (request,) = calls
    assert request.mode == "rds"
    assert request.inputs == {"member_1": "A says 4", "member_2": "B says 5"}
    assert request.params == {"reducer": "vote"}
    assert request.intent == ""


@pytest.mark.asyncio
async def test_a_code_pointer_run_never_calls_the_process_hook(
    code: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: PRD row 12 (H1) — no process hook and no processor route for an RDS group.
    await run(f"({_MEMBERS})!/combine", code, process=_recording_process(hook_calls))
    assert hook_calls == []


@pytest.mark.asyncio
async def test_a_mixed_group_makes_one_code_pointer_call_with_every_source(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 14 (H5) — calls and a quoted weight-0.0 source make one call, not a fan-out.
    await run(f"({_MEMBERS}, q:0.0:'lit')!/combine", code)
    assert len(calls) == 1
    assert list(calls[0].inputs or {}) == ["member_1", "member_2", "q"]


@pytest.mark.asyncio
async def test_a_quorum_not_met_fails_before_the_code_pointer_runs(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 15 (E6) — every optional member failed and quorum=1 needs one.
    expr = (
        "(member_1:/nope($input)!'P';optional, member_2:/nope2($input)!'P';optional)"
        "!/combine;quorum=1"
    )
    with pytest.raises(ResolutionError) as err:
        await run(expr, code)
    assert err.value.code == "quorum_not_met"
    assert calls == []


@pytest.mark.asyncio
async def test_a_vacuous_quorum_calls_the_code_pointer_with_no_inputs(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 15 (D9) — quorum=all with no resolved source still calls, with an empty document.
    await run(
        "(member_1:/nope($input)!'P';optional, member_2:/nope2($input)!'P';optional)!/combine",
        code,
    )
    assert calls[0].inputs == {}


@pytest.mark.asyncio
async def test_a_required_source_failure_fails_the_group_without_a_call(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 16 (E5) — a required source that fails fails the group, and the code
    # pointer is not run.
    with pytest.raises(ResolutionError) as err:
        await run("(member_1:/nope($input)!'P', member_2:/b($input)!'P')!/combine", code)
    assert err.value.code == "endpoint_not_found"
    assert calls == []


@pytest.mark.asyncio
async def test_an_unknown_code_pointer_path_is_intent_error(code: Url4Node) -> None:
    # WHY: PRD row 17 (E1) — no endpoint at the path is intent_error, permanent, and names the path.
    with pytest.raises(ResolutionError) as err:
        await run(f"({_MEMBERS})!/nope", code)
    assert err.value.code == ErrorCode.INTENT_ERROR
    assert err.value.permanent is True
    assert "/nope" in str(err.value)


@pytest.mark.asyncio
async def test_a_handler_value_error_is_intent_error(code: Url4Node) -> None:
    # WHY: PRD row 18 (E3) — a handler that raises a non-url4 error is intent_error, permanent.
    @code.endpoint("/bad")
    async def bad(request: Request) -> str:
        raise ValueError("bad input")

    with pytest.raises(ResolutionError) as err:
        await run(f"({_MEMBERS})!/bad", code)
    assert err.value.code == ErrorCode.INTENT_ERROR
    assert err.value.permanent is True


@pytest.mark.asyncio
async def test_a_handler_url4_error_keeps_its_own_code_and_permanence(code: Url4Node) -> None:
    # WHY: PRD row 18 (E3) — a handler's own Url4Error passes through with its code and permanence.
    @code.endpoint("/custom")
    async def custom(request: Request) -> str:
        raise Url4Error("custom failure", code="x.custom", permanent=False)

    with pytest.raises(Url4Error) as err:
        await run(f"({_MEMBERS})!/custom", code)
    assert err.value.code == "x.custom"
    assert err.value.permanent is False


@pytest.mark.asyncio
async def test_an_error_body_from_a_source_is_delivered_not_sniffed(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 19 (E4) — a source that answers with an error object is delivered as text.
    await run("(e=/errbody, 'x')!/combine", code)
    assert calls[0].inputs == {"e": '{"error": "boom"}', "$2": "x"}


@pytest.mark.asyncio
async def test_an_unknown_processor_does_not_touch_a_code_pointer_group(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 22 (D10) — processor= names no route for an RDS group, so the run succeeds.
    assert await run("(a='1')!/combine", code, processor="unknown-id") == "COMBINED"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_mixed_run_uses_the_processor_route_only_for_the_llm_group(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 22 (D10) — a fan-out LLM group uses the processor route, and the RDS group
    # above it does not. The LLM group is the source of the RDS group, so it runs first.
    expr = "(x=(member_1:/a($input)!'P', member_2:/b($input)!'P')!'Pick best', b='2')!/combine"
    await run(expr, code, processor="/claude")
    assert [(request.path, request.mode) for request in calls] == [
        ("/claude", "llm"),
        ("/combine", "rds"),
    ]


@pytest.mark.asyncio
async def test_the_eval_path_runs_a_code_pointer_group_on_the_node(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: PRD row 25 (D11) — GET /v1?q=(…)!/combine evaluates the group and calls the node's
    # own /combine.
    assert await code.fetch("/v1?q=(a='1', b='2')!/combine", relative=True) == "COMBINED"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_code_pointer_group_starts_a_code_pointer_node(code: Url4Node) -> None:
    # WHY: PRD row 28 — the node kind is the observable signal that the group ran as a code pointer.
    observer = _Events()
    await run("(a='1')!/combine", code, observer=observer)
    started = [e.node_kind for e in observer.events if isinstance(e, NodeStarted)]
    assert "CodePointerNode" in started


@pytest.mark.asyncio
async def test_a_url4_code_pointer_is_one_outbound_fetch_of_kind_url4() -> None:
    # WHY: PRD row 23 (H8) — url4://authority/path?query sends the document to the remote node once.
    io = RecordingIOLayer()
    await run("(a='1')!url4://scorer.example/score/v1?k=2", io)
    document = encode_rds_document({"a": "1"})
    assert io.fetches == [f"url4://scorer.example{encode_rds_target('/score/v1', 'k=2', document)}"]


@pytest.mark.parametrize(
    "text",
    ["/p('ctx')!https://h/instr", "/p('ctx')!/code?x=a,b", "/p('ctx')!url4://host"],
)
def test_a_call_with_a_uri_intent_compiles_on_the_ast_path_as_on_the_text_path(text: str) -> None:
    # WHY: PRD P16 — a call's own intent is out of scope for code-pointer classification, so the
    # parse-tree path compiles the same texts the text path compiles.
    compile_expression(parse(text))
    compile_expression(text)


@pytest.mark.asyncio
async def test_a_substituted_code_pointer_path_with_a_query_is_malformed_source(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: C2 / F3 — a `$name` value that carries a query cannot turn the path into a second
    # query-tail; the resolved path is checked before any call.
    ctx = ExecutionContext(code, scope=Context.root().child(p="combine?reducer=evil&x"))
    with pytest.raises(ParseError) as err:
        await run("(a='1')!/$p?reducer=vote", ctx=ctx)
    assert err.value.code == ErrorCode.MALFORMED_SOURCE
    assert calls == []


@pytest.mark.asyncio
async def test_a_substituted_code_pointer_path_that_is_a_plain_path_is_called(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: C2 / F3 — a `$name` that resolves to a plain path still reaches its code pointer.
    ctx = ExecutionContext(code, scope=Context.root().child(p="combine"))
    assert await run("(a='1')!/$p?reducer=vote", ctx=ctx) == "COMBINED"
    assert [request.mode for request in calls] == ["rds"]


@pytest.mark.asyncio
async def test_a_handler_endpoint_not_found_keeps_its_own_transient_code(code: Url4Node) -> None:
    # WHY: F4 (C7) — a handler's own endpoint_not_found is transient; the call must not turn it
    # into a permanent intent_error.
    @code.endpoint("/inner")
    async def inner(request: Request) -> str:
        raise ResolutionError("inner", code=ErrorCode.ENDPOINT_NOT_FOUND, permanent=False)

    with pytest.raises(ResolutionError) as err:
        await run(f"({_MEMBERS})!/inner", code)
    assert err.value.code == "endpoint_not_found"
    assert err.value.permanent is False


@pytest.mark.asyncio
async def test_a_code_pointer_quorum_not_met_is_permanent(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: F6 (C7) — the same inputs fail the same way, so a quorum miss here is permanent.
    with pytest.raises(ResolutionError) as err:
        await run("(/nope;optional)!/combine;quorum=1", code)
    assert err.value.code == "quorum_not_met"
    assert err.value.permanent is True
    assert calls == []


@pytest.mark.asyncio
async def test_2_0_combine_endpoint_request_is_rds_mode(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: N5 — a code-pointer call on a combine path reaches its handler as an rds request.
    await run(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote", code)
    (request,) = calls
    assert request.mode == "rds"
    assert request.params == {"reducer": "vote"}


@pytest.mark.asyncio
async def test_2_0_at_in_a_code_pointer_query_is_an_rds_param_value(
    code: Url4Node, calls: list[Request]
) -> None:
    # WHY: N5 — `@` in a query-tail value reaches the handler intact, in rds mode.
    await run(f"({_MEMBERS})!/ensemble/combine/v1?reducer=vote&extract=last_number@1", code)
    (request,) = calls
    assert request.mode == "rds"
    assert request.params["extract"] == "last_number@1"


class _KindRecordingIO(RecordingIOLayer):
    """A recording layer that also records the request kind of every fetch (N5)."""

    def __init__(self) -> None:
        super().__init__()
        self.kinds: list[str] = []

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.kinds.append(request.kind)
        return FetchResult(await self.fetch(request.target, relative=request.relative))


@pytest.mark.asyncio
async def test_a_url4_code_pointer_fetch_is_kind_url4() -> None:
    # WHY: N5 — the remote code-pointer call is a url4-kind fetch, so URL4 rules apply to it.
    io = _KindRecordingIO()
    await run("(a='1')!url4://scorer.example/score/v1?k=2", io)
    assert io.kinds == ["url4"]


def test_a_group_with_a_legacy_path_intent_keeps_the_1_5_1_process_sink() -> None:
    # WHY: N5 — `!/p(c)!x` is an expression, not a code pointer, so the group keeps 1.5.1's shape.
    assert isinstance(compile_expression("(a='1', b='2')!/p(c)!x").sink, ProcessNode)


def test_a_reducer_path_call_with_no_inputs_keeps_the_1_5_1_process_sink() -> None:
    # WHY: N5 — `/reduce()` is an expression (LEGACY) intent, so the group keeps 1.5.1's shape.
    assert isinstance(compile_expression("(a='1')!/reduce()").sink, ProcessNode)
