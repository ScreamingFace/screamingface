"""Remote-node calls are refused in a node context in v1 (#1450 spec C6 / F1b, ``OME-1539``).

FEATURE: file inputs for url4 (epic ``OME-1529``); the remote-node half of F1b.
STORY: as a node operator, an expression my node evaluates can never make my node call another
node, because nothing yet authenticates my node to it; it fails ``x.remote_node_unsupported``
before any DNS lookup or connection.

INVARIANT (owner decisions, Sergey 2026-10-26): the refusal applies to remote EXPRESSIONS
(``RemoteFetchNode``) in a node context: every evaluation a ``Url4Node`` runs, and everything a
``Client(node=...)`` evaluates except the one outer hop it builds itself. Bare ``url4.run()``
keeps today's behaviour; plain ``url4://host/path`` data fetches stay with the transport guard;
a remote blob ref keeps ``x.remote_blob_unsupported``.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import ExecutionContext, RemoteFetchNode, WebFetchNode
from url4.dag._run import run
from url4.dag.nodes.blob import BlobRefNode
from url4.dag.remote_nodes import allow_one_remote_hop, check_remote_node, refuse_remote_nodes
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer
from url4.peer.client import Client
from url4.peer.server import Url4Node

PNG = b"\x89PNG\r\n\x1a\n-remote-node-1539"
HEX = hashlib.sha256(PNG).hexdigest()
TOKEN = f"blob:sha256/{HEX}"
C6 = f"(url4://n2.example/v1(img:src={TOKEN})!'Describe')!'Summarize'"


class _Tripwire:
    """An outbound io that records every call of any kind: a refusal must leave it empty."""

    def __init__(self, fetch_map: dict[str, str] | None = None) -> None:
        self.calls: list[str] = []
        self._map = fetch_map or {}

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return self._map.get(target, "TRIPPED")

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(f"fetch_ex {request.target}")
        return FetchResult(self._map.get(request.target, "TRIPPED"))

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return FetchedBytes(b"TRIPPED", media_type=None)


class _Peers:
    """The client's io: serves ``url4://<name>/…`` by that in-process ``Url4Node``."""

    def __init__(self, nodes: dict[str, Url4Node]) -> None:
        self.nodes = nodes
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        authority, _, rest = target.removeprefix("url4://").partition("/")
        return await self.nodes[authority].fetch("/" + rest, relative=True)


def _assert_remote_node_unsupported(exc: ResolutionError) -> None:
    assert (exc.code, exc.permanent) == (ErrorCode.REMOTE_NODE_UNSUPPORTED, True)
    assert exc.code == "x.remote_node_unsupported"


# --- the node context ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c6_through_a_url4_node_is_refused_before_any_io() -> None:
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound)
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(C6)
    _assert_remote_node_unsupported(caught.value)
    # INVARIANT: no DNS, no connection, no store read: the outbound io was never touched.
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_c6_on_the_node_eval_path_is_refused_too() -> None:
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound)
    with pytest.raises(ResolutionError) as caught:
        await node.fetch("/v1?q=" + C6, relative=True)
    _assert_remote_node_unsupported(caught.value)
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_node_refuses_its_own_authority_as_well() -> None:
    # Any url4:// remote expression is a remote-node call, the node's own name included.
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound)
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate("(s=url4://n1/v1(x='1')!'go')!'$s'")
    _assert_remote_node_unsupported(caught.value)
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_relative_call_at_a_node_is_unchanged() -> None:
    node = Url4Node("n1", outbound=_Tripwire())
    node.endpoint("/echo")(lambda request: f"echo {request.intent}")
    result = await node.evaluate("(s:0:/echo(x)!'go')!'$s'")
    assert result.text == "echo go"


@pytest.mark.asyncio
async def test_a_remote_blob_ref_at_a_node_stays_remote_blob_unsupported() -> None:
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound)
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"(img:src=url4://n2.example/blob/sha256/{HEX})!'Describe'")
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_BLOB_UNSUPPORTED,
        True,
    )
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_plain_url4_data_fetch_at_a_node_is_not_refused_here() -> None:
    # A url4://host/path data fetch is the transport guard's (F1b), not this refusal.
    outbound = _Tripwire({"url4://n2.example/data": "DATA"})
    node = Url4Node("n1", outbound=outbound)
    result = await node.evaluate("(d:0:url4://n2.example/data)!'$d'")
    assert result.text == "DATA"
    assert outbound.calls == ["fetch_ex url4://n2.example/data"]


