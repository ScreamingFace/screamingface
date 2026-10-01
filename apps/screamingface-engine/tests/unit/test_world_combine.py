"""The url4 route of the combine call (FW-8, FW-11, EV-3, EV-E1; OME-1289 E4a, unit 1).

FEATURE: ``world.combine`` serves ``/ensemble/combine/v1`` on a node and records the evidence.
The pure core is tested in ``test_combine_endpoint.py``; here only the adapter's own duties are
pinned: the route, the ``ResolutionError`` mapping, and the task-local record.
"""

from __future__ import annotations

import socket
from collections.abc import Callable

import httpx
import pytest
from combine_support import (
    FAKE_REGISTRY,
    context_text,
    request,
    run_recorded,
    spec_text,
    vote_spec,
)

from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.world.combine import CombineRoute, install_combine_runtime
from url4 import RelExpr, Text, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.peer.server import Url4Node


def _node() -> Url4Node:
    node = Url4Node("t", outbound=StaticIOLayer())
    install_combine_runtime(node, FAKE_REGISTRY)
    return node


async def _evaluate(node: Url4Node, intent: str, context: str) -> str:
    expression = expr(
        src(text(context), name="ctx", weight=0.0),
        RelExpr(
            path=COMBINE_ROUTE,
            context="$ctx",
            intent=Text(intent),
            params=(("binding", "synthesis_1"),),
        ),
        intent=Text(""),
    )
    return (await node.evaluate(render(expression))).text


# --- EV-3 / FW-H1 ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_combine_call_through_url4_records_one_operation_call_with_evidence() -> None:
    node = _node()
    texts = ["same x", "other y", "third x"]
    with capture_operation_calls() as calls:
        result = await _evaluate(node, spec_text(vote_spec(3)), context_text(texts))
    assert result == texts[0]
    assert len(calls) == 1
    call = calls[0]
    assert call.path == COMBINE_ROUTE
    assert call.params == (("binding", "synthesis_1"),)
    assert call.output == texts[0]
    assert call.finish_reason == "stop"
    assert call.accounting is None
    assert call.combine is not None and call.combine.kind == "answer"


def test_the_route_records_the_core_evidence_unchanged() -> None:
    output, calls = run_recorded(spec_text(vote_spec(3)), context_text(["a x", "b", "c x"]))
    assert output == "a x"
    assert calls[0].combine is not None
    assert calls[0].combine.chosen == ["member_1"]


# --- FW-8 -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the combine endpoint must not touch the network")

    monkeypatch.setattr(httpx.AsyncClient, "send", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    texts = ["a x", "b x", "c y"]
    result = await _evaluate(_node(), spec_text(vote_spec(3)), context_text(texts))
    assert result == texts[0]


# --- FW-11 ----------------------------------------------------------------------------------


def test_install_combine_runtime_is_idempotent() -> None:
    node = Url4Node("t")
    install_combine_runtime(node, FAKE_REGISTRY)
    install_combine_runtime(node, FAKE_REGISTRY)
    assert node.processor_routes().count(COMBINE_ROUTE) == 1


def test_the_route_exposes_its_registry() -> None:
    assert CombineRoute(FAKE_REGISTRY).registry is FAKE_REGISTRY


# --- the ResolutionError mapping and EV-E1 ---------------------------------------------------


def _no_votes() -> tuple[str, str, dict[str, str]]:
    return spec_text(vote_spec(2)), context_text(["", " "]), {"binding": "synthesis_1"}


def _unknown_operator() -> tuple[str, str, dict[str, str]]:
    spec = vote_spec(2, extract={"op": "fake_last_word@9", "args": {}})
    return spec_text(spec), context_text(["a", "b"]), {"binding": "synthesis_1"}


def _invalid_spec() -> tuple[str, str, dict[str, str]]:
    return "not json", context_text(["a", "b"]), {"binding": "synthesis_1"}


def _too_large() -> tuple[str, str, dict[str, str]]:
    return "x" * (64 * 1024 + 1), context_text(["a", "b"]), {"binding": "synthesis_1"}


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (_no_votes, "combine_no_votes"),
        (_unknown_operator, "combine_operator_unknown"),
        (_invalid_spec, "combine_spec_invalid"),
        (_too_large, "combine_input_too_large"),
    ],
    ids=["no-votes", "operator-unknown", "spec-invalid", "input-too-large"],
)
def test_a_combine_error_becomes_a_permanent_resolution_error_and_records_nothing(
    make: Callable[[], tuple[str, str, dict[str, str]]], code: str
) -> None:
    intent, context, params = make()
    with capture_operation_calls() as calls:
        with pytest.raises(ResolutionError) as caught:
            CombineRoute(FAKE_REGISTRY)(request(intent, context, params))
    assert caught.value.code == code
    assert caught.value.permanent is True
    assert calls == []


def test_a_plugin_bug_stays_loud_and_records_nothing() -> None:
    spec = vote_spec(2, select={"op": "fake_bad@1", "args": {}})
    with capture_operation_calls() as calls:
        with pytest.raises(RuntimeError, match=r"fake_bad@1") as caught:
            CombineRoute(FAKE_REGISTRY)(request(spec_text(spec), context_text(["a", "b"])))
    assert not isinstance(caught.value, ResolutionError)
    assert calls == []


# --- U1-21 ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spec_strings_may_escape_dollar_as_u0024() -> None:
    spec = vote_spec(2, extract={"op": "fake_args@1", "args": {"sep": "$input"}})
    intent = spec_text(spec).replace("$", "\\u0024")
    assert "$" not in intent
    with capture_operation_calls() as calls:
        result = await _evaluate(_node(), intent, context_text(["first", "second"]))
    assert result == "first"
    assert len(calls) == 1
    evidence = calls[0].combine
    assert evidence is not None and evidence.tally is not None
    assert evidence.tally[0].value == "$input"
    assert [row.raw for row in evidence.members] == ["$input", "$input"]
