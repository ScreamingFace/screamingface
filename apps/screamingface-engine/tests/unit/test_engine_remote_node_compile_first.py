"""An engine run refuses every remote call its compiled graph makes, first (OME-1811, #1750 r7).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose iteration per-row intent, map-in-map or holdings context
(sent to my own evaluation path) calls another node costs nothing: no local endpoint, and so no
paid model call, runs before the refusal.

INVARIANT: each case fails `x.remote_node_unsupported` (permanent) out of `Url4Executor.execute`
with no `Completed` step, zero endpoint invocations, zero DNS lookups and zero requests; the same
per-row intent without the remote call completes. (The too-deep refusal is pinned in url4's
`test_remote_node_compile_first_preflight.py`: patching url4's private walk from here would grow
the engine's private-import ratchet.)
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
ROW_INTENT = f"/c({REMOTE}(a)!'z')!'k'"
CASES = {
    "per-row-intent-over-https-rows": f"https://rows*(/b($item)!'i')!{ROW_INTENT}",
    "per-row-intent-in-a-group": f"(/a(x)!'q', ('r1','r2')*(/b($item)!'i')!{ROW_INTENT})!'m'",
    "per-row-intent-of-a-map-in-a-map": (
        f"('s1','s2')*(('r1','r2')*(/b($item)!'i')!{ROW_INTENT})!'o'"
    ),
    "holdings-context-to-the-eval-path": f"(/a(x)!'q', /v1(@, {REMOTE}(y)!'i')!'k')!'m'",
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
        self.requests.append(f"{request.method} {request.headers.get('host', '')}")
        return httpx.Response(
            200, text='["w1", "w2"]', headers={"content-type": "application/json"}
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    tripwire = _Tripwire()
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(tripwire.handler))
    return tripwire


def _world(wire: _Tripwire) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example", "rows"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io)

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
async def test_an_engine_run_refuses_a_compiled_remote_call_for_free(
    wire: _Tripwire, case: str
) -> None:
    steps: list[object] = []
    with pytest.raises(ResolutionError) as caught:
        async for step in Url4Executor(_world(wire)).execute(CASES[case]):
            steps.append(step)
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert not any(isinstance(step, Completed) for step in steps)
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])


@pytest.mark.asyncio
async def test_the_engine_completes_the_per_row_intent_without_a_remote_call(
    wire: _Tripwire,
) -> None:
    expression = "https://rows*(/b($item)!'i')!/c(/a(a)!'z')!'k'"
    steps = [step async for step in Url4Executor(_world(wire)).execute(expression)]
    assert isinstance(steps[-1], Completed)
    assert wire.requests == ["GET rows"]
