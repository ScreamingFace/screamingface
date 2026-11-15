"""An engine run in local mode prechecks eval-path calls through its fair-share io (OME-1811 r11).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as an operator running the engine locally, the fair-share io wrapper the runner always
puts around my node's io never switches the remote-node precheck off: a run handing my eval path
an expression that calls another node costs nothing, and a map body fails the run instead of
completing with error rows.

INVARIANT: `FairShareIOLayer` forwards the eval-path port (`eval_expression`) when the inner
layer has it, so every round-10 case fails `x.remote_node_unsupported` (permanent) out of
`Url4Executor(io_wrap=FairShareIOLayer)` with a real `FairShareGate`, no `Completed` step and
zero endpoint invocations and DNS lookups (so zero requests); the control completes.
"""

from __future__ import annotations

import pytest

from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.fair_share import FairShareGate, FairShareIOLayer
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import IOLayer
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed

REMOTE = "url4://n2.example/v1"
ITERATION = f"'r1' *({REMOTE}($item)!'i') zz(y)!'p'"
CASES = {
    "iteration-context-to-the-eval-path": f"(/a(x)!'q', /v1({ITERATION})!'k')!'m'",
    "iteration-context-beside-a-local-member": (
        f"(/a(x)!'q', (/b(y)!'w', /v1({ITERATION})!'k')!'h')!'m'"
    ),
    "iteration-context-in-a-map-body": f"('r1','r2')*(/b($item)!'i', /v1({ITERATION})!'k')!'per'",
    "eval-path-collection-qualifier": f"(/a(x)!'q', /v1/shelf({ITERATION})!'k')!'m'",
    "unquoted-collection-context": (
        f"(/a(x)!'q', /v1(hello *({REMOTE}($item)!'i') world(y)!'p')!'k')!'m'"
    ),
    "processor-param-on-the-call": (
        f"(/a(x)!'q', /v1(/b(y)!'w', /c(z)!'v')!'k';processor={REMOTE})!'m'"
    ),
    "processor-param-in-the-query": (
        f"(/a(x)!'q', /v1?processor={REMOTE}&q=(/b(y)!'w', /c(z)!'v')!'k')!'m'"
    ),
}


class _Tripwire:
    """Every endpoint invocation and DNS lookup this run causes.

    WHY no transport stub: every host here is a name, so a request needs a lookup first; the
    resolver refusing (and recording) every lookup means "zero DNS" is also "zero requests",
    without importing url4's private transport (the engine's private-import ratchet).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.dns: list[str] = []

    async def resolver(self, host: str, port: int) -> list[str]:
        self.dns.append(host)
        raise OSError("no DNS in this test")


@pytest.fixture
def wire() -> _Tripwire:
    return _Tripwire()


def _fair_share(io: IOLayer) -> IOLayer:
    return FairShareIOLayer(io, FairShareGate(8), "run-1")  # what local mode always wraps in


def _world(wire: _Tripwire) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example"}))
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
async def test_a_fair_share_engine_run_prechecks_an_eval_path_call_for_free(
    wire: _Tripwire, case: str
) -> None:
    steps: list[object] = []
    with pytest.raises(ResolutionError) as caught:
        async for step in Url4Executor(_world(wire), io_wrap=_fair_share).execute(CASES[case]):
            steps.append(step)
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert not any(isinstance(step, Completed) for step in steps)
    assert (wire.calls, wire.dns) == ([], [])


@pytest.mark.asyncio
async def test_a_fair_share_engine_run_completes_the_same_context_to_a_normal_route(
    wire: _Tripwire,
) -> None:
    expression = f"(/a(x)!'q', /c({ITERATION})!'k')!'m'"
    steps = [
        step async for step in Url4Executor(_world(wire), io_wrap=_fair_share).execute(expression)
    ]
    assert isinstance(steps[-1], Completed)
    assert "c" in wire.calls
