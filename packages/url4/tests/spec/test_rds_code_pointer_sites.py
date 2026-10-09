"""The code-pointer call at the broadcast and iteration-reducer sites (PRD D7, D8; rows 20, 21).

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, `(a, b, c)!*/score` calls `/score` once per resolved source, and
# `(rows)!/reduce` calls `/reduce` once with the whole row array, so a deterministic scorer or
# reducer gets its inputs as JSON and no model sees them.
#
# INVARIANT: neither site reads the processor route or calls the process hook (PRD D10).
"""

from __future__ import annotations

import json

import pytest
from conftest import RecordingIOLayer

from url4.core.context import Context
from url4.core.errors import ParseError, ResolutionError
from url4.dag import ProcessFn, compile_expression, run
from url4.peer.server import Request, Url4Node
from url4.wire.rds import decode_q_payload, decode_rds_document


@pytest.fixture()
def calls() -> list[Request]:
    return []


@pytest.fixture()
def hook_calls() -> list[tuple[str, str | None]]:
    return []


@pytest.fixture()
def node(calls: list[Request]) -> Url4Node:
    n = Url4Node("t", default_processor="/claude")

    @n.endpoint("/score")
    async def score(request: Request) -> str:
        calls.append(request)
        return f"score:{(request.inputs or {})['current']}"

    @n.endpoint("/reduce")
    async def reduce(request: Request) -> str:
        calls.append(request)
        return "REDUCED"

    @n.endpoint("/claude")
    async def claude(request: Request) -> str:
        calls.append(request)
        return "CLAUDE"

    n.data("/rows", '["r1", "r2"]')
    return n


def _recording_process(hook_calls: list[tuple[str, str | None]]) -> ProcessFn:
    async def process(sources: str, intent: str | None, scope: Context) -> str:
        hook_calls.append((sources, intent))
        return f"{intent}\n\n{sources}" if intent and sources else (intent or sources or "")

    return process


def _currents(calls: list[Request]) -> list[str]:
    """Each call's ``current`` input, sorted; every call must carry exactly that one key."""
    currents: list[str] = []
    for call in calls:
        assert call.mode == "rds"
        assert call.inputs is not None
        assert list(call.inputs) == ["current"]
        currents.append(str(call.inputs["current"]))
    return sorted(currents)


@pytest.mark.asyncio
async def test_2_0_broadcast_calls_the_code_pointer_once_per_resolved_source(
    node: Url4Node, calls: list[Request]
) -> None:
    # WHY: url4 2.0 — one call per resolved source; a failed optional source has no call and
    # no row, and the surviving rows keep their source positions (PRD D7).
    result = await run("(a='1', b=/nope;optional, c='3')!*/score", node)
    assert _currents([c for c in calls if c.path == "/score"]) == ["1", "3"]
    assert json.loads(result) == [
        {"source_position": 1, "source_name": "a", "result": "score:1"},
        {"source_position": 3, "source_name": "c", "result": "score:3"},
    ]


@pytest.mark.asyncio
async def test_2_0_broadcast_with_a_failed_required_source_fails_without_a_call(
    node: Url4Node, calls: list[Request]
) -> None:
    # WHY: url4 2.0 — a required source that fails fails the run, and the code pointer is not
    # called for it (PRD E5).
    with pytest.raises(ResolutionError) as err:
        await run("(a='1', b=/nope, c='3')!*/score", node)
    assert err.value.code == "endpoint_not_found"
    assert [c.path for c in calls if c.path == "/score"] == []


@pytest.mark.asyncio
async def test_2_0_broadcast_never_calls_the_process_hook_or_the_processor(
    node: Url4Node, calls: list[Request], hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: url4 2.0 — a broadcast code pointer is a code call, not a prompt (PRD D10).
    await run(
        "(a='1', c='3')!*/score", node, processor="/claude", process=_recording_process(hook_calls)
    )
    assert hook_calls == []
    assert [c.path for c in calls] == ["/score", "/score"]


@pytest.mark.asyncio
async def test_2_0_iteration_reducer_relative_uri_is_one_call_with_the_row_array(
    node: Url4Node, calls: list[Request], hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: url4 2.0 — an iteration reducer that is a relative URI is one code-pointer call
    # with the rows as `$1` (PRD row 21, D8). The reducer text never reaches the process hook.
    result = await run("(/rows*()!'R $item')!/reduce", node, process=_recording_process(hook_calls))
    assert result == "REDUCED"
    reduce_calls = [c for c in calls if c.path == "/reduce"]
    assert [(c.mode, c.inputs) for c in reduce_calls] == [("rds", {"$1": ["R r1", "R r2"]})]
    assert all(intent != "/reduce" for _, intent in hook_calls)


@pytest.mark.asyncio
async def test_2_0_remote_iteration_reducer_is_one_url4_fetch_with_the_row_array() -> None:
    # WHY: url4 2.0 — a url4:// reducer is a remote code pointer: one outbound fetch whose
    # document holds the rows as `$1` (PRD D8, contracts C4).
    io = RecordingIOLayer({"/rows": '["r1", "r2"]'})
    await run("(/rows*()!'R $item')!url4://n/reduce", io)
    remote = [target for target in io.fetches if target.startswith("url4://")]
    assert len(remote) == 1
    path, _, raw_q = remote[0].partition("?q=")
    assert path == "url4://n/reduce"
    document = decode_q_payload(raw_q)
    assert document is not None
    assert decode_rds_document(document) == {"$1": ["R r1", "R r2"]}


@pytest.mark.asyncio
async def test_2_0_unsupported_scheme_reducer_compiles_and_fails_at_run_time(
    node: Url4Node,
) -> None:
    # WHY: url4 2.0 — an https:// reducer is refused with unsupported_mode (PRD P2). The
    # iteration reducer is read at run time, so the graph still validates.
    expr = "(/rows*()!'R $item')!https://x/reduce"
    compile_expression(expr).validate()
    with pytest.raises(ParseError) as err:
        await run(expr, node)
    assert err.value.code == "unsupported_mode"
    assert err.value.permanent is True
