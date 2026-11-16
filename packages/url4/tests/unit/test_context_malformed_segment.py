"""An unparseable call-context segment raises only with an attachment opt-in (owner 2026-11-02).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; e2e finding F3 follow-up).
STORY: as an ensemble author I mistype ``src=https://x/a.png;accept=image/png`` inside a call's
parens, and the run fails with ``malformed_source`` instead of answering without the picture.

INVARIANT ("raise only with an opt-in"): a file the caller asked for is never silently dropped.
An unparseable segment of a call context is refused — permanent ``malformed_source``, before
any I/O — when (a) the same context carries an attachment opt-in, or (b) the segment itself
looks like an attachment descriptor (``src=`` / ``;accept=``). Otherwise prose stays prose and
contributes nothing (pinned ``test_attachments.py::test_a_prose_or_holdings_context_…``).
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
import url4.io.http as http_mod
from url4.cli._serve import ServeConfig, build_node
from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import parse
from url4.dag.attachments import scan_sources
from url4.peer.server import Request, Url4Node

IMG = "https://img.example/a.png"
PUBLIC = "93.184.215.14"


class _NoWeb:
    """Every outbound request fails the test: the refusal must come before any I/O."""

    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        raise AssertionError(f"DNS lookup for {host!r} before the refusal")

    def transport(self) -> httpx.AsyncBaseTransport:
        def refuse(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            raise AssertionError(f"request to {request.url} before the refusal")

        return httpx.MockTransport(refuse)


@pytest.fixture
def no_web(monkeypatch: pytest.MonkeyPatch) -> _NoWeb:
    fake = _NoWeb()
    monkeypatch.setattr(guarded_mod, "_inner_transport", fake.transport)
    monkeypatch.setattr(http_mod, "system_resolver", fake.resolve)
    return fake


def _node() -> tuple[Url4Node, list[str]]:
    node = build_node(ServeConfig(commands={"/echo": ("cat",)}, data={}))
    calls: list[str] = []

    @node.endpoint("/model")
    def model(request: Request) -> str:
        calls.append("model")
        return "described"

    return node, calls


async def _evaluate(text: str) -> tuple[str, list[str]]:
    node, calls = _node()
    try:
        result = await node.evaluate(text)
    finally:
        await node.aclose()
    return result.text, calls


def _malformed(text: str) -> tuple[str, ...]:
    return scan_sources(parse(text)).malformed


# -- prose alone stays prose -------------------------------------------------------------------


def test_prose_alone_contributes_no_refs_and_no_malformed_segment() -> None:
    text = "(/m(note: run 1, , 'x')!'d')!'r'"
    scan = scan_sources(parse(text))
    assert scan.refs == () and scan.occurrences == () and scan.malformed == ()


@pytest.mark.asyncio
async def test_prose_alone_runs_without_error(no_web: _NoWeb) -> None:
    text, calls = await _evaluate("/model(note: run 1, 'x')!'d'")
    assert text == "described" and calls == ["model"]
    assert no_web.sent == []


# -- (a) prose beside an attachment opt-in -----------------------------------------------------


def test_prose_beside_an_attachment_is_recorded_as_malformed() -> None:
    assert _malformed(f"/model(note: run 1, src={IMG};accept=image/png)!'d'") == ("note: run 1",)


@pytest.mark.asyncio
async def test_prose_beside_an_attachment_raises_before_any_io(no_web: _NoWeb) -> None:
    with pytest.raises(ParseError) as caught:
        await _evaluate(f"/model(note: run 1, src={IMG};accept=image/png)!'d'")
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert caught.value.permanent is True
    assert "note: run 1" in str(caught.value)
    assert no_web.sent == []


def test_a_text_source_is_not_an_opt_in() -> None:
    # An https:// source with no attachment ;accept= is a text source: prose beside it is prose.
    assert _malformed(f"/model(note: run 1, src={IMG})!'d'") == ()
    assert _malformed(f"/model(note: run 1, src={IMG};accept=text/plain)!'d'") == ()


# -- (b) a segment that looks like a descriptor ------------------------------------------------


@pytest.mark.parametrize(
    "segment",
    [
        f"src={IMG};;accept=image/png",
        f"src={IMG};accept=image/png extra",
        f"src={IMG};accept=image/png;",
        "src=;accept=image/png",
    ],
)
def test_a_malformed_descriptor_alone_is_recorded(segment: str) -> None:
    assert _malformed(f"/model('q', {segment})!'d'") == (segment,)


@pytest.mark.asyncio
async def test_a_malformed_descriptor_alone_raises_before_any_io(no_web: _NoWeb) -> None:
    with pytest.raises(ParseError) as caught:
        await _evaluate(f"/model(src={IMG};;accept=image/png)!'d'")
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE
    assert caught.value.permanent is True
    assert no_web.sent == []


# -- holdings contexts are unchanged -----------------------------------------------------------


@pytest.mark.parametrize(
    "context",
    [
        f"@, note: run 1, src={IMG};accept=image/png",
        f"@emily, src={IMG};;accept=image/png",
        f"note: ask @emily, src={IMG};accept=image/png",
    ],
)
def test_a_holdings_context_records_nothing(context: str) -> None:
    scan = scan_sources(parse(f"/model({context})!'d'"))
    assert scan.occurrences == () and scan.malformed == ()


# -- iteration bodies are templates, not call contexts -----------------------------------------


def test_an_iteration_body_segment_is_never_recorded() -> None:
    # WHY: a body segment may only parse after row substitution (deviation 3).
    text = f"(('a')*(note: run 1, src={IMG};accept=image/png)!'d')!'r'"
    assert _malformed(text) == ()
