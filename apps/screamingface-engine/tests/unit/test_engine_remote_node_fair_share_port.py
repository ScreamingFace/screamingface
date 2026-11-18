"""Local mode's fair-share io really carries the eval-path port (OME-1811 round 12).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as an operator running the engine locally, a run that only MENTIONS `url4://` in prose it
sends to an ordinary route completes, exactly as on a bare node: the precheck can ask my node
what its eval path runs, so it never falls back to reading every call's text fail closed.

INVARIANT: `FairShareIOLayer` exposes `eval_expression` when the inner node has it (the forward
is load-bearing: without it the port-less fail-closed fallback refuses these runs), and the
fair-share run then matches the bare-node run. The tripwire records every endpoint call and DNS
lookup; DNS raising means zero DNS is also zero requests.
"""

from __future__ import annotations

import pytest

from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.fair_share import FairShareGate, FairShareIOLayer
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import IOLayer
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed

REMOTE = "url4://n2.example/v1"
PROSE_TO_A_ROUTE = {
    "prose-naming-url4": f"(/a(x)!'q', /c(see {REMOTE} for docs, thanks)!'k')!'m'",
    "email-prose-naming-url4": f"(/a(x)!'q', /c(mail bob@x.io about {REMOTE} docs)!'k')!'m'",
}


class _Tripwire:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.dns: list[str] = []

    async def resolver(self, host: str, port: int) -> list[str]:
        self.dns.append(host)
        raise OSError("no DNS in this test")


def _world(wire: _Tripwire) -> Url4Node:
    guard = SourceGuard(peer_hosts=frozenset({"n2.example"}))
    node = Url4Node("n1", outbound=HttpIOLayer(guard=guard, resolver=wire.resolver))

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)
            return name.upper()

        return handle

    for name in ("a", "b", "c"):
        node.endpoint(f"/{name}")(endpoint(name))
    return node


def _fair_share(io: IOLayer) -> IOLayer:
    return FairShareIOLayer(io, FairShareGate(8), "run-1")


def test_the_fair_share_layer_exposes_the_inner_eval_port() -> None:
    node = _world(_Tripwire())
    wrapped = FairShareIOLayer(node, FairShareGate(8), "run-1")
    assert wrapped.eval_expression("/v1?q=(/a(x)!'i')!'k'") == node.eval_expression(
        "/v1?q=(/a(x)!'i')!'k'"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(PROSE_TO_A_ROUTE))
async def test_a_fair_share_run_completes_prose_naming_url4_like_a_bare_node(case: str) -> None:
    wire = _Tripwire()
    expression = PROSE_TO_A_ROUTE[case]
    steps = [s async for s in Url4Executor(_world(wire), io_wrap=_fair_share).execute(expression)]
    assert isinstance(steps[-1], Completed)
    assert "c" in wire.calls  # the prose reached /c as text
    assert wire.dns == []
