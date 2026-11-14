"""An engine run refuses a remote node hidden in a call's context (OME-1811, #1750 round 6).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run that hides another node's call in a grammar-blind group inside a
local call's context (the lowering defers it into a group that runs on my node) costs nothing:
no local endpoint, and so no paid model call, runs before the refusal.

INVARIANT: the context in the run text, a map body, a nested group or a Form-3 processor, and a
remote call at the bottom of a 300-deep run, fail `x.remote_node_unsupported` (permanent) out of
`Url4Executor.execute` with no `Completed` step, zero endpoint invocations, zero DNS lookups and
zero requests. A quoted `url4://` mention in an uncompilable body is data, and that run completes.
"""

from __future__ import annotations

import httpx
import pytest

import url4.io._guarded_transport as gt
from screamingface_engine.runner.executor import Url4Executor
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed

REMOTE = "url4://n2.example/v1"
CTX = f"/c((('r1','r2')*({REMOTE}($item)!'i'))!'g')!'k'"
REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"


def _deep(bottom: str, depth: int = 300) -> str:
    text = bottom
    for _ in range(depth):
        text = f"(/b(y)!'w', {text})!'h'"
    return f"(/a(x)!'q', (('r1')*(/b($item)!'i'))!'g', {text})!'m'"


CASES = {
    "context-in-the-run-text": (f"(/a(x)!'q', {CTX})!'m'", None),
    "context-in-a-map-body": (f"https://rows*(/b($item)!'i', {CTX})!'per'", None),
    "context-in-a-nested-group": (f"(/a(x)!'q', (/b(y)!'w', {CTX})!'h')!'m'", None),
    "context-in-a-form-3-processor": (REDUCE, f"(p:0:{CTX})!'$p'"),
    "remote-at-the-bottom-of-a-deep-run": (_deep(f"{REMOTE}(a)!'k'"), None),
}


class _Tripwire:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.dns: list[str] = []
        self.requests: list[str] = []

    async def resolver(self, host: str, port: int) -> list[str]:
        self.dns.append(host)
        return ["93.184.216.34"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(f"{request.method} {request.url.path}")
        return httpx.Response(
            200, text='["w1", "w2"]', headers={"content-type": "application/json"}
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire, default_processor: str | None) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io, default_processor=default_processor)

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # in the real engine this is a (paid) model source
            return name.upper()

        return handle

    for name in ("a", "b", "c"):
        node.endpoint(f"/{name}")(endpoint(name))
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(CASES))
async def test_an_engine_run_refuses_a_remote_call_a_context_hides_for_free(
    wire: _Tripwire, case: str
) -> None:
    expression, processor = CASES[case]
    steps: list[object] = []
    with pytest.raises(ResolutionError) as caught:
        async for step in Url4Executor(_world(wire, processor)).execute(expression):
            steps.append(step)
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert not any(isinstance(step, Completed) for step in steps)
    assert wire.calls == []
    assert wire.dns == []
    assert wire.requests == []


@pytest.mark.asyncio
async def test_the_engine_completes_a_quoted_url4_mention_in_an_uncompilable_body(
    wire: _Tripwire,
) -> None:
    expression = f"https://rows*(/b($item)!'i', /b($item)!'see {REMOTE}' junk)!'per'"
    steps = [step async for step in Url4Executor(_world(wire, None)).execute(expression)]
    assert isinstance(steps[-1], Completed)
    assert wire.requests == ["GET /"]
