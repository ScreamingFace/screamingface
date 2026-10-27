"""Round-7 conformance: opt-in ``https://`` attachment sources (#1450 F1b at ``357ce4199``).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY: as an ensemble author I write ``src=https://…/photo.png;accept=image/png`` and every
model call in the run receives that image, fetched once before any model is called; every
other ``https://`` source stays the text source it is today.

INVARIANT (F1b round 8): an ``https://`` source is an attachment source iff its ``;accept=`` is
exactly one lower-case attachment type (round 7's range set, narrowed; see the round-8 tests).
Attachment sources are pre-materialized from a reachability-aware manifest before the first
model call, one flight per identity ``(URL, accept, ;optional, ;t=, ;retry=)``, listed in
manifest preorder and frozen. Text sources keep today's lazy, per-occurrence semantics exactly.
"""

from __future__ import annotations

import asyncio
import hashlib

import httpx
import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer
from url4.peer._http import status_for_code

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-round7"
JPG = b"\xff\xd8\xff\xe0round7-jpeg"
PDF = b"%PDF-1.7 round7"
IMG_URL = "https://img.example/photo.png"
JPG_URL = "https://img.example/photo.jpg"
PDF_URL = "https://doc.example/paper.pdf"
TXT_URL = "https://txt.example/notes.txt"
ROWS_URL = "https://rows.example/rows.json"


def _att(body: bytes, media_type: str) -> Attachment:
    return Attachment(f"sha256:{hashlib.sha256(body).hexdigest()}", media_type, body)


IMG = _att(PNG, "image/png")
JPEG = _att(JPG, "image/jpeg")
DOC = _att(PDF, "application/pdf")


class _Web(StaticIOLayer):
    """A fake web recording every text and bytes fetch into one shared event log."""

    def __init__(
        self,
        fetch_map: dict[str, str | bytes] | None = None,
        media_types: dict[str, str] | None = None,
        events: list[str] | None = None,
    ) -> None:
        base: dict[str, str | bytes] = {
            IMG_URL: PNG,
            JPG_URL: JPG,
            PDF_URL: PDF,
            TXT_URL: "plain notes",
            ROWS_URL: '["a", "b"]',
        }
        types = {
            IMG_URL: "image/png",
            JPG_URL: "image/jpeg",
            PDF_URL: "application/pdf",
            TXT_URL: "text/plain",
            ROWS_URL: "application/json",
        }
        super().__init__(
            {**base, **(fetch_map or {})}, media_types={**types, **(media_types or {})}
        )
        self.events = events if events is not None else []
        self.gates: dict[str, asyncio.Event] = {}
        self.done: dict[str, asyncio.Event] = {}
        self.retryable: dict[str, int] = {}

    def text_fetches(self, target: str) -> int:
        return self.events.count(f"text:{target}")

    def byte_fetches(self, target: str | None = None) -> int:
        if target is None:
            return sum(1 for event in self.events if event.startswith("bytes:"))
        return self.events.count(f"bytes:{target}")

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.events.append(f"text:{request.target}")
        self._maybe_transient(request.target)
        return await super().fetch_ex(request)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.events.append(f"bytes:{request.target}")
        gate = self.gates.get(request.target)
        if gate is not None:
            await gate.wait()
        self._maybe_transient(request.target)
        got = await super().fetch_bytes(request)
        self.events.append(f"done:{request.target}")
        self.done.setdefault(request.target, asyncio.Event()).set()
        return got

    def _maybe_transient(self, target: str) -> None:
        left = self.retryable.get(target, 0)
        if left:
            self.retryable[target] = left - 1
            raise ResolutionError(f"flaky {target!r}", code=ErrorCode.TIMEOUT, permanent=False)


