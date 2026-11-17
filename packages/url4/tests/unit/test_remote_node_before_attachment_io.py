"""A remote-node call is refused BEFORE any run-start attachment I/O (C6).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 4,
owner decision Sergey 2026-11-04).
STORY: as a node operator, an expression my node evaluates that names an attachment source AND a
``url4://`` remote-node call fails ``x.remote_node_unsupported`` with zero outbound I/O — the
run-start attachment phase (blob reads, ``https://`` flights, collection admission) never runs
first. The client's one allowed hop is checked without being spent.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.core.grammar import parse
from url4.dag._run import run
from url4.dag.attachments import scan_sources
from url4.dag.remote_nodes import allow_one_remote_hop, precheck_remote_nodes, refuse_remote_nodes
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.peer.server import Url4Node

PNG = b"\x89PNG\r\n\x1a\n-before-attachment-io"
HEX = hashlib.sha256(PNG).hexdigest()
IMG = "https://img.example/a.png"
REVIEW_REPRO = f"(src={IMG};accept=image/png, s=url4://n2/v1(x)!go)!d"


class _Tripwire:
    """Records every outbound call of any kind; a refusal must leave it empty."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return "remote says hi"

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(f"fetch_ex {request.target}")
        return FetchResult("remote says hi")

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return FetchedBytes(PNG, "image/png")


def _assert_refused(exc: ResolutionError) -> None:
    assert (exc.code, exc.permanent) == (ErrorCode.REMOTE_NODE_UNSUPPORTED, True)


@pytest.mark.asyncio
async def test_the_review_repro_makes_zero_fetches_on_a_node() -> None:
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound)
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(REVIEW_REPRO)
    _assert_refused(caught.value)
    assert outbound.calls == []


@pytest.mark.parametrize(
    "text",
    [
        f"((src={IMG};accept=image/png)!'a', (url4://n2/v1(x)!go)!'b')!'r'",  # a nested group
        f"(src={IMG};accept=image/png, url4://n2/v1(x)!go*($item)!'d')!'r'",  # a collection
        f"(src={IMG};accept=image/png, ('a')*(url4://n2/v1($item)!go)!'d')!'r'",  # a row body
        f"(src={IMG};accept=image/png, /m(url4://n2/v1(x)!go)!'d')!'r'",  # a call context
        f"(url4://n2/v1(x)!go, src={IMG};accept=image/png)!d",  # before the attachment
    ],
)
@pytest.mark.asyncio
async def test_a_remote_call_anywhere_in_the_run_refuses_before_the_attachment_flight(
    text: str,
) -> None:
    outbound = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(text, outbound))
    _assert_refused(caught.value)
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_local_blob_read_does_not_happen_before_the_refusal() -> None:
    node = Url4Node("n1", outbound=_Tripwire())
    reads: list[str] = []

    @node.data(f"/blob/sha256/{HEX}", media_type="image/png")
    def blob() -> str:
        reads.append("read")
        return "never"

    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"(src=/blob/sha256/{HEX}, s=url4://n2/v1(x)!go)!d")
    _assert_refused(caught.value)
    assert reads == []


def test_the_scan_records_every_remote_call_but_not_one_inside_a_remote_context() -> None:
    scan = scan_sources(parse("(url4://n2/v1(url4://n3/v9(y)!z)!go, /m(url4://n4/v2(x)!w)!'d')!r"))
    assert scan.remote_nodes == (("n2", "/v1"), ("n4", "/v2"))


# -- the client's one hop: checked, never spent -------------------------------------------


@pytest.mark.asyncio
async def test_the_allowed_hop_beside_an_attachment_still_runs_and_is_spent_once() -> None:
    outbound = _Tripwire()
    text = f"(src={IMG};accept=image/png, s=url4://n2/v1(x)!go)!'$s'"
    assert "remote says hi" in await allow_one_remote_hop(run(text, outbound), ("n2", "/v1"))
    assert outbound.calls[0] == f"fetch_bytes {IMG}"
    assert len(outbound.calls) == 2  # the attachment flight, then the one remote call


@pytest.mark.asyncio
async def test_a_second_call_to_the_allowed_hop_refuses_before_any_io() -> None:
    outbound = _Tripwire()
    text = f"(src={IMG};accept=image/png, url4://n2/v1(x)!go, url4://n2/v1(y)!go)!d"
    with pytest.raises(ResolutionError) as caught:
        await allow_one_remote_hop(run(text, outbound), ("n2", "/v1"))
    _assert_refused(caught.value)
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_the_precheck_never_spends_the_hop() -> None:
    from url4.dag.remote_nodes import check_remote_node

    async def probe() -> None:
        precheck_remote_nodes([("n2", "/v1")])
        precheck_remote_nodes([("n2", "/v1")])
        check_remote_node("n2", "/v1")  # the real call still has its hop

    await allow_one_remote_hop(probe(), ("n2", "/v1"))


def test_without_a_policy_the_precheck_refuses_nothing() -> None:
    precheck_remote_nodes([("n2", "/v1"), ("n2", "/v1"), ("n3", "/x")])  # bare run()


@pytest.mark.asyncio
async def test_a_text_only_run_at_a_node_keeps_the_execution_time_refusal() -> None:
    # No run-start I/O: nothing changes; the refusal still comes from the remote node itself.
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound)
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate("(s=url4://n2/v1(x)!go)!'$s'")
    _assert_refused(caught.value)
    assert outbound.calls == []
