"""A call's context is a holdings pass-through only when its PARSED segments hold a holdings ref.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; e2e finding F3, 2026-11-02).
STORY: as an ensemble author I attach ``src=https://cdn.jsdelivr.net/gh/o/r@<ref>/chart.png;
accept=image/png`` inside a call's parens, and the picture reaches the model, instead of the run
answering 200 with the URL handed to the model as text because the URL happens to contain ``@``.

INVARIANT (spec §5.6.3.1/.2): a context holding a holdings ref (``@`` / ``@identity``) is the
receiving route's business and is never resolved caller-side — decided on the parsed AST
(``SelfRef`` / ``IdentityRef``), not on a substring, so an ``@`` inside a URL or quoted text
does not disable the scan.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
import url4.io.http as http_mod
from url4.cli._serve import ServeConfig, build_node
from url4.core.grammar import parse
from url4.dag.attachment import Attachment
from url4.dag.attachments import scan_sources
from url4.peer.server import Request, Url4Node

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-at-sign"
PNG_HEX = hashlib.sha256(PNG).hexdigest()
AT_URL = "https://cdn.jsdelivr.net/gh/ScreamingFace/screamingface@12f9844a9/fixtures/chart.png"
PUBLIC = "93.184.215.14"


class _Web:
    def __init__(self) -> None:
        self.sent: list[httpx.Request] = []

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        return [PUBLIC]

    def transport(self) -> httpx.AsyncBaseTransport:
        def record(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

        return httpx.MockTransport(record)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> _Web:
    fake = _Web()
    monkeypatch.setattr(guarded_mod, "_inner_transport", fake.transport)
    monkeypatch.setattr(http_mod, "system_resolver", fake.resolve)
    return fake


def _node() -> tuple[Url4Node, list[tuple[Attachment, ...]]]:
    node = build_node(ServeConfig(commands={"/echo": ("cat",)}, data={}))
    seen: list[tuple[Attachment, ...]] = []

    @node.endpoint("/model")
    def model(request: Request) -> str:
        seen.append(request.attachments)
        return "described"

    return node, seen


def _occurrence_targets(text: str) -> list[str]:
    return [identity.url for identity, _ in scan_sources(parse(text)).occurrences]


def test_an_at_sign_inside_a_context_url_keeps_the_attachment_source() -> None:
    text = f"/model(src={AT_URL};accept=image/png)!'What is the chart title code?'"
    assert _occurrence_targets(text) == [AT_URL]


def test_an_at_sign_in_quoted_context_text_keeps_the_attachment_source() -> None:
    text = f"/model('mail a@b.example', src={AT_URL};accept=image/png)!'d'"
    assert _occurrence_targets(text) == [AT_URL]


@pytest.mark.parametrize("holdings", ["@", "@emily", "@emily/notes"])
def test_a_real_holdings_ref_keeps_the_context_verbatim(holdings: str) -> None:
    # Today's behaviour: the whole context is the receiving route's business.
    text = f"/model({holdings}, src={AT_URL};accept=image/png)!'d'"
    assert _occurrence_targets(text) == []


def test_a_holdings_ref_in_a_nested_call_keeps_the_outer_context_verbatim() -> None:
    text = f"/model(/inner(@)!'q', src={AT_URL};accept=image/png)!'d'"
    assert _occurrence_targets(text) == []


@pytest.mark.asyncio
async def test_the_at_sign_url_repro_fetches_and_attaches(web: _Web) -> None:
    node, seen = _node()
    try:
        result = await node.evaluate(
            f"/model(src={AT_URL};accept=image/png)!'What is the chart title code?'"
        )
    finally:
        await node.aclose()
    assert result.text == "described"
    assert [str(request.url.path) for request in web.sent] == [httpx.URL(AT_URL).path]
    assert seen == [(Attachment(f"sha256:{PNG_HEX}", "image/png", PNG),)]


def test_a_holdings_ref_in_a_nested_iteration_body_keeps_the_outer_context_verbatim() -> None:
    text = f"/model(('a')*(@)!'q', src={AT_URL};accept=image/png)!'d'"
    assert _occurrence_targets(text) == []


def test_a_holdings_ref_in_a_nested_remote_call_keeps_the_outer_context_verbatim() -> None:
    text = f"/model(url4://peer.example/m(@emily)!'q', src={AT_URL};accept=image/png)!'d'"
    assert _occurrence_targets(text) == []


def test_an_unparseable_segment_holding_an_at_sign_keeps_the_context_verbatim() -> None:
    # Conservative, as before F3: its meaning is unknown and may be a holdings ref.
    text = f"/model(note: ask @emily, src={AT_URL};accept=image/png)!'d'"
    assert _occurrence_targets(text) == []


def test_an_unparseable_segment_without_an_at_sign_does_not_hide_the_others() -> None:
    text = f"/model(note: run 1, src={AT_URL};accept=image/png)!'d'"
    assert _occurrence_targets(text) == [AT_URL]
