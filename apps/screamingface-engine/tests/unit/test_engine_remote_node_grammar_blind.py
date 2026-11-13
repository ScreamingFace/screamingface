"""An engine run refuses a remote node hidden by a grammar-blind nested group (OME-1811, #1750).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a run whose text holds a nested group the strict grammar rejects but
the engine compiles (`(('r1','r2')*(/b($item)!'i'))!'g'`) and that names another node costs
nothing: no local endpoint, and so no paid model call, runs before the refusal.

INVARIANT (PR #1750 round 5): a `url4://` call beside the group, inside it, in a sibling map body,
or beside / inside a group over an `https://` collection fails `x.remote_node_unsupported`
(permanent) out of `Url4Executor.execute` with no `Completed` step, zero endpoint invocations, zero
DNS lookups and zero requests. The same shape without the remote call completes, and a
non-reducing run with a static Form-3 `url4://` processor is refused the same way.
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
BLIND = "(('r1','r2')*(/b($item)!'i'))!'g'"
BLIND_HTTPS = "(https://rows*(/b($item)!'i'))!'g'"
CASES = {
    "remote-sibling-of-the-group": (f"(/a(x)!'q', {BLIND}, {REMOTE}(a)!'k')!'m'", None),
    "remote-inside-the-group": (
        f"(/a(x)!'q', (('r1','r2')*(/b($item)!'i', {REMOTE}(a)!'k'))!'g')!'m'",
        None,
    ),
    "remote-in-a-sibling-map-body": (
        f"(/a(x)!'q', {BLIND}, ('s1','s2')*({REMOTE}($item)!'j')!'p')!'m'",
        None,
    ),
    "https-collection-group-with-a-remote-sibling": (
        f"(/a(x)!'q', {BLIND_HTTPS}, {REMOTE}(a)!'k')!'m'",
        None,
    ),
    "non-reducing-run-static-form-3-processor": ("/a(x)!'i'", f"(p:0:'{REMOTE}')!'$p'"),
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
        self.requests.append(f"{request.method} {request.url.host}{request.url.path}")
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

    node.endpoint("/a")(endpoint("a"))
    node.endpoint("/b")(endpoint("b"))
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(CASES))
async def test_an_engine_run_refuses_a_grammar_blind_remote_call_for_free(
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
async def test_the_engine_runs_the_grammar_blind_group_without_a_remote_call(
    wire: _Tripwire,
) -> None:
    expression = f"(/a(x)!'q', {BLIND_HTTPS})!'m'"
    steps = [step async for step in Url4Executor(_world(wire, None)).execute(expression)]
    assert isinstance(steps[-1], Completed)
    assert sorted(wire.calls) == ["a", "b", "b"]  # the member, then one call per fetched row
    assert wire.dns == ["rows"]
    assert wire.requests == ["GET 93.184.216.34/"]
