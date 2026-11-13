"""PR #1587 review round 15: a nested run and a pre-built graph precheck remote calls too (F1b).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY: as a node operator, a ``url4://`` call in a nested ``run()`` (one started inside a bound
run) or in a pre-built ``Graph`` / ``DagNode`` is refused ``x.remote_node_unsupported`` before any
local endpoint, model or outbound call runs; a client's one allowed hop still runs.
"""

from __future__ import annotations

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import compile_expression
from url4.dag._run import run
from url4.dag.attachments import bind_run_files
from url4.dag.remote_nodes import allow_one_remote_hop, refuse_remote_nodes
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes

MIXED = "(/a(x)!'i', url4://n2.example/v1(x)!'j')!'r'"  # the review probe
LOCAL = "(/a(x)!'i', /b(y)!'j')!'r'"


class _Tripwire:
    """An io that records every call on every port (local endpoints are relative fetches)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return "r"

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(f"fetch_ex {request.target}")
        return FetchResult("r")

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return FetchedBytes(b"r", "text/plain")


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.calls += 1
        return "m"


def _assert_remote_refused(error: ResolutionError) -> None:
    assert (error.code, error.permanent) == (ErrorCode.REMOTE_NODE_UNSUPPORTED, True)


async def _nested(text: str, io: _Tripwire, model: _Model) -> str:
    with bind_run_files(()):
        return await run(text, io, processor="/p", process=model)


# -- blocker 1: a nested run ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_nested_run_refuses_a_remote_sibling_before_any_local_endpoint() -> None:
    io, model = _Tripwire(), _Model()
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(_nested(MIXED, io, model))
    _assert_remote_refused(caught.value)
    assert io.calls == []
    assert model.calls == 0


@pytest.mark.asyncio
async def test_a_nested_run_with_only_local_work_still_runs() -> None:
    io, model = _Tripwire(), _Model()
    await refuse_remote_nodes(_nested(LOCAL, io, model))
    assert {"fetch_ex /a", "fetch_ex /b"} <= {call.split("?")[0] for call in io.calls}


@pytest.mark.asyncio
async def test_a_nested_run_keeps_the_clients_one_hop() -> None:
    io, model = _Tripwire(), _Model()
    text = "(r:0.0:url4://n2.example/v1(x)!'go')!'$r'"
    await allow_one_remote_hop(_nested(text, io, model), ("n2.example", "/v1"))
    assert [call.split("?")[0] for call in io.calls] == ["fetch_ex url4://n2.example/v1"]


# -- blocker 2: a pre-built graph --------------------------------------------------------------


@pytest.mark.parametrize("as_node", [False, True], ids=["graph", "dag-node"])
@pytest.mark.asyncio
async def test_a_prebuilt_mixed_graph_refuses_before_any_local_endpoint(as_node: bool) -> None:
    io, model = _Tripwire(), _Model()
    graph = compile_expression(MIXED)
    target = graph.sink if as_node else graph
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(target, io, process=model))
    _assert_remote_refused(caught.value)
    assert io.calls == []
    assert model.calls == 0


@pytest.mark.asyncio
async def test_a_prebuilt_graph_with_a_remote_call_in_a_verbatim_context_refuses_first() -> None:
    io, model = _Tripwire(), _Model()
    graph = compile_expression("(/a(x)!'i', /b(url4://n2.example/v1(x)!'j')!'d')!'r'")
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(graph, io, process=model))
    _assert_remote_refused(caught.value)
    assert io.calls == []


@pytest.mark.asyncio
async def test_a_prebuilt_local_graph_still_runs() -> None:
    io, model = _Tripwire(), _Model()
    await refuse_remote_nodes(run(compile_expression(LOCAL), io, processor="/p", process=model))
    assert {"fetch_ex /a", "fetch_ex /b"} <= {call.split("?")[0] for call in io.calls}


@pytest.mark.asyncio
async def test_a_prebuilt_graph_keeps_the_clients_one_hop() -> None:
    io, model = _Tripwire(), _Model()
    graph = compile_expression("(r:0.0:url4://n2.example/v1(x)!'go')!'$r'")
    await allow_one_remote_hop(run(graph, io, process=model), ("n2.example", "/v1"))
    assert [call.split("?")[0] for call in io.calls] == ["fetch_ex url4://n2.example/v1"]


@pytest.mark.asyncio
async def test_a_prebuilt_graph_calling_the_hop_twice_refuses_first() -> None:
    io, model = _Tripwire(), _Model()
    graph = compile_expression("(url4://n2.example/v1(x)!'a', url4://n2.example/v1(y)!'b')!'r'")
    with pytest.raises(ResolutionError) as caught:
        await allow_one_remote_hop(run(graph, io, process=model), ("n2.example", "/v1"))
    _assert_remote_refused(caught.value)
    assert io.calls == []
