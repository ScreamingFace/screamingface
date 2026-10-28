"""``https://`` attachment sources become run attachments; text sources never do (U3b, F1b).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543`` sub-issue A; plan
``docs/plan/2026-10-21-OME-1543-file-refs-carry-plan.md`` §2.7 / U3b; #1450 F1b rounds 7–8).
STORY: as an ensemble author I write ``img:src=https://…/photo.png;accept=image/png`` and every
model call receives the image as an attachment, while the payload carries the URL text.

INVARIANT (owner decision A, 2026-10-27 — Q-B dropped): only an attachment source (``;accept=``
exactly one attachment type) is attached: fetched once as bytes before the first model call,
sha256-hashed, listed at its identity's first occurrence. A text source stays lazy, as today; a
text body is unchanged, never attached, and exempt from D5; a non-text body is never attached.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.dag.node import ExecutionContext
from url4.dag.nodes import WebFetchNode
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-https"
PDF = b"%PDF-1.7 https"
PNG_HEX = hashlib.sha256(PNG).hexdigest()
PDF_HEX = hashlib.sha256(PDF).hexdigest()
IMG_URL = "https://files.example/photo.png"
TWIN_URL = "https://mirror.example/same-photo.png"
TXT_URL = "https://files.example/notes.txt"
IMG = Attachment(f"sha256:{PNG_HEX}", "image/png", PNG)
DOC = Attachment(f"sha256:{PDF_HEX}", "application/pdf", PDF)

GUARD_CODES = [
    ErrorCode.SOURCE_DESTINATION_BLOCKED,
    ErrorCode.SOURCE_REDIRECT_LIMIT,
    ErrorCode.SOURCE_TOO_LARGE,
    ErrorCode.SOURCE_TIMEOUT,
]


class _Web(StaticIOLayer):
    """A fake web plus node store; ``refuse`` makes a target's BYTES fetch raise a guard code."""

    def __init__(self, refuse: dict[str, ErrorCode] | None = None) -> None:
        super().__init__(
            {
                IMG_URL: PNG,
                TWIN_URL: PNG,
                TXT_URL: "plain notes",
                f"/blob/sha256/{PNG_HEX}": PNG,
                f"/blob/sha256/{PDF_HEX}": PDF,
            },
            media_types={
                IMG_URL: "image/png",
                TWIN_URL: "image/png",
                TXT_URL: "text/plain",
                f"/blob/sha256/{PNG_HEX}": "image/png",
                f"/blob/sha256/{PDF_HEX}": "application/pdf",
            },
        )
        self.refuse = dict(refuse or {})
        self.byte_targets: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.byte_targets.append(request.target)
        code = self.refuse.get(request.target)
        if code is not None:
            raise ResolutionError(f"guard refused {request.target!r}", code=code)
        return await super().fetch_bytes(request)


class _Model:
    """A ``process`` hook recording each call's payload and attachments."""

    def __init__(self) -> None:
        self.payloads: list[str] = []
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.payloads.append(sources)
        self.seen.append(current_attachments())
        return "ok"


@pytest.mark.asyncio
async def test_non_text_https_body_is_attached_once_at_its_source_position() -> None:
    io, model = _Web(), _Model()
    text = (
        f"(img:src={IMG_URL};accept=image/png, src=/blob/sha256/{PDF_HEX},"
        f" again:src={IMG_URL};accept=image/png)!'d'"
    )
    assert await run(text, io, process=model) == "ok"
    # WHY (IMG, DOC): the https source comes first in the source list, so it is first.
    assert model.seen == [(IMG, DOC)]
    assert model.seen[0][0].body == PNG
    assert IMG_URL in model.payloads[0]
    assert PNG.decode("latin-1") not in model.payloads[0]
    # The second occurrence of the same identity shares the one flight: fetched once.
    assert io.byte_targets.count(IMG_URL) == 1


@pytest.mark.asyncio
async def test_text_https_body_is_not_attached_and_payload_is_unchanged() -> None:
    io, model = _Web(), _Model()
    await run(f"(src={TXT_URL})!'d'", io, process=model)
    baseline = _Model()
    await run("(src='plain notes')!'d'", _Web(), process=baseline)
    assert model.seen == [()]
    assert model.payloads == baseline.payloads
    assert io.byte_targets == []


@pytest.mark.asyncio
async def test_https_body_with_a_blob_refs_digest_is_attached_once() -> None:
    model = _Model()
    text = (
        f"(src=/blob/sha256/{PNG_HEX}, src=/blob/sha256/{PNG_HEX},"
        f" src={IMG_URL};accept=image/png, src={IMG_URL};accept=image/png)!'d'"
    )
    await run(text, _Web(), process=model)
    # Blob refs dedupe by digest and equal identities share one attachment; a blob ref and an
    # attachment identity are never merged, even for equal bytes (F1b round 7).
    assert model.seen == [(IMG, IMG)]


@pytest.mark.asyncio
async def test_case_attachments_precede_an_https_attachment() -> None:
    model = _Model()
    await run(f"(src={IMG_URL};accept=image/png)!'d'", _Web(), process=model, attachments=[DOC])
    assert model.seen == [(DOC, IMG)]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", GUARD_CODES)
async def test_guard_refusal_on_the_bytes_fetch_fails_the_run_unchanged(code: ErrorCode) -> None:
    model = _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(
            f"(src={IMG_URL};accept=image/png)!'d'", _Web(refuse={IMG_URL: code}), process=model
        )
    assert caught.value.code == code
    assert model.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("code", GUARD_CODES)
async def test_guard_refusal_on_the_text_fetch_surfaces_as_today(code: ErrorCode) -> None:
    class _Refusing(_Web):
        async def fetch_ex(self, request: FetchRequest) -> FetchResult:
            raise ResolutionError(f"guard refused {request.target!r}", code=code)

    io, model = _Refusing(), _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={TXT_URL})!'d'", io, process=model)
    assert caught.value.code == code
    assert io.byte_targets == []


@pytest.mark.asyncio
async def test_failed_optional_https_text_source_is_still_dropped() -> None:
    # D5 exemption: a lazy https source keeps today's ;optional behaviour.
    model = _Model()
    assert await run("(src=https://gone.example/x;optional, 'kept')!'d'", _Web(), process=model)
    assert model.seen == [()]
    assert "kept" in model.payloads[0]


@pytest.mark.asyncio
async def test_non_text_https_in_collection_position_still_fails_unsupported_content_type() -> None:
    with pytest.raises(ResolutionError) as caught:
        await run(f"({IMG_URL}*($item)!'d')!'r'", _Web(), process=_Model())
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE


@pytest.mark.asyncio
async def test_non_text_https_outside_a_run_still_fails_unsupported_content_type() -> None:
    node = WebFetchNode(IMG_URL)
    with pytest.raises(ResolutionError) as caught:
        await node.resolve({}, ExecutionContext(_Web()))
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
