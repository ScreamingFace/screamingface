"""Every verbatim call context is checked as it would run; no context crashes the check (OME-1811).

FEATURE: file inputs for url4 (epic ``OME-1529``); #1450 spec F1b / §4, conformance case C6.
STORY: as a node operator, a context my node ships verbatim (any context holding an ``@``) and may
evaluate on its own path is checked for ``url4://`` calls before anything runs — a quoted ``'a@b'``
does not hide a grammar-blind group beside it — and a context that merely looks odd (an empty
comma segment) runs exactly as it did before the check existed.

INVARIANT (PR #1750 round 8): under :func:`url4.dag.refuse_remote_nodes` every verbatim context
is compiled as ``(context)`` and walked; a remote call it holds fails ``x.remote_node_unsupported``
(permanent) with zero endpoint invocations, zero DNS lookups and zero requests. A context that
does not compile is read as the scan always read it (prose stays prose), and NO exception a
fragment's compile raises escapes the precheck: the empty-comma texts give the same result with
and without a policy, through ``run()`` and ``Url4Node.evaluate``.
"""

from __future__ import annotations

import httpx
import pytest

import url4.io._guarded_transport as gt
from url4.core.descriptor_head import deferrable_group
from url4.core.errors import ErrorCode, ParseError, ResolutionError
from url4.dag import refuse_remote_nodes, run
from url4.io._source_policy import SourceGuard
from url4.io.http import HttpIOLayer
from url4.peer.server import Url4Node

REMOTE = "url4://n2.example/v1"
BLIND = f"(('r1','r2')*({REMOTE}($item)!'i'))!'g'"
REFUSED = {
    "quoted-at-and-blind-group-to-the-eval-path": f"(/a(x)!'q', /v1('a@b', {BLIND})!'k')!'m'",
    "quoted-at-and-blind-group-as-the-run": f"/v1('a@b', {BLIND})!'k'",
    "email-text-and-blind-group-to-the-eval-path": (
        f"(/a(x)!'q', /v1('mail me at x@y', {BLIND})!'k')!'m'"
    ),
    "quoted-at-and-blind-group-in-a-map-body": (
        f"('r1','r2')*(/b($item)!'i', /v1('a@b', {BLIND})!'k')!'per'"
    ),
    "quoted-at-and-blind-group-in-a-nested-group": (
        f"(/a(x)!'q', (/b(y)!'w', /v1('a@b', {BLIND})!'k')!'h')!'m'"
    ),
    "quoted-at-and-blind-group-to-a-normal-route": f"(/a(x)!'q', /c('a@b', {BLIND})!'k')!'m'",
    "quoted-at-and-blind-group-beside-a-local-member": (
        f"(/a(x)!'q', /v1('a@b', (('r1','r2')*(/b($item)!'i', {REMOTE}($item)!'z'))!'g')!'k')!'m'"
    ),
}
# The value each text gives on origin/main, with and without a policy (measured 2026-11-14).
EMPTY_COMMA = {
    "/c(@,)!'k'": "C",
    "(/a(x)!'q', /c(@, ,optional)!'k')!'m'": "A",
    "('r1')*(/c(@, $item,)!'k')!'p'": '["A"]',
    "/c(mail bob@x.io, thanks,)!'k'": "C",
}


class _Tripwire:
    """Every endpoint invocation, DNS lookup and request this run causes."""

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
    guard = SourceGuard(peer_hosts=frozenset({"n2.example"}))
    io = HttpIOLayer(guard=guard, resolver=wire.resolver)
    node = Url4Node("n1", outbound=io)

    def endpoint(name: str):
        def handle(request: object) -> str:
            wire.calls.append(name)  # the tripwire: a local source that ran
            return name.upper()

        return handle

    for name in ("a", "b", "c"):
        node.endpoint(f"/{name}")(endpoint(name))
    return node


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(REFUSED))
async def test_a_remote_call_in_a_verbatim_context_refuses_before_any_io(
    wire: _Tripwire, case: str
) -> None:
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(REFUSED[case], _world(wire)))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_NODE_UNSUPPORTED,
        True,
    )
    assert (wire.calls, wire.dns, wire.requests) == ([], [], [])


@pytest.mark.asyncio
async def test_the_quoted_at_context_without_a_remote_call_runs(wire: _Tripwire) -> None:
    blind = "(('r1','r2')*(/b($item)!'i'))!'g'"
    await refuse_remote_nodes(run(f"(/a(x)!'q', /c('a@b', {blind})!'k')!'m'", _world(wire)))
    assert "a" in wire.calls
    assert "c" in wire.calls
    assert wire.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", sorted(EMPTY_COMMA))
@pytest.mark.parametrize("policy", [False, True], ids=["bare", "policy"])
async def test_an_empty_comma_context_runs_as_on_main(
    wire: _Tripwire, expression: str, policy: bool
) -> None:
    evaluation = run(expression, _world(wire))
    result = await (refuse_remote_nodes(evaluation) if policy else evaluation)
    assert result == EMPTY_COMMA[expression]


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", sorted(EMPTY_COMMA))
async def test_an_empty_comma_context_evaluates_on_a_node_as_on_main(
    wire: _Tripwire, expression: str
) -> None:
    result = await _world(wire).evaluate(expression)
    assert result.text == EMPTY_COMMA[expression]


def test_an_empty_segment_is_a_coded_parse_error_not_a_value_error() -> None:
    with pytest.raises(ParseError) as caught:
        deferrable_group("")
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
