"""An engine run checks every verbatim context and never crashes on one (OME-1811, #1750 r8).

FEATURE: file inputs for url4 (epic OME-1529); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a context holding a quoted `'a@b'` beside a grammar-blind group that
calls another node costs nothing (no local endpoint, so no paid model call, runs first), and a
context with an empty comma segment completes exactly as it did before the check existed.

INVARIANT: each refused case fails `x.remote_node_unsupported` (permanent) out of
`Url4Executor.execute` with no `Completed` step and zero endpoint invocations and DNS lookups
(so zero requests); each empty-comma text completes with its origin/main value.
"""

from __future__ import annotations

import pytest

from screamingface_engine.runner.executor import Url4Executor
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.peer.server import Url4Node
from url4.streaming.interfaces import Completed

REMOTE = "url4://n2.example/v1"
BLIND = f"(('r1','r2')*({REMOTE}($item)!'i'))!'g'"
CASES = {
    "quoted-at-to-the-eval-path": f"(/a(x)!'q', /v1('a@b', {BLIND})!'k')!'m'",
    "quoted-at-in-a-map-body": f"('r1','r2')*(/b($item)!'i', /v1('a@b', {BLIND})!'k')!'per'",
    "quoted-at-in-a-nested-group": f"(/a(x)!'q', (/b(y)!'w', /v1('a@b', {BLIND})!'k')!'h')!'m'",
}
EMPTY_COMMA = {
    "/c(@,)!'k'": "C",
    "(/a(x)!'q', /c(@, ,optional)!'k')!'m'": "A",
    "('r1')*(/c(@, $item,)!'k')!'p'": '["A"]',
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
async def test_an_engine_run_refuses_a_remote_call_in_a_verbatim_context_for_free(
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
    assert (wire.calls, wire.dns) == ([], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", sorted(EMPTY_COMMA))
async def test_an_engine_run_completes_an_empty_comma_context_as_on_main(
    wire: _Tripwire, expression: str
) -> None:
    steps = [step async for step in Url4Executor(_world(wire)).execute(expression)]
    finished = steps[-1]
    assert isinstance(finished, Completed)
    assert finished.result.body == EMPTY_COMMA[expression]