class _Model:
    """A ``process`` hook recording payloads, attachments, and its place in the event log."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.payloads: list[str] = []
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.events.append("model")
        self.payloads.append(sources)
        self.seen.append(current_attachments())
        return "ok"


def _pair() -> tuple[_Web, _Model]:
    events: list[str] = []
    return _Web(events=events), _Model(events)


def _before_first_model(events: list[str]) -> list[str]:
    return events[: events.index("model")] if "model" in events else list(events)


# -- reachability: an empty collection does no I/O ---------------------------------------


@pytest.mark.asyncio
async def test_empty_collection_causes_no_attachment_io_and_the_run_succeeds() -> None:
    events: list[str] = []
    io, model = _Web({ROWS_URL: "[]"}, events=events), _Model(events)
    text = f"({ROWS_URL}*(src={IMG_URL};accept=image/png)!'d')!'r'"
    assert await run(text, io, process=model) == "ok"
    assert io.byte_fetches() == 0
    # The collection is resolved once: in the admission phase, and reused by execution.
    assert io.text_fetches(ROWS_URL) == 1
    assert all(seen == () for seen in model.seen)


@pytest.mark.asyncio
async def test_reachable_body_source_is_fetched_once_before_the_first_model_call() -> None:
    io, model = _pair()
    text = f"({ROWS_URL}*(src={IMG_URL};accept=image/png)!'d')!'r'"
    assert await run(text, io, process=model) == "ok"
    assert io.text_fetches(ROWS_URL) == 1  # reused, not fetched again by execution
    assert io.byte_fetches(IMG_URL) == 1  # two rows, one identity, one flight
    assert f"done:{IMG_URL}" in _before_first_model(io.events)
    assert len(model.seen) == 3  # two rows and the reduce
    assert all(seen == (IMG,) for seen in model.seen)


@pytest.mark.asyncio
async def test_sliced_to_zero_rows_causes_no_attachment_io() -> None:
    io, model = _pair()
    text = f"({ROWS_URL}*(src={IMG_URL};accept=image/png)!'d';iteration.slice=0:0)!'r'"
    await run(text, io, process=model)
    assert io.byte_fetches() == 0


@pytest.mark.asyncio
async def test_inline_collection_rows_make_the_body_reachable() -> None:
    io, model = _pair()
    await run(f"(('a')*(src={IMG_URL};accept=image/png)!'d')!'r'", io, process=model)
    assert io.byte_fetches(IMG_URL) == 1
    assert model.seen[0] == (IMG,)


# -- text sources are unchanged ----------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_text_occurrences_with_differing_policies_behave_as_today() -> None:
    io, model = _pair()
    text = f"(src={TXT_URL};t=5, src={TXT_URL};retry=1, src={TXT_URL};optional)!'d'"
    await run(text, io, process=model)
    # Lazy and per occurrence: three fetches, no bytes fetch, nothing attached.
    assert io.text_fetches(TXT_URL) == 3
    assert io.byte_fetches() == 0
    assert model.seen == [()]
    assert model.payloads[0].count("plain notes") == 3


@pytest.mark.asyncio
async def test_text_occurrence_retry_stays_per_occurrence() -> None:
    io, model = _pair()
    io.retryable[TXT_URL] = 1  # the first text fetch fails transiently
    await run(f"(src={TXT_URL};retry=1, src={TXT_URL};optional)!'d'", io, process=model)
    # Today's semantics: each occurrence fetches on its own; the failure costs one more fetch.
    assert io.text_fetches(TXT_URL) == 3
    assert io.byte_fetches() == 0


@pytest.mark.asyncio
async def test_text_source_with_any_non_media_accept_stays_text() -> None:
    io, model = _pair()
    await run(
        f"(src={TXT_URL};accept=text/plain, src={TXT_URL};accept=application/json)!'d'",
        io,
        process=model,
    )
    assert io.text_fetches(TXT_URL) == 2
    assert io.byte_fetches() == 0
    assert model.seen == [()]


def _http_serving(body: bytes, content_type: str | None, seen: list[str]) -> HttpIOLayer:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        headers = {} if content_type is None else {"content-type": content_type}
        return httpx.Response(200, content=body, headers=headers)

    return HttpIOLayer(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "body", "decoded"),
    [
        (None, b"no header", "no header"),
        ("application/xml", b"<a>x</a>", "<a>x</a>"),
        ("application/ld+json", b'{"a": 1}', '{"a": 1}'),
        ("application/yaml", b"a: 1", "a: 1"),
        ("application/x-custom; charset=utf-8", b"custom text", "custom text"),
        ("text/plain; charset=latin-1", "café".encode("latin-1"), "café"),
    ],
)
async def test_text_sources_decode_exactly_as_today(
    content_type: str | None, body: bytes, decoded: str
) -> None:
    seen: list[str] = []
    model, baseline = _Model(), _Model()
    io = _http_serving(body, content_type, seen)
    await run("(src=https://t.example/doc)!'d'", io, process=model)
    await run(f"(src='{decoded}')!'d'", StaticIOLayer(), process=baseline)
    assert model.payloads == baseline.payloads
    assert model.seen == [()]
    assert seen == ["https://t.example/doc"]  # one GET, the text path's own


# -- classification of attachment sources ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("accept", "media_type"),
    [
        ("image/png", None),  # no Content-Type at all
        ("image/png", "text/plain"),
        ("image/png", "image/jpeg"),  # in the set, but not the requested range
        ("image/gif", "application/pdf"),
        ("application/pdf", "image/png"),
        ("image/png", "image/svg+xml"),
        ("image/png", "text/plain, image/png"),  # not exactly one media type
    ],
)
async def test_required_attachment_with_a_wrong_or_missing_type_fails_before_any_model_call(
    accept: str, media_type: str | None
) -> None:
    events: list[str] = []
    types = {} if media_type is None else {"https://x.example/f": media_type}
    io = _Web({"https://x.example/f": PNG}, types, events=events)
    model = _Model(events)
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src=https://x.example/f;accept={accept})!'d'", io, process=model)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True
    assert model.seen == []
    assert io.byte_fetches() == 1  # one binary-safe fetch, no second (text) fetch


@pytest.mark.asyncio
async def test_optional_attachment_with_a_wrong_type_is_omitted() -> None:
    io, model = _pair()
    text = f"(src={TXT_URL};accept=image/png;optional, 'kept')!'d'"
    assert await run(text, io, process=model) == "ok"
    assert model.seen == [()]
    assert "kept" in model.payloads[0]
    assert io.byte_fetches(TXT_URL) == 1
    assert io.text_fetches(TXT_URL) == 0  # an omitted attachment is never re-fetched as text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("accept", "url", "expected"),
    [
        ("image/png", IMG_URL, IMG),
        ("image/jpeg", JPG_URL, JPEG),
        ("application/pdf", PDF_URL, DOC),
    ],
)
async def test_attachment_source_attaches_and_reads_as_its_url(
    accept: str, url: str, expected: Attachment
) -> None:
    io, model = _pair()
    assert await run(f"(src={url};accept={accept})!'d'", io, process=model) == "ok"
    assert model.seen == [(expected,)]
    assert model.seen[0][0].body == expected.body
    assert url in model.payloads[0]
    assert io.text_fetches(url) == 0


@pytest.mark.asyncio
async def test_content_type_parameters_and_case_are_ignored_by_classification() -> None:
    io = _Web(media_types={IMG_URL: "IMAGE/PNG; name=photo.png"})
    model = _Model()
    await run(f"(src={IMG_URL};accept=image/png)!'d'", io, process=model)
    assert model.seen == [(IMG,)]
    assert model.seen[0][0].media_type == "image/png"


# -- the text path and the attachment path are independent -------------------------------


@pytest.mark.asyncio
async def test_same_url_with_and_without_media_accept_takes_both_paths_independently() -> None:
    io, model = _pair()
    text = f"(src={TXT_URL};accept=image/png;optional, src={TXT_URL})!'d'"
    await run(text, io, process=model)
    assert io.byte_fetches(TXT_URL) == 1  # the attachment path: refused, omitted
    assert io.text_fetches(TXT_URL) == 1  # the text path: today's lazy fetch
    assert model.seen == [()]
    assert "plain notes" in model.payloads[0]


@pytest.mark.asyncio
async def test_a_required_attachment_refusal_stops_the_run_before_its_text_twin_is_fetched() -> (
    None
):
    io, model = _pair()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={TXT_URL};accept=image/png, src={TXT_URL})!'d'", io, process=model)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert io.text_fetches(TXT_URL) == 0
    assert model.seen == []


# -- identity: one flight, one attachment, manifest preorder ----------------------------


@pytest.mark.asyncio
async def test_identical_identities_in_parallel_siblings_share_one_flight() -> None:
    io, model = _pair()
    a = f"src={IMG_URL};accept=image/png"
    text = f"(({a})!'m1', ({a})!'m2', {a})!'d'"
    assert await run(text, io, process=model) == "ok"
    assert io.byte_fetches(IMG_URL) == 1
    assert len(model.seen) == 3
    assert all(seen == (IMG,) for seen in model.seen)


@pytest.mark.asyncio
async def test_identities_differing_in_policy_run_and_list_separately() -> None:
    io, model = _pair()
    text = (
        f"(src={IMG_URL};accept=image/png, src={IMG_URL};accept=image/png;t=5,"
        f" src={IMG_URL};accept=image/png;retry=1, src={IMG_URL};accept=image/png;optional)!'d'"
    )
    await run(text, io, process=model)
    # Four identities, four flights, four entries — even though the bytes are equal.
    assert io.byte_fetches(IMG_URL) == 4
    assert model.seen == [(IMG, IMG, IMG, IMG)]


@pytest.mark.asyncio
async def test_reversed_completion_order_still_yields_manifest_preorder() -> None:
    io, model = _pair()
    io.gates[IMG_URL] = gate = asyncio.Event()

    pdf_done = io.done.setdefault(PDF_URL, asyncio.Event())

    async def release_after_pdf() -> None:
        await pdf_done.wait()
        gate.set()

    releaser = asyncio.create_task(release_after_pdf())
    text = f"(src={IMG_URL};accept=image/png, src={PDF_URL};accept=application/pdf)!'d'"
    await run(text, io, process=model)
    await releaser
    assert io.events.index(f"done:{PDF_URL}") < io.events.index(f"done:{IMG_URL}")
    assert model.seen == [(IMG, DOC)]


@pytest.mark.asyncio
async def test_retry_policy_runs_inside_the_one_flight_and_execution_never_refetches() -> None:
    io, model = _pair()
    io.retryable[IMG_URL] = 2
    text = f"(src={IMG_URL};accept=image/png;retry=2, src={IMG_URL};accept=image/png;retry=2)!'d'"
    await run(text, io, process=model)
    assert io.byte_fetches(IMG_URL) == 3  # the first send and two retries, shared
    assert model.seen == [(IMG,)]


@pytest.mark.asyncio
async def test_attachments_follow_case_attachments_and_blob_refs_in_preorder() -> None:
    blob_hex = hashlib.sha256(PDF).hexdigest()
    io = _Web({f"/blob/sha256/{blob_hex}": PDF}, {f"/blob/sha256/{blob_hex}": "application/pdf"})
    model = _Model()
    text = f"(src=/blob/sha256/{blob_hex}, src={IMG_URL};accept=image/png)!'d'"
    await run(text, io, process=model, attachments=[JPEG])
    assert model.seen == [(JPEG, DOC, IMG)]


# -- static targets ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attachment_source_under_a_model_derived_collection_is_not_static() -> None:
    io, model = _pair()
    text = f"((src='a')!'list'*(src={IMG_URL};accept=image/png)!'d')!'r'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model)
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert caught.value.permanent is True
    assert io.events == []  # before any fetch
    assert model.seen == []  # and before any model call


@pytest.mark.asyncio
async def test_attachment_source_under_a_model_derived_binding_is_not_static() -> None:
    io, model = _pair()
    text = f"(xs=(src='a')!'list', $xs*(src={IMG_URL};accept=image/png)!'d')!'r'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model)
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert io.events == []


@pytest.mark.asyncio
async def test_text_source_under_a_model_derived_collection_is_never_refused() -> None:
    io, model = _pair()

    async def lister(sources: str, intent: str | None, scope: object) -> str:
        await model(sources, intent, scope)
        return '["row"]'

    await run(f"((src='a')!'list'*(src={TXT_URL})!'d')!'r'", io, process=lister)
    assert io.byte_fetches() == 0
    assert io.text_fetches(TXT_URL) == 1  # lazily, inside the one row, as today


# -- per-run caps ------------------------------------------------------------------------


def _many(count: int, size: int = 8) -> tuple[_Web, _Model, str]:
    urls = [f"https://img.example/{i}.png" for i in range(count)]
    bodies = {url: bytes([i % 256]) * size for i, url in enumerate(urls)}
    events: list[str] = []
    io = _Web(dict(bodies), dict.fromkeys(urls, "image/png"), events=events)
    text = "(" + ", ".join(f"src={url};accept=image/png" for url in urls) + ")!'d'"
    return io, _Model(events), text


@pytest.mark.asyncio
async def test_twenty_attachments_are_within_the_cap() -> None:
    io, model, text = _many(20)
    assert await run(text, io, process=model) == "ok"
    assert len(model.seen[0]) == 20


@pytest.mark.asyncio
async def test_twenty_one_attachments_are_refused_before_any_model_call() -> None:
    io, model, text = _many(21)
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_MANY
    assert caught.value.permanent is True
    assert model.seen == []


@pytest.mark.asyncio
async def test_case_attachments_count_toward_the_entry_cap() -> None:
    io, model, text = _many(20)
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model, attachments=[DOC])
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_MANY


@pytest.mark.asyncio
async def test_eight_million_bytes_are_within_the_cap() -> None:
    io, model, text = _many(2, 4_000_000)
    assert await run(text, io, process=model) == "ok"
    assert sum(len(a.body) for a in model.seen[0]) == 8_000_000


@pytest.mark.asyncio
async def test_one_byte_over_eight_million_is_refused_before_any_model_call() -> None:
    events: list[str] = []
    big = {
        "https://img.example/a.png": b"a" * 4_000_000,
        "https://img.example/b.png": b"b" * 4_000_000,
    }
    io = _Web({**big, PDF_URL: b"%"}, dict.fromkeys(big, "image/png"), events=events)
    model = _Model(events)
    sources = [f"src={url};accept=image/png" for url in big] + [
        f"src={PDF_URL};accept=application/pdf"
    ]
    with pytest.raises(ResolutionError) as caught:
        await run("(" + ", ".join(sources) + ")!'d'", io, process=model)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert caught.value.permanent is True
    assert model.seen == []


def test_image_wildcard_is_not_an_attachment_type_and_not_authorable() -> None:
    # AIDEV-NOTE (round 8): no wildcard — ``image/*`` is not an attachment type, classifies
    # nothing, and the exec-value grammar (spec §4.2) refuses ``*`` anyway.
    from url4.core.errors import ParseError
    from url4.core.grammar import parse
    from url4.dag.attachment_sources import AttachmentIdentity, classify, is_attachment_accept

    assert not is_attachment_accept("image/*")
    wildcard = AttachmentIdentity(IMG_URL, "image/*")
    with pytest.raises(ResolutionError):
        classify(wildcard, "image/webp")
    with pytest.raises(ResolutionError):
        classify(wildcard, "image/svg+xml")
    with pytest.raises(ParseError):
        parse(f"(src={IMG_URL};accept=image/*)!'d'")


def test_accept_with_any_non_attachment_range_is_a_text_source() -> None:
    from url4.dag.attachment_sources import is_attachment_accept

    assert not is_attachment_accept(None)
    assert not is_attachment_accept("")
    assert not is_attachment_accept("image/png, text/plain")
    assert not is_attachment_accept("application/json")
    assert not is_attachment_accept("IMAGE/PNG, application/pdf")  # round 8: no list, no case
    assert is_attachment_accept("application/pdf")


def test_new_codes_map_to_their_proposed_statuses() -> None:
    assert status_for_code(ErrorCode.SOURCE_NOT_STATIC, permanent=True) == 422
    assert status_for_code(ErrorCode.ATTACHMENTS_TOO_MANY, permanent=True) == 413
    assert status_for_code(ErrorCode.ATTACHMENTS_TOO_LARGE, permanent=True) == 413


# -- collection shapes in the admission phase --------------------------------------------


@pytest.mark.asyncio
async def test_relative_collection_is_resolved_once_and_makes_the_body_reachable() -> None:
    events: list[str] = []
    io, model = _Web({"/rows": '["a"]'}, events=events), _Model(events)
    await run(f"(/rows*(src={IMG_URL};accept=image/png)!'d')!'r'", io, process=model)
    assert io.text_fetches("/rows") == 1
    assert io.byte_fetches(IMG_URL) == 1


@pytest.mark.asyncio
async def test_literal_text_collection_rows_make_the_body_reachable() -> None:
    io, model = _pair()
    await run(f"('[\"a\"]'*(src={IMG_URL};accept=image/png)!'d')!'r'", io, process=model)
    assert io.byte_fetches(IMG_URL) == 1
    assert model.seen[0] == (IMG,)


@pytest.mark.asyncio
async def test_bound_collection_with_a_guard_is_resolved_once() -> None:
    io, model = _pair()
    text = f"(xs:src={ROWS_URL};t=5, $xs*(src={IMG_URL};accept=image/png)!'d')!'r'"
    await run(text, io, process=model)
    assert io.text_fetches(ROWS_URL) == 1
    assert io.byte_fetches(IMG_URL) == 1


@pytest.mark.asyncio
async def test_a_failing_collection_fails_as_today_without_attachment_io() -> None:
    io, model = _pair()
    io.retryable[ROWS_URL] = 1  # the admission fetch fails; execution replays that failure
    with pytest.raises(ResolutionError) as caught:
        await run(f"({ROWS_URL}*(src={IMG_URL};accept=image/png)!'d')!'r'", io, process=model)
    assert caught.value.code == ErrorCode.TIMEOUT
    assert io.text_fetches(ROWS_URL) == 1  # replayed, not fetched a second time
    assert io.byte_fetches() == 0


@pytest.mark.asyncio
async def test_an_unparseable_collection_fails_as_today_without_attachment_io() -> None:
    io = _Web({ROWS_URL: "{not json"})
    with pytest.raises(Exception) as caught:
        await run(f"({ROWS_URL}*(src={IMG_URL};accept=image/png)!'d')!'r'", io, process=_Model())
    assert getattr(caught.value, "code", None) != ErrorCode.SOURCE_NOT_STATIC
    assert io.byte_fetches() == 0
    assert io.text_fetches(ROWS_URL) == 1


@pytest.mark.asyncio
async def test_attachment_source_under_a_relative_call_collection_is_not_static() -> None:
    io, model = _pair()
    text = f"(/route(x)!'list'*(src={IMG_URL};accept=image/png)!'d')!'r'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=model)
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert io.events == []


@pytest.mark.asyncio
async def test_a_row_reference_collection_is_conservatively_reachable() -> None:
    io, model = _pair()
    text = f"({ROWS_URL}*($item*(src={IMG_URL};accept=image/png)!'d')!'m')!'r'"
    await run(text, io, process=model)
    assert io.byte_fetches(IMG_URL) == 1
    assert f"done:{IMG_URL}" in _before_first_model(io.events)


# -- adapters and execution outside the manifest -----------------------------------------


class _TextOnly:
    """An adapter with a text port only: no binary-safe fetch."""

    async def fetch(self, target: str, *, relative: bool) -> str:
        return "text"


@pytest.mark.asyncio
async def test_attachment_source_on_an_adapter_without_bytes_fetch_is_unsupported() -> None:
    model = _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={IMG_URL};accept=image/png)!'d'", _TextOnly(), process=model)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert model.seen == []


@pytest.mark.asyncio
async def test_prebuilt_graph_has_no_manifest_so_its_attachment_source_is_not_static() -> None:
    from url4.dag import compile_expression

    io, model = _pair()
    graph = compile_expression(f"(src={IMG_URL};accept=image/png)!'d'")
    with pytest.raises(ResolutionError) as caught:
        await run(graph, io, process=model)
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert io.byte_fetches() == 0
    assert model.seen == []


@pytest.mark.asyncio
async def test_attachment_source_outside_a_run_keeps_the_text_path() -> None:
    from url4.dag import compile_expression
    from url4.dag.node import ExecutionContext
    from url4.dag.nodes import WebFetchNode

    graph = compile_expression(f"(src={TXT_URL};accept=image/png)!'d'")
    fetches = [node for node in graph.walk() if isinstance(node, WebFetchNode)]
    assert [node.attachment is not None for node in fetches] == [True]
    io = _Web()
    assert await fetches[0].resolve({}, ExecutionContext(io)) == "plain notes"
    assert io.byte_fetches() == 0
