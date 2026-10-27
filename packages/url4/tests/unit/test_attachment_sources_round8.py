"""Round 8 + owner decisions A/E (2026-10-27): one exact type, no Q-B, caps on every path.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F1b at ``4a020cc39``).
STORY: as an ensemble author I opt a picture in with exactly ``;accept=image/png``; any other
``https://`` source is the text source it always was and never becomes an attachment.

INVARIANT (round 8): an attachment source's ``;accept=`` is EXACTLY one lower-case attachment
type; the response's bare type must EQUAL it. Anything else is a text source.
INVARIANT (owner decision A): a text source is never attached, even when its body is not text
(today's ``unsupported_content_type``), and is never fetched as bytes.
INVARIANT (owner decision E): the per-run caps (20 entries / 8,000,000 decoded bytes over the
WHOLE ``attachments[]``) are enforced while the list is built, before the first model call; no
path adds to the list after the run starts.
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments, current_run_files
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-round8"
PDF = b"%PDF-1.7 round8"
PNG_HEX = hashlib.sha256(PNG).hexdigest()
IMG_URL = "https://img.example/photo.png"
PDF_URL = "https://doc.example/paper.pdf"
BLOB = f"/blob/sha256/{PNG_HEX}"
ATTACHMENT_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"]


def _att(body: bytes, media_type: str) -> Attachment:
    return Attachment(f"sha256:{hashlib.sha256(body).hexdigest()}", media_type, body)


class _Web(StaticIOLayer):
    """A fake web recording text and bytes fetches; ``gates`` hold a bytes fetch open."""

    def __init__(
        self, fetch_map: dict[str, str | bytes] | None = None, types: dict[str, str] | None = None
    ) -> None:
        super().__init__(
            {IMG_URL: PNG, PDF_URL: PDF, BLOB: PNG, **(fetch_map or {})},
            media_types={
                IMG_URL: "image/png",
                PDF_URL: "application/pdf",
                BLOB: "image/png",
                **(types or {}),
            },
        )
        self.events: list[str] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.cancelled: list[str] = []

    def byte_fetches(self, target: str | None = None) -> int:
        hits = [e for e in self.events if e.startswith("bytes:")]
        return len(hits) if target is None else hits.count(f"bytes:{target}")

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.events.append(f"text:{request.target}")
        return await super().fetch_ex(request)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.events.append(f"bytes:{request.target}")
        gate = self.gates.get(request.target)
        if gate is not None:
            try:
                await gate.wait()
            except asyncio.CancelledError:
                self.cancelled.append(request.target)
                raise
        return await super().fetch_bytes(request)


class _Model:
    def __init__(self) -> None:
        self.payloads: list[str] = []
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.payloads.append(sources)
        self.seen.append(current_attachments())
        return "ok"


# -- A: a text source is never attached --------------------------------------------------


@pytest.mark.asyncio
async def test_text_source_with_a_non_text_body_fails_as_today_and_is_never_fetched_as_bytes() -> (
    None
):
    io, model = _Web(), _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={IMG_URL})!'d'", io, process=model)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert model.seen == []
    assert io.byte_fetches() == 0


@pytest.mark.asyncio
async def test_optional_text_source_with_a_non_text_body_is_dropped_not_attached() -> None:
    io, model = _Web(), _Model()
    assert await run(f"(src={IMG_URL};optional, 'kept')!'d'", io, process=model) == "ok"
    assert model.seen == [()]
    assert "kept" in model.payloads[0]
    assert io.byte_fetches() == 0


@pytest.mark.asyncio
async def test_text_source_next_to_an_attachment_source_adds_nothing_after_run_start() -> None:
    io, model = _Web(), _Model()
    text = f"(src={PDF_URL};accept=application/pdf, src={IMG_URL};optional)!'d'"
    assert await run(text, io, process=model) == "ok"
    assert model.seen == [(_att(PDF, "application/pdf"),)]
    assert io.byte_fetches(IMG_URL) == 0


# -- B: exactly one lower-case attachment type --------------------------------------------


@pytest.mark.parametrize("accept", ATTACHMENT_TYPES)
def test_each_attachment_type_alone_opts_a_source_in(accept: str) -> None:
    from url4.dag.attachment_sources import is_attachment_accept

    assert is_attachment_accept(accept)


@pytest.mark.parametrize(
    "accept",
    [
        None,
        "",
        "image/*",
        "IMAGE/PNG",
        "Image/Png",
        " image/png",
        "image/png ",
        "image/png, application/pdf",
        "image/png,image/png",
        "image/svg+xml",
        "image/png;q=1",
        "text/plain",
    ],
)
def test_anything_but_exactly_one_lower_case_attachment_type_is_a_text_source(
    accept: str | None,
) -> None:
    from url4.dag.attachment_sources import is_attachment_accept

    assert not is_attachment_accept(accept)


@pytest.mark.asyncio
async def test_upper_case_accept_is_a_text_source_on_the_wire() -> None:
    io, model = _Web(), _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={IMG_URL};accept=IMAGE/PNG)!'d'", io, process=model)
    # The text path's own refusal of a non-text body: no bytes fetch, nothing attached.
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert io.byte_fetches() == 0
    assert io.events == [f"text:{IMG_URL}"]


@pytest.mark.parametrize(
    ("accept", "media_type"),
    [
        ("image/png", "image/png"),
        ("image/png", "IMAGE/PNG; name=a.png"),
        ("image/webp", "image/webp"),
        ("application/pdf", "application/pdf; charset=binary"),
    ],
)
def test_response_type_equal_to_the_accept_type_classifies(accept: str, media_type: str) -> None:
    from url4.dag.attachment_sources import AttachmentIdentity, classify

    assert classify(AttachmentIdentity(IMG_URL, accept), media_type) == accept


@pytest.mark.parametrize(
    ("accept", "media_type"),
    [
        ("image/png", "image/jpeg"),
        ("image/jpeg", "image/png"),
        ("image/gif", "image/webp"),
        ("application/pdf", "image/png"),
        ("image/png", None),
        ("image/png", "image/png, image/png"),
    ],
)
def test_response_type_not_equal_to_the_accept_type_is_unsupported(
    accept: str, media_type: str | None
) -> None:
    from url4.dag.attachment_sources import AttachmentIdentity, classify

    with pytest.raises(ResolutionError) as caught:
        classify(AttachmentIdentity(IMG_URL, accept), media_type)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True


# -- E: caps on every adding path, before the first model call ---------------------------


def _sources(count: int) -> tuple[dict[str, str | bytes], dict[str, str], list[str]]:
    urls = [f"https://img.example/{i}.png" for i in range(count)]
    bodies: dict[str, str | bytes] = {url: PNG + str(i).encode() for i, url in enumerate(urls)}
    return bodies, dict.fromkeys(urls, "image/png"), urls


@pytest.mark.asyncio
async def test_too_many_required_attachments_are_refused_before_any_attachment_fetch() -> None:
    bodies, types, urls = _sources(21)
    io, model = _Web(bodies, types), _Model()
    text = "(" + ", ".join(f"src={url};accept=image/png" for url in urls) + ")!'d'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_MANY
    assert io.byte_fetches() == 0
    assert model.seen == []


@pytest.mark.asyncio
async def test_case_and_blob_refs_count_before_any_attachment_fetch() -> None:
    bodies, types, urls = _sources(19)
    io, model = _Web(bodies, types), _Model()
    text = "(" + ", ".join([f"src={BLOB}", *(f"src={u};accept=image/png" for u in urls)]) + ")!'d'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model, attachments=[_att(PDF, "application/pdf")])
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_MANY
    # The local blob ref is verified first (Case, blob refs, then flights); no flight starts.
    assert io.events == [f"bytes:{BLOB}"]


@pytest.mark.asyncio
async def test_an_omitted_optional_identity_does_not_count_toward_the_entry_cap() -> None:
    bodies, types, urls = _sources(20)
    io, model = _Web(bodies, types), _Model()
    text = (
        "("
        + ", ".join(f"src={url};accept=image/png" for url in urls)
        + ", src=https://gone.example/x.png;accept=image/png;optional)!'d'"
    )
    assert await run(text, io, process=model) == "ok"
    assert len(model.seen[0]) == 20


@pytest.mark.asyncio
async def test_byte_cap_breach_cancels_the_flights_still_in_progress() -> None:
    half = 4_000_001
    big = {"https://img.example/a.png": b"a" * half, "https://img.example/b.png": b"b" * half}
    io = _Web({**big, PDF_URL: PDF}, dict.fromkeys(big, "image/png"))
    io.gates[PDF_URL] = asyncio.Event()  # never set: only a cap refusal can end this run
    model = _Model()
    sources = [f"src={url};accept=image/png" for url in big] + [
        f"src={PDF_URL};accept=application/pdf"
    ]
    with pytest.raises(ResolutionError) as caught:
        await asyncio.wait_for(run("(" + ", ".join(sources) + ")!'d'", io, process=model), 5)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert io.cancelled == [PDF_URL]
    assert model.seen == []


@pytest.mark.asyncio
async def test_case_bytes_count_before_any_attachment_fetch_is_spent() -> None:
    # WHY the blob ref breaches: Case bytes are charged first, local blob refs next, and both
    # before any https flight, so the gated (never-answered) flight is never started.
    io, model = _Web(), _Model()
    case = [_att(b"c" * 8_000_000, "application/pdf")]
    io.gates[IMG_URL] = asyncio.Event()  # never set
    text = f"(src={BLOB}, src={IMG_URL};accept=image/png)!'d'"
    with pytest.raises(ResolutionError) as caught:
        await asyncio.wait_for(run(text, io, process=model, attachments=case), 5)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert io.byte_fetches(IMG_URL) == 0
    assert model.seen == []


@pytest.mark.asyncio
async def test_the_bound_list_cannot_grow_after_the_run_starts() -> None:
    io = _Web()
    lists: list[tuple[Attachment, ...]] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        files = current_run_files()
        assert files is not None
        # INVARIANT: frozen — no adder, slots a tuple, the manifest a read-only view.
        assert not hasattr(files, "attach_fetched")
        assert isinstance(files.slots, tuple)
        assert not hasattr(files.manifest, "__setitem__")
        lists.append(files.attachments)
        return "ok"

    text = f"(src={IMG_URL};accept=image/png, src={PDF_URL};optional)!'d'"
    await run(text, io, process=model)
    assert lists == [(_att(PNG, "image/png"),)]


@pytest.mark.asyncio
async def test_many_non_text_text_sources_can_no_longer_bypass_the_caps() -> None:
    # Regression (security review, owner decision E): under Q-B, 25 text sources with image
    # bodies attached lazily after run start, past the 20-entry cap. Now none attaches.
    bodies, types, urls = _sources(25)
    io, model = _Web(bodies, types), _Model()
    text = "(" + ", ".join(f"src={url};optional" for url in urls) + ", 'kept')!'d'"
    assert await run(text, io, process=model) == "ok"
    assert model.seen == [()]
    assert io.byte_fetches() == 0
