"""Only ``https://`` is an attachment source; ``http://`` stays on the text path.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 5,
owner decision Sergey 2026-11-04).
STORY: as an ensemble author, ``src=http://…/a.png;accept=image/png`` is the text source it always
was: fetched as text when it runs, never fetched as bytes before the first model call and never
attached. ``ARCHITECTURE.md`` (F1b "Scope of attachments") names ``https://`` sources only.
"""

from __future__ import annotations

import pytest

from url4.core.grammar import parse
from url4.core.nodes import Source, Url
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachment_sources import identity_of
from url4.dag.attachments import current_attachments, scan_sources
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

HTTP = "http://img.example/a.png"
HTTPS = "https://img.example/a.png"


class _Io(StaticIOLayer):
    def __init__(self) -> None:
        super().__init__(
            {HTTP: "plain text body", HTTPS: b"\x89PNG"}, media_types={HTTPS: "image/png"}
        )
        self.byte_targets: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.byte_targets.append(request.target)
        return await super().fetch_bytes(request)


class _Model:
    def __init__(self) -> None:
        self.seen: list[tuple[Attachment, ...]] = []
        self.sources: list[str] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.seen.append(current_attachments())
        self.sources.append(sources)
        return "ok"


@pytest.mark.parametrize("accept", ["image/png", "application/pdf"])
def test_an_http_source_with_an_attachment_accept_has_no_attachment_identity(accept: str) -> None:
    source = Source(Url(HTTP), annotations=(("accept", accept),))
    assert identity_of(source) is None
    assert identity_of(Source(Url(HTTPS), annotations=(("accept", accept),))) is not None


def test_the_scan_records_no_occurrence_or_slot_for_an_http_source() -> None:
    scan = scan_sources(parse(f"(src={HTTP};accept=image/png)!'d'"))
    assert scan.occurrences == () and scan.order == () and scan.non_literal == ()


@pytest.mark.asyncio
async def test_an_http_source_is_fetched_as_text_and_never_attached() -> None:
    io, model = _Io(), _Model()
    assert await run(f"(src={HTTP};accept=image/png)!'d'", io, process=model) == "ok"
    assert io.byte_targets == []  # no bytes flight before the model call
    assert model.seen == [()]
    assert "plain text body" in model.sources[0]


@pytest.mark.asyncio
async def test_the_same_https_source_is_still_an_attachment() -> None:
    io, model = _Io(), _Model()
    assert await run(f"(src={HTTPS};accept=image/png)!'d'", io, process=model) == "ok"
    assert io.byte_targets == [HTTPS]
    assert [a.media_type for a in model.seen[0]] == ["image/png"]