# --- the policy itself ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_fetch_node_under_refusal_raises_with_zero_io() -> None:
    io = _Tripwire()
    node = RemoteFetchNode("n2.example", "/v1", context="x", deps={})
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(node.resolve({}, ExecutionContext(io)))
    _assert_remote_node_unsupported(caught.value)
    assert io.calls == []


@pytest.mark.asyncio
async def test_web_fetch_of_a_url4_target_under_refusal_is_unaffected() -> None:
    io = StaticIOLayer(fetch_map={"url4://host/path": "U4"})
    assert await refuse_remote_nodes(run(WebFetchNode("url4://host/path"), io)) == "U4"


def test_without_a_policy_nothing_is_refused() -> None:
    check_remote_node("n2.example", "/v1")  # bare run(): today's behaviour


@pytest.mark.asyncio
async def test_the_one_hop_allowance_is_single_use_and_exact() -> None:
    async def probe() -> list[str]:
        seen: list[str] = []
        for authority, path in [("n2", "/v2"), ("n3", "/v1"), ("n2", "/v1"), ("n2", "/v1")]:
            try:
                check_remote_node(authority, path)
                seen.append(f"ok {authority}{path}")
            except ResolutionError as exc:
                seen.append(f"{exc.code} {authority}{path}")
        return seen

    assert await allow_one_remote_hop(probe(), ("n2", "/v1")) == [
        "x.remote_node_unsupported n2/v2",
        "x.remote_node_unsupported n3/v1",
        "ok n2/v1",
        "x.remote_node_unsupported n2/v1",
    ]


@pytest.mark.asyncio
async def test_the_policy_is_reset_after_the_evaluation() -> None:
    with pytest.raises(ResolutionError):
        await refuse_remote_nodes(_raise_if_refused())
    check_remote_node("n2.example", "/v1")  # outside the evaluation: no policy again


async def _raise_if_refused() -> None:
    check_remote_node("n2.example", "/v1")


# --- the client --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_clients_own_outer_hop_still_works() -> None:
    io = _Peers({"n": Url4Node("n", outbound=_Tripwire())})
    result = await Client(io, node="url4://n/v1").evaluate("(x='1')!'go'")
    assert result.text.startswith("go")
    assert io.fetches[0].startswith("url4://n/v1?q=")


@pytest.mark.asyncio
async def test_a_url4_call_nested_in_a_client_wrapped_expression_is_refused() -> None:
    outbound = _Tripwire()
    io = _Peers({"n": Url4Node("n", outbound=outbound)})
    with pytest.raises(ResolutionError) as caught:
        await Client(io, node="url4://n/v1").evaluate(C6)
    _assert_remote_node_unsupported(caught.value)
    # The outer hop reached node n; n refused the nested call with no outbound I/O.
    assert len(io.fetches) == 1
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_local_client_evaluation_keeps_bare_run_behaviour() -> None:
    io_calls: list[str] = []

    class _Rec(StaticIOLayer):
        async def fetch(self, target: str, *, relative: bool) -> str:
            io_calls.append(target)
            return "R"

    result = await Client(_Rec()).evaluate("(s:0:url4://n2/v1(x)!'go')!'$s'")
    assert result.text == "R"
    assert io_calls and io_calls[0].startswith("url4://n2/v1?q=")


@pytest.mark.asyncio
async def test_bare_run_still_forwards_a_remote_expression() -> None:
    io = _Tripwire({"url4://n2/v1?q=(x)!%27go%27": "FORWARDED"})
    assert await run("(s:0:url4://n2/v1(x)!'go')!'$s'", io=io) == "FORWARDED"
    assert io.calls == ["fetch_ex url4://n2/v1?q=(x)!%27go%27"]


@pytest.mark.asyncio
async def test_a_blob_ref_node_under_refusal_keeps_its_own_code() -> None:
    io = _Tripwire()
    ref = BlobRefNode.remote(f"url4://n2.example/blob/sha256/{HEX}")
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(ref.resolve({}, ExecutionContext(io)))
    assert caught.value.code == ErrorCode.REMOTE_BLOB_UNSUPPORTED
    assert io.calls == []
